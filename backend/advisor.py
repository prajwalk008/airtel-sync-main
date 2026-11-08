import hashlib
import json
from fastapi import HTTPException
from .ai import parse_answer
from .catalogue import POLICY
from .db import get, put, dumps, log, listing, now, uid

def q(id, text, options=()):
    return {'id': id, 'text': text, 'options': [{'id': a, 'label': b} for a, b in options]}

QUESTIONS = [
    q('adviceConsent', 'May we store your business answers to recommend suitable services?', [('yes','Agree'),('no','Decline')]),
    q('aiConsent', 'May we send your answers and voice recordings to the configured AI provider for interpretation? Optional: choose No to use local text and options.', [('yes','Allow AI'),('no','Local text only')]),
    q('businessName', 'What is your business called?'),
    q('segment', 'What kind of business do you run?', [('prof','Professional office'),('micro','Shop or service'),('mfg','Manufacturer'),('multi','Multiple locations')]),
    q('employees', 'How many people work in your business? Please give a number.'),
    q('sites', 'How many locations do you need services for?', [('1','One location'),('2','Two locations'),('3','Three locations')]),
    q('city', 'Which city and postcode is your business in?'),
    q('cityTier', 'Which city tier should we use for this demo? This will need address verification before a real purchase.', [('1','Tier 1'),('2','Tier 2')]),
    q('fibreAvailable', 'Has fibre availability been confirmed at your premises?', [('yes','Yes'),('no','No / not sure')]),
    q('needs', 'What problem should we solve? Describe your needs or choose an option.', [('internet','Reliable internet'),('security','Protect my business'),('messaging','Reach customers')]),
    q('budget', 'What is your monthly budget in rupees, including GST?'),
    q('gstin', 'Enter your GSTIN, or choose no GSTIN. We use the supplied mock registry.', [('none','No GSTIN')]),
    q('tools', 'What internet connection and digital tools do you use today?')
]
HI = {
    'businessName':'आपके व्यवसाय का नाम क्या है?', 'segment':'आपका व्यवसाय किस प्रकार का है?',
    'employees':'आपके व्यवसाय में कितने लोग काम करते हैं? संख्या बताएं।', 'sites':'कितनी जगहों के लिए सेवाएं चाहिए?',
    'city':'आपका व्यवसाय किस शहर और पिनकोड में है?', 'cityTier':'इस डेमो के लिए शहर का टियर चुनें।',
    'fibreAvailable':'क्या आपके पते पर फाइबर उपलब्ध होने की पुष्टि हुई है?', 'needs':'आप कौन सी समस्या हल करना चाहते हैं?',
    'budget':'GST सहित आपका मासिक बजट कितने रुपये है?', 'gstin':'GSTIN लिखें या No GSTIN चुनें। हम मॉक रजिस्ट्री उपयोग करते हैं।',
    'tools':'अभी आप कौन सा इंटरनेट और डिजिटल टूल उपयोग करते हैं?'
}
HINGLISH = {
    'businessName':'Aapke business ka naam kya hai?', 'segment':'Aap kis tarah ka business chalate hain?',
    'employees':'Aapke business mein kitne log kaam karte hain? Number batayein.', 'sites':'Kitni locations ke liye services chahiye?',
    'city':'Aapka business kis city aur PIN code mein hai?', 'cityTier':'Is demo ke liye apni city ka tier chunein.',
    'fibreAvailable':'Kya aapke address par fibre availability confirm hui hai?', 'needs':'Aap apne business ki kaunsi problem solve karna chahte hain?',
    'budget':'GST mila kar aapka monthly budget kitne rupees hai?', 'gstin':'GSTIN likhein ya No GSTIN chunein. Hum mock registry use karte hain.',
    'tools':'Abhi aap kaunsa internet aur digital tools use karte hain?'
}

