import asyncio
import hashlib
import hmac
import json
import os
import secrets
import time
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Literal
import httpx
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import Field
from .ai import AI
from .advisor import Advisor
from .catalogue import Catalogue, POLICY, ROOT
from .db import Database, dumps, get, listing, log, now, put, uid
from .kyc import extract_document, validate_kyc
from .schemas import Model, Profile, QuoteInput, Consent, SessionInput, Turn

def digest(value): return hashlib.sha256(value.encode()).hexdigest()
def fingerprint(value): return digest(dumps(value))
def normalized_mobile(value):
    value = value.lstrip('+')
    return '91' + value if len(value) == 10 else value

class Login(Model):
    mobile: str = Field(pattern=r'^\+?[1-9]\d{9,14}$')

class Verify(Login):
    code: str = Field(pattern=r'^\d{6}$')

class ConfirmDocument(Model):
    fields: dict[str, str]

class Checkout(Model):
    paymentOutcome: Literal['success','failure'] = 'success'
    idempotencyKey: str = Field(min_length=8, max_length=100)

class Sign(Model):
    accepted: bool
    signatoryName: str = Field(min_length=2, max_length=100)

class StatusEvent(Model):
    status: Literal['provisioning','installation_scheduled','activated','cancelled']
    message: str = Field(default='', max_length=500)

class Ticket(Model):
    message: str = Field(min_length=5, max_length=1000)

def create_app(overrides=None):
    load_dotenv(ROOT / 'backend/.env')
    settings = {**os.environ, **(overrides or {})}
    demo = settings.get('DEMO_MODE', 'true').lower() == 'true'
    internal_key = settings.get('INTERNAL_API_KEY', 'local-dev-only-change-me' if demo else '')
    if not internal_key or (not demo and internal_key == 'local-dev-only-change-me'): raise RuntimeError('Set a private INTERNAL_API_KEY outside demo mode')
    database = Database(settings.get('DATABASE_PATH', str(ROOT / 'backend/.runtime/app.sqlite3')))
    catalogue = Catalogue(settings.get('DATA_DIR'))
    ai = AI(settings)
    advisor = Advisor(catalogue, ai)
    tracker_url = settings.get('TRACKER_URL', 'http://127.0.0.1:3001').rstrip('/')
    tracker_headers = {'X-Tracker-Api-Key': settings.get('TRACKER_API_KEY','')}
    reference_date = date.fromisoformat(settings.get('REFERENCE_DATE', '2026-07-15'))
    upload_dir = Path(database.path).parent / 'documents'
    upload_dir.mkdir(exist_ok=True)

    def flush_outbox():
        delivered = 0
        with database.connect() as db, httpx.Client(timeout=3) as client:
            # Lock before reads so concurrent requests/workers cannot send the same job together.
            db.execute('BEGIN IMMEDIATE')
            failed_orders = set()
            for row in db.execute('SELECT * FROM outbox WHERE delivered=0 ORDER BY rowid LIMIT 25').fetchall():
                if row['order_id'] in failed_orders: continue
                db.execute('UPDATE outbox SET attempts=attempts+1 WHERE id=?', (row['id'],))
                try:
                    body = json.loads(row['body'])
                    response = client.post(tracker_url + row['path'], json=body, headers=tracker_headers)
                    if response.status_code == 409 and row['path'] == '/v1/orders':
                        existing = client.get(tracker_url + '/v1/orders/' + row['order_id'], headers=tracker_headers)
                        existing.raise_for_status(); stored = existing.json()['order']
                        if stored['customer'] != body['customer'] or stored['bundle'] != body['bundle']: raise ValueError('Conflicting Tracker order')
                    else: response.raise_for_status()
                    db.execute('UPDATE outbox SET delivered=1 WHERE id=?', (row['id'],)); delivered += 1
                except (httpx.HTTPError, ValueError, KeyError): failed_orders.add(row['order_id'])
        return delivered

    @asynccontextmanager
    async def lifespan(app):
        async def worker():
            while True:
                try: await asyncio.to_thread(flush_outbox)
                except Exception: pass  # Persisted pending jobs remain available for retry.
                await asyncio.sleep(5)
        task = asyncio.create_task(worker())
        yield
        task.cancel()
        try: await task
        except asyncio.CancelledError: pass

    app = FastAPI(title='Accel Business Shared Backend', version='1.0.0', lifespan=lifespan)
    app.state.database = database; app.state.catalogue = catalogue; app.state.ai = ai; app.state.flush_outbox = flush_outbox
    app.add_middleware(CORSMiddleware, allow_origins=settings.get('CORS_ORIGINS', 'http://127.0.0.1:5173,http://localhost:5173').split(','), allow_methods=['GET','POST','PUT'], allow_headers=['Authorization','Content-Type'])

    def internal(authorization: str = Header(default='')):
        if not hmac.compare_digest(authorization, 'Bearer ' + internal_key): raise HTTPException(401, 'Internal API authentication required')

    def customer(authorization: str = Header(default='')):
        if not authorization.startswith('Bearer '): raise HTTPException(401, 'Sign in first')
        with database.connect() as db:
            row = db.execute('SELECT customer FROM tokens WHERE hash=? AND expires>?', (digest(authorization[7:]), time.time())).fetchone()
            if not row: raise HTTPException(401, 'Session expired or invalid')
            return row['customer']

    def require_consent(db, owner, scope):
        rows = listing(db, 'consent', owner)
        last = next((c for c in rows if c['scope'] == scope), None)
        if not last or not last['accepted']: raise HTTPException(403, f'{scope} consent required')

    def new_session(db, owner, sid, channel, language='English'):
        result = {'id':sid, 'channel':channel, 'language':language, 'index':0, 'profile':{}, 'sources':{}, 'createdAt':now()}
        return put(db, 'session', sid, owner, result)

    @app.get('/health')
    def health(): return {'status':'ok', 'demoMode':demo, 'aiConfigured':bool(ai.key and ai.model), 'transcriptionConfigured':bool(ai.key and ai.transcription_model), 'referenceDate':reference_date.isoformat()}

    @app.get('/consent-notice')
    def notice(): return {'version':'2026-01', 'advice':'Store confirmed business answers to recommend catalogue services.', 'kyc':'Extract document fields and compare with synthetic registries. Documents stay on this local prototype until explicitly deleted by its operator.', 'ai':'Send your answers or recordings to the configured AI provider for interpretation/transcription. Optional; text/options can use local rules.', 'mockPayments':True}

    @app.post('/auth/request-otp')
    def request_otp(body: Login):
        if not demo: raise HTTPException(503, 'A real SMS provider must be configured before public login')
        mobile = normalized_mobile(body.mobile); code = f'{secrets.randbelow(1000000):06d}'
        with database.connect() as db:
            existing = db.execute('SELECT expires FROM otps WHERE mobile=?', (mobile,)).fetchone()
            if existing and existing['expires'] > time.time() + 240: raise HTTPException(429, 'Wait a minute before requesting another code')
            db.execute('INSERT OR REPLACE INTO otps VALUES(?,?,?,0)', (mobile, digest(code), time.time()+300))
        return {'expiresInSeconds':300, 'demoCode':code, 'mock':True}

    @app.post('/auth/verify-otp')
    def verify_otp(body: Verify):
        mobile = normalized_mobile(body.mobile)
        valid = False
        with database.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM otps WHERE mobile=?', (mobile,)).fetchone()
            if row and row['expires'] > time.time() and row['attempts'] < 5:
                valid = hmac.compare_digest(row['hash'], digest(body.code))
                db.execute('UPDATE otps SET attempts=attempts+1 WHERE mobile=?', (mobile,))
            if valid:
                db.execute('DELETE FROM otps WHERE mobile=?', (mobile,))
                found = db.execute('SELECT id FROM customers WHERE mobile=?', (mobile,)).fetchone()
                owner = found['id'] if found else uid('CUS')
                db.execute('INSERT OR IGNORE INTO customers VALUES(?,?)', (owner, mobile))
                token = secrets.token_urlsafe(32)
                db.execute('INSERT INTO tokens VALUES(?,?,?)', (digest(token), owner, time.time()+86400))
        if not valid: raise HTTPException(401, 'Invalid or expired code')
        return {'token':token, 'customerId':owner, 'expiresInSeconds':86400, 'mock':True}

    @app.post('/consents')
    def consent(body: Consent, owner=Depends(customer)):
        with database.connect() as db:
            entry = {'id':uid('CON'), **body.model_dump(), 'version':'2026-01', 'at':now()}
            put(db, 'consent', entry['id'], owner, entry); log(db, owner, 'consent.' + body.scope)
            return entry

    @app.get('/catalogue')
    def products(): return {'products':list(catalogue.products.values()), 'pricePolicy':POLICY['price_policy'], 'synthetic':True}

    @app.get('/registry/{kind}/{identifier}')
    def registry(kind: Literal['gstin','udyam'], identifier: str, scenario: Literal['normal','down']='normal', owner=Depends(customer)):
        if scenario == 'down':
            if not demo: raise HTTPException(400, 'Failure simulation is only available in demo mode')
            raise HTTPException(503, 'Mock registry temporarily unavailable')
        item = catalogue.registries[kind].get(identifier.strip().upper())
        if not item: raise HTTPException(404, 'Not found in mock registry')
        return {'record':item, 'synthetic':True, 'active':item.get('status','Active').lower() == 'active'}

    @app.post('/profiles')
    def profile(body: Profile, owner=Depends(customer)):
        with database.connect() as db:
            require_consent(db, owner, 'advice')
            id = uid('PRO'); value = {'id':id, 'facts':body.model_dump(), 'sources':{k:{'source':'customer', 'confirmed':True} for k in body.model_fields_set}, 'updatedAt':now()}
            put(db, 'profile', id, owner, value); log(db, owner, 'profile.confirmed'); return value

    @app.put('/profiles/{id}')
    def update_profile(id: str, body: Profile, owner=Depends(customer)):
        with database.connect() as db:
            require_consent(db, owner, 'advice'); value = get(db, 'profile', id, owner)
            value.update(facts=body.model_dump(), updatedAt=now(), sources={k:{'source':'customer', 'confirmed':True} for k in body.model_fields_set})
            return put(db, 'profile', id, owner, value)

    @app.get('/profiles/{id}')
    def read_profile(id: str, owner=Depends(customer)):
        with database.connect() as db: return get(db, 'profile', id, owner)

    @app.post('/sessions')
    def session(body: SessionInput, owner=Depends(customer)):
        with database.connect() as db:
            require_consent(db, owner, 'advice')
            value = new_session(db, owner, uid('SES'), body.channel, body.language)
            if body.context:
                value['context'] = body.context.model_dump()
                consents = listing(db, 'consent', owner)
                allow_ai = next((c['accepted'] for c in consents if c['scope']=='ai'),False)
                value['profile'].update(adviceConsent=True,aiConsent=allow_ai,budget=body.context.budget)
                value['sources']['budget'] = {'source':'customer_form','confirmed':True}
                if body.context.businessName.strip():
                    value['profile']['businessName'] = body.context.businessName.strip()
                    value['sources']['businessName'] = {'source':'registration','confirmed':True}
                if body.context.contactName.strip(): value['profile']['contactName'] = body.context.contactName.strip()
                value['index'] = 2
                put(db,'session',value['id'],owner,value)
                log(db,owner,'advisor.started',body.channel)
            result = advisor.render(value)
            put(db,'session',value['id'],owner,value)
            return {'sessionId':value['id'], **result}

    @app.get('/sessions/{id}')
    def read_session(id: str, owner=Depends(customer)):
        with database.connect() as db: return get(db, 'session', id, owner)

    def do_turn(db, owner, body):
        result = advisor.turn(db, owner, body)
        session = get(db, 'session', body['sessionId'], owner)
        if result['completed'] and session.get('profile', {}).get('businessName'):
            fields = {k:v for k,v in session['profile'].items() if k in Profile.model_fields}
            facts = Profile.model_validate(fields).model_dump()
            profile_id = 'PRO-' + session['id']
            put(db, 'profile', profile_id, owner, {'id':profile_id,'facts':facts,'sources':session['sources'],'updatedAt':now()})
            result['profileId'] = profile_id
        return result

    @app.post('/sessions/{id}/turn')
    def session_turn(id: str, body: Turn, owner=Depends(customer)):
        if id != body.sessionId: raise HTTPException(422, 'Session ID mismatch')
        with database.connect() as db:
            db.execute('BEGIN IMMEDIATE'); require_consent(db, owner, 'advice')
            return do_turn(db, owner, body.model_dump())

    @app.post('/advisor/turn', dependencies=[Depends(internal)])
    def whatsapp_turn(body: Turn):
        if body.channel != 'whatsapp' or not body.customerId: raise HTTPException(422, 'WhatsApp customer identity required')
        with database.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            mobile = body.customerId
            if not mobile.isdigit() or not 10 <= len(mobile) <= 15:
                # Simulator identities never get linked to a real mobile account.
                if not demo or not mobile.startswith('demo-'): raise HTTPException(422, 'Invalid WhatsApp identity')
            existing = db.execute('SELECT id FROM customers WHERE mobile=?', (mobile,)).fetchone()
            owner = existing['id'] if existing else uid('CUS')
            db.execute('INSERT OR IGNORE INTO customers VALUES(?,?)', (owner, mobile))
            exists = db.execute("SELECT 1 FROM records WHERE kind='session' AND id=?", (body.sessionId,)).fetchone()
            if not exists:
                if body.answer: raise HTTPException(409, 'Start the conversation before answering')
                new_session(db, owner, body.sessionId, 'whatsapp')
            return do_turn(db, owner, body.model_dump())

    @app.post('/bundles/recommend')
    def recommend(profileId: str, owner=Depends(customer)):
        with database.connect() as db:
            require_consent(db, owner, 'advice')
            value = get(db, 'profile', profileId, owner)
            return catalogue.recommend(value['facts'])

    def save_quote(db, owner, body):
        require_consent(db, owner, 'advice')
        profile = get(db, 'profile', body.profileId, owner)
        quote = catalogue.price([x.model_dump() for x in body.items], profile['facts'])
        quote.update(id=uid('QUO'), profileId=body.profileId, profileHash=fingerprint(profile['facts']), createdAt=now(), expiresAt=(datetime.now(timezone.utc)+timedelta(hours=POLICY['quote_valid_hours'])).isoformat(), signed=False)
        quote['expectedActivationDate'] = (reference_date+timedelta(days=quote['installDays'])).isoformat()
        put(db, 'quote', quote['id'], owner, quote); log(db, owner, 'quote.created'); return quote

    @app.post('/quotes')
    @app.post('/bundles/reprice')
    def quote(body: QuoteInput, owner=Depends(customer)):
        with database.connect() as db: return save_quote(db, owner, body)

    @app.get('/quotes/{id}')
    def read_quote(id: str, owner=Depends(customer)):
        with database.connect() as db: return get(db, 'quote', id, owner)

    @app.post('/quotes/{id}/reprice')
    def reprice(id: str, body: QuoteInput, owner=Depends(customer)):
        with database.connect() as db:
            previous = get(db, 'quote', id, owner)
            if previous['profileId'] != body.profileId: raise HTTPException(409, 'Cannot reprice a different business profile')
            return save_quote(db, owner, body)

    @app.post('/quotes/{id}/sign')
    def sign(id: str, body: Sign, owner=Depends(customer)):
        if not body.accepted: raise HTTPException(422, 'Accept the quote to continue')
        with database.connect() as db:
            quote = get(db, 'quote', id, owner)
            if datetime.fromisoformat(quote['expiresAt']) < datetime.now(timezone.utc): raise HTTPException(409, 'Quote expired')
            quote.update(signed=True, signedAt=now(), signatoryName=body.signatoryName, signatureMode='mock')
            put(db, 'quote', id, owner, quote); log(db, owner, 'quote.mock_signed'); return quote

    @app.post('/kyc/documents')
    async def upload(profileId: str = Form(...), kind: Literal['gst','udyam','signatory','address','authorization'] = Form(...), file: UploadFile = File(...), owner=Depends(customer)):
        with database.connect() as db:
            require_consent(db, owner, 'kyc'); get(db, 'profile', profileId, owner)
        data = await file.read(POLICY['document_max_bytes'] + 1)
        await file.close()
        value = await asyncio.to_thread(extract_document, data, kind, settings.get('TESSERACT_CMD', r'C:\Program Files\Tesseract-OCR\tesseract.exe'))
        id = uid('DOC'); value.update(id=id, profileId=profileId, uploadedAt=now())
        with database.connect() as db:
            require_consent(db, owner, 'kyc')
            (upload_dir / (id + '.image')).write_bytes(data)
            put(db, 'document', id, owner, value); log(db, owner, 'kyc.document_uploaded')
        return value

    @app.post('/kyc/documents/{id}/confirm')
    def confirm_document(id: str, body: ConfirmDocument, owner=Depends(customer)):
        with database.connect() as db:
            require_consent(db, owner, 'kyc'); value = get(db, 'document', id, owner)
            if set(body.fields) != set(value['fields']) or any(len(v) > 1000 for v in body.fields.values()): raise HTTPException(422, 'Confirm the extracted field set only')
            value.update(fields=body.fields, confirmed=True, source='customer_confirmed', confirmedAt=now())
            put(db, 'document', id, owner, value); log(db, owner, 'kyc.fields_confirmed'); return value

    @app.post('/kyc/check')
    def check_kyc(profileId: str, owner=Depends(customer)):
        with database.connect() as db:
            require_consent(db, owner, 'kyc'); profile = get(db, 'profile', profileId, owner)
            docs = listing(db, 'document', owner)
            # Latest uploaded copy of each type replaces the older one for a fix-and-retry journey.
            latest = {}
            for d in docs:
                if d['profileId'] == profileId: latest.setdefault(d['kind'], d)
            result = validate_kyc(profile['facts'], list(latest.values()), catalogue, reference_date)
            result.update(profileId=profileId, profileHash=fingerprint(profile['facts']), documentHash=fingerprint([d for d in latest.values()]), checkedAt=now())
            put(db, 'kyc', profileId, owner, result); log(db, owner, 'kyc.' + result['outcome']); return result

    @app.get('/demo/specimen-profile')
    def specimen_profile(owner=Depends(customer)):
        if not demo: raise HTTPException(404, 'Not found')
        reg = catalogue.registries['gstin']['27XUIXG0767D1ZP']
        return Profile(businessName=reg['trade_name'],contactName='Joseph Singh',segment='prof',employees=5,sites=1,city='Nagpur',cityTier=2,fibreAvailable=True,budget=5000,needs=['internet','email','security'],gstin=reg['gstin'],constitution=reg['constitution'],installationAddress=reg['principal_place_of_business']).model_dump()

    @app.post('/demo/kyc/{profileId}/specimens')
    def specimen_documents(profileId: str, owner=Depends(customer)):
        if not demo: raise HTTPException(404, 'Not found')
        with database.connect() as db:
            require_consent(db, owner, 'kyc'); get(db, 'profile', profileId, owner)
        docs = []
        for kind, suffix in [('gst','gst_certificate'),('signatory','signatory_id'),('address','address_proof')]:
            data = (ROOT / f'data/source/kyc_documents/K03_{suffix}.png').read_bytes()
            doc = extract_document(data, kind, settings.get('TESSERACT_CMD', r'C:\Program Files\Tesseract-OCR\tesseract.exe'))
            id = uid('DOC'); doc.update(id=id,profileId=profileId,uploadedAt=now())
            with database.connect() as db:
                require_consent(db, owner, 'kyc')
                (upload_dir / (id + '.image')).write_bytes(data)
                put(db,'document',id,owner,doc)
            docs.append(doc)
        return {'documents':docs, 'synthetic':True, 'requiresConfirmation':True}

    @app.post('/quotes/{id}/checkout')
    def checkout(id: str, body: Checkout, owner=Depends(customer)):
        with database.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            quote = get(db, 'quote', id, owner)
            previous = next((o for o in listing(db, 'order', owner) if o['quoteId'] == id), None)
            if previous: return {'order':previous, 'idempotent':True, 'mockPayment':True}
            used = next((o for o in listing(db, 'order', owner) if o['idempotencyKey'] == body.idempotencyKey), None)
            if used: raise HTTPException(409, 'Idempotency key belongs to another quote')
            require_consent(db, owner, 'advice'); require_consent(db, owner, 'kyc')
            profile = get(db, 'profile', quote['profileId'], owner)
            kyc = get(db, 'kyc', quote['profileId'], owner)
            latest = {}
            for d in listing(db, 'document', owner):
                if d['profileId'] == quote['profileId']: latest.setdefault(d['kind'], d)
            if kyc['outcome'] != 'pass' or kyc['documentHash'] != fingerprint(list(latest.values())): raise HTTPException(409, 'KYC must pass for the current documents')
            if not quote['signed']: raise HTTPException(409, 'Accept the mock e-sign before payment')
            if quote['signatoryName'].casefold() != latest['signatory']['fields']['signatoryName'].casefold(): raise HTTPException(409, 'Quote signatory must match the confirmed KYC signatory')
            if quote['profileHash'] != fingerprint(profile['facts']) or kyc['profileHash'] != quote['profileHash']: raise HTTPException(409, 'Business details changed; refresh quote and KYC')
            if datetime.fromisoformat(quote['expiresAt']) < datetime.now(timezone.utc): raise HTTPException(409, 'Quote expired')
            fresh = catalogue.price([{'productId':x['productId'],'quantity':x['quantity']} for x in quote['items']], profile['facts'])
            if fresh['payToday'] != quote['payToday']: raise HTTPException(409, 'Price changed; refresh quote')
            log(db, owner, 'payment.mock_' + body.paymentOutcome)
            if body.paymentOutcome == 'failure': return {'paymentStatus':'failed', 'retryAllowed':True, 'mockPayment':True}
            order_id = uid('ORD')
            facts = profile['facts']
            mobile = db.execute('SELECT mobile FROM customers WHERE id=?', (owner,)).fetchone()['mobile']
            tracker_order = {'id':order_id, 'customer':{'businessName':facts['businessName'],'contactName':facts['contactName'],'mobile':mobile,'preferredLanguage':'English'}, 'bundle':{'name':'Confirmed business bundle','monthlyPriceInr':quote['monthlyTotal'],'items':quote['items']}, 'installation':{'address':facts['installationAddress'],'expectedActivationDate':quote['expectedActivationDate']}}
            order = {'id':order_id,'quoteId':id,'profileId':quote['profileId'],'idempotencyKey':body.idempotencyKey,'monthlyTotal':quote['monthlyTotal'],'payToday':quote['payToday'],'status':'provisioning','createdAt':now(),'expectedActivationDate':quote['expectedActivationDate'],'items':quote['items']}
            put(db, 'order', order_id, owner, order)
            def queue(path, value): db.execute('INSERT INTO outbox VALUES(?,?,?,?,0,0)', (uid('OUT'), order_id, path, dumps(value)))
            queue('/v1/orders', tracker_order)
            for status in ['kyc_verified','provisioning']: queue(f'/v1/orders/{order_id}/events', {'id':uid('TEV'),'status':status})
            log(db, owner, 'order.created')
        flush_outbox()
        return {'order':order, 'mockPayment':True}

    @app.get('/orders')
    def orders(owner=Depends(customer)):
        with database.connect() as db: return {'orders':listing(db, 'order', owner)}

    @app.get('/orders/{id}/tracker')
    def tracker(id: str, owner=Depends(customer)):
        with database.connect() as db:
            order = get(db, 'order', id, owner)
            pending = db.execute('SELECT count(*) FROM outbox WHERE order_id=? AND delivered=0', (id,)).fetchone()[0]
        if pending: flush_outbox()
        with database.connect() as db: pending = db.execute('SELECT count(*) FROM outbox WHERE order_id=? AND delivered=0', (id,)).fetchone()[0]
        if pending: return {'syncStatus':'pending', 'orderId':id, 'message':'Your order is saved. Tracker synchronisation will retry.', 'expectedActivationDate':order['expectedActivationDate']}
        try:
            with httpx.Client(timeout=4) as client:
                response = client.get(tracker_url + f'/v1/orders/{id}/tracker', headers=tracker_headers)
                response.raise_for_status()
                return {'syncStatus':'synced', **response.json()}
        except (httpx.HTTPError, ValueError): raise HTTPException(503, 'Tracker temporarily unavailable; your order remains saved')

    @app.post('/internal/orders/{id}/events', dependencies=[Depends(internal)])
    def order_event(id: str, body: StatusEvent):
        transitions = {'provisioning':{'installation_scheduled','cancelled'}, 'installation_scheduled':{'activated','cancelled'}, 'activated':set(), 'cancelled':set()}
        with database.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute("SELECT owner FROM records WHERE kind='order' AND id=?", (id,)).fetchone()
            if not row: raise HTTPException(404, 'Order not found')
            order = get(db, 'order', id)
            if body.status == order['status']: return order
            if body.status not in transitions.get(order['status'],set()): raise HTTPException(409, 'Invalid order stage transition')
            order['status'] = body.status
            put(db, 'order', id, row['owner'], order)
            db.execute('INSERT INTO outbox VALUES(?,?,?,?,0,0)', (uid('OUT'), id, f'/v1/orders/{id}/events', dumps({'id':uid('TEV'),**body.model_dump()})))
        flush_outbox(); return order

    @app.post('/orders/{id}/help')
    def help_ticket(id: str, body: Ticket, owner=Depends(customer)):
        with database.connect() as db:
            get(db, 'order', id, owner); ticket = {'id':uid('TKT'),'orderId':id,'message':body.message,'status':'open','createdAt':now()}
            return put(db, 'ticket', ticket['id'], owner, ticket)

    @app.post('/internal/tracker/sync', dependencies=[Depends(internal)])
    def sync(): return {'delivered':flush_outbox()}

    @app.get('/internal/review-queue', dependencies=[Depends(internal)])
    def reviews():
        with database.connect() as db:
            return {'cases':[json.loads(r['body']) for r in db.execute("SELECT body FROM records WHERE kind='kyc'") if json.loads(r['body'])['outcome'] == 'manual_review']}

    @app.get('/internal/data-summary', dependencies=[Depends(internal)])
    def data_summary():
        return {'products':len(catalogue.products),'gstin':len(catalogue.registries['gstin']),'udyam':len(catalogue.registries['udyam']),'leads':len(catalogue.leads),'synthetic':True}

    @app.get('/internal/tracker/outbox', dependencies=[Depends(internal)])
    def outbox_status():
        with database.connect() as db: return {'jobs':[dict(row) for row in db.execute('SELECT id,order_id,path,delivered,attempts FROM outbox ORDER BY rowid DESC LIMIT 100')]}

    return app

app = create_app()