class Advisor:
    def __init__(self, catalogue, ai): self.catalogue, self.ai = catalogue, ai

    def render(self, session, message=None):
        if session.get('stopped'): return {'completed':True, 'message':'No problem. We have stopped collecting business details. You can restart whenever you choose.'}
        if not session.get('pending'):
            while session['index'] < len(QUESTIONS) and QUESTIONS[session['index']]['id'] in session['profile']:
                session['index'] += 1
        if session.get('pending'):
            pending = session['pending']
            question = q('confirm', 'Please confirm: ' + pending['display'][:500], [('yes','Confirm'),('no','Change answer')])
        elif session['index'] < len(QUESTIONS):
            question = dict(QUESTIONS[session['index']])
            translations = HI if session.get('language') == 'Hindi' else HINGLISH if session.get('language') == 'Hinglish' else {}
            question['text'] = translations.get(question['id'], question['text'])
            if question['id']=='needs' and session.get('context',{}).get('problem'):
                question['text'] = 'You mentioned: “' + session['context']['problem'][:400] + '”. What would you most like to improve? You can confirm that problem or describe more.'
        else:
            result = self.catalogue.recommend(session['profile'])
            reasons = {}
            if session.get('allowAI'):
                approved = {item['productId']:{'productId':item['productId'],'name':item['name'],'description':self.catalogue.products[item['productId']]['description']} for b in result['bundles'] for item in b['items']}
                # Identifiers and document details are not needed to explain a recommendation.
                public_context = {k:v for k,v in session['profile'].items() if k in {'segment','employees','sites','needs','tools'}}
                public_context['problem'] = session.get('context',{}).get('problem','')
                reasons = self.ai.explain_products(public_context,list(approved.values()))
            for bundle in result['bundles']:
                for item in bundle['items']:
                    need = next((need for need,pid in POLICY['need_products'].items() if pid==item['productId']),None)
                    item['reason'] = reasons.get(item['productId']) or (f'Addresses your {need.replace("_"," ")} needs.' if need else 'Supports the selected business services.')
            session['recommendation'] = result
            if result['bundles']:
                b = result['bundles'][0]
                names = ', '.join(x['name'] for x in b['items'])
                message = f"Recommended: {names}. Monthly total including GST: Rs {b['monthlyTotal']:.2f}. "
                message += f"This is Rs {result['budgetGap']:.2f} above your budget. " if result['budgetGap'] else 'This fits your stated budget. '
                message += 'Review the quote and serviceability before purchasing.'
            else: message = 'No eligible bundle matches the confirmed details. A specialist should review the uncovered needs.'
            return {'completed': True, 'message': message, 'sessionId': session['id'], 'recommendation': result, 'aiMode': 'configured' if self.ai.key and self.ai.model else 'deterministic'}
        return {'completed': False, 'question': question, 'sessionId': session['id'], **({'message':message} if message else {})}

    def turn(self, db, owner, request):
        sid, eid = request['sessionId'], request['eventId']
        fingerprint = hashlib.sha256(dumps({k: v for k, v in request.items() if k != 'history'}).encode()).hexdigest()
        cached = db.execute('SELECT * FROM turns WHERE event_id=?', (eid,)).fetchone()
        if cached:
            if cached['session_id'] != sid or cached['request_hash'] != fingerprint: raise HTTPException(409, 'Event ID reused with different input')
            get(db, 'session', sid, owner)
            return json.loads(cached['response'])
        session = get(db, 'session', sid, owner)
        previous_profile = dict(session['profile'])
        consents = listing(db, 'consent', owner)
        ai_consent = next((c['accepted'] for c in consents if c['scope'] == 'ai'), False)
        session['allowAI'] = ai_consent
        answer = request.get('answer')
        if answer and session.get('stopped'): raise HTTPException(409, 'Consent declined; start a new session to continue')
        message = None
        if answer and session['index'] >= len(QUESTIONS): raise HTTPException(409, 'Advisor session completed')
        if answer:
            expected = 'confirm' if session.get('pending') else QUESTIONS[session['index']]['id']
            if request.get('questionId') != expected: raise HTTPException(409, 'Answer the current question')
            text = answer.get('text', '')
            voice = answer.get('type') == 'audio'
            if voice:
                try:
                    if not ai_consent: raise ValueError('Please allow AI processing before sending voice notes, or use text/options.')
                    text = self.ai.transcribe(answer.get('audio', {}))
                except ValueError as e: message = str(e)
            if not message:
                if expected == 'confirm':
                    choice = answer.get('optionId') if answer.get('type') == 'option' else text.lower().strip()
                    if choice in {'yes','confirm','हाँ','haan'}:
                        self.apply(session, session['pending']['field'], session['pending']['value'], session['pending']['source'])
                        session.pop('pending'); session['index'] += 1
                    elif choice in {'no','change','नहीं','nahi'}: session.pop('pending')
                    else: message = 'Please confirm or choose Change answer.'
                else:
                    question = QUESTIONS[session['index']]
                    if answer.get('type') == 'option':
                        selected = next((o for o in question['options'] if o['id'] == answer.get('optionId')), None)
                        if not selected: raise HTTPException(422, 'Invalid option for question')
                        text = selected['id']
                    value = None
                    source = 'voice' if voice else 'text' if answer.get('type') == 'text' else 'option'
                    if ai_consent and source != 'option' and expected not in {'businessName','city','gstin','adviceConsent','aiConsent'}:
                        inferred = self.ai.interpret(expected, text, question['options'])
                        value = parse_answer(expected, inferred, question['options']) if isinstance(inferred, str) else None
                        if value is not None: source = 'ai_interpreted'
                    if value is None: value = parse_answer(expected, text, question['options'])
                    if value is None: message = 'I could not confidently understand that answer. Please rephrase or choose an option.'
                    elif source != 'option': session['pending'] = {'field':expected,'value':value,'display':f'{expected} = {value}', 'source':source}
                    else: self.apply(session, expected, value, source); session['index'] += 1
        for field, scope in [('adviceConsent','advice'), ('aiConsent','ai')]:
            if field in session['profile'] and (field not in previous_profile or previous_profile[field] != session['profile'][field]):
                previous = next((c for c in consents if c['scope'] == scope), None)
                accepted = session['profile'][field]
                if not previous or previous['accepted'] != accepted:
                    consent = {'id':uid('CON'), 'scope':scope,'accepted':accepted,'version':'2026-01','at':now()}
                    put(db, 'consent', consent['id'], owner, consent)
        result = self.render(session, message)
        put(db, 'session', sid, owner, session)
        db.execute('INSERT INTO turns VALUES(?,?,?,?)', (eid, sid, fingerprint, dumps(result)))
        log(db, owner, 'advisor.turn', session['channel'])
        return result

    @staticmethod
    def apply(session, field, value, source):
        if field in {'adviceConsent','aiConsent'}: value = value == 'yes'
        if field == 'adviceConsent' and not value: session['stopped'] = True
        if field in {'employees','sites','budget'}: value = int(value)
        if field == 'cityTier': value = int(value)
        if field == 'fibreAvailable': value = value == 'yes'
        if field == 'needs' and isinstance(value, str): value = [value]
        session['profile'][field] = value
        session['sources'][field] = {'source':source, 'confirmed':True}
