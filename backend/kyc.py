import io
import re
import subprocess
from datetime import date
from difflib import SequenceMatcher
from pathlib import Path
from PIL import Image, ImageFilter, ImageStat, UnidentifiedImageError
from fastapi import HTTPException
from .catalogue import POLICY

def clean(value): return re.sub(r'[^a-z0-9]', '', value.lower())
def similar(a, b): return bool(a and b) and SequenceMatcher(None, clean(a), clean(b)).ratio() >= 0.85

def gst_format(value):
    if not re.fullmatch(r'\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z]', value): return False
    chars = '0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ'; factor = 2; total = 0
    for c in reversed(value[:-1]):
        digit = factor * chars.index(c); total += digit // 36 + digit % 36; factor = 1 if factor == 2 else 2
    return chars[(36 - total % 36) % 36] == value[-1]

def fields_from_text(text, kind):
    def capture(pattern):
        match = re.search(pattern, text, re.I | re.S)
        return re.sub(r'\s+', ' ', match.group(1)).strip(' :') if match else ''
    fields = {}
    if kind == 'gst':
        fields = {'gstin':capture(r'GSTIN\s+([A-Z0-9]{15})'), 'legalName':capture(r'Legal name\s+(.*?)\s+Trade name'), 'businessName':capture(r'Trade name\s+(.*?)\s+Constitution'), 'constitution':capture(r'Constitution\s+(.*?)\s+Address of principal'), 'address':capture(r'Address of principal\s+(.*?)\s+Date of liability')}
        fields['address'] = fields['address'].replace('place of business', '')
    elif kind == 'udyam':
        fields = {'udyam':capture(r'(UDYAM-[A-Z]{2}-\d{2}-\d{7})'), 'businessName':capture(r'Enterprise name\s+(.*?)\s+Major activity')}
    elif kind == 'signatory':
        fields = {'signatoryName':capture(r'\bName\s+(.*?)\s+Designation'), 'designation':capture(r'Designation\s+(.*?)\s+For business'), 'businessName':capture(r'For business\s+(.*?)\s+ID no'), 'idNumber':capture(r'(SYN-ID-\d+)'), 'validTill':capture(r'Valid till\s+(\d{4}-\d{2}-\d{2})')}
    elif kind == 'address':
        fields = {'businessName':capture(r'Billed to\s+(.*?)\s+Supply address'), 'address':capture(r'Supply address\s+(.*?)\s+Bill date'), 'billDate':capture(r'Bill date\s+(\d{4}-\d{2}-\d{2})')}
    elif kind == 'authorization':
        fields = {'signatoryName':capture(r'Signatory name\s*:?\s*(.*?)\n'), 'businessName':capture(r'Business name\s*:?\s*(.*?)\n')}
    return fields

def extract_document(data, kind, tesseract):
    if not data or len(data) > POLICY['document_max_bytes']: raise HTTPException(413, 'Document must be 1 byte to 6 MB')
    try:
        image = Image.open(io.BytesIO(data))
        if image.format not in {'PNG','JPEG'} or image.width * image.height > 20_000_000: raise HTTPException(422, 'Upload a PNG/JPEG of at most 20 megapixels')
        image.load()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as e: raise HTTPException(422, 'Invalid image') from e
    gray = image.convert('L')
    edge_strength = ImageStat.Stat(gray.filter(ImageFilter.FIND_EDGES)).stddev[0]
    quality = {'width':image.width, 'height':image.height, 'edgeStrength':round(edge_strength, 2), 'warnings':[]}
    if min(image.size) < 400 or edge_strength < 8: quality['warnings'].append('Image may be too small or blurred; upload a clearer copy')
    # Normalize metadata away and pass bytes via stdin; filenames never become shell commands.
    normalized = io.BytesIO(); image.save(normalized, format='PNG')
    text = ''; status = 'unavailable'
    if tesseract and Path(tesseract).is_file():
        try:
            r = subprocess.run([tesseract, 'stdin', 'stdout', '--psm', '6'], input=normalized.getvalue(), capture_output=True, timeout=20, check=True)
            text = r.stdout.decode('utf-8', errors='replace'); status = 'extracted' if text.strip() else 'empty'
        except (subprocess.SubprocessError, OSError): status = 'failed'
    fields = fields_from_text(text, kind)
    return {'kind':kind, 'fields':fields, 'quality':quality, 'ocrStatus':status, 'confirmed':False, 'source':'ocr', 'text':text}

def validate_kyc(profile, docs, catalogue, reference_date):
    fixes = []; review = []
    by_kind = {d['kind']:d for d in docs}
    registration = by_kind.get('gst') or by_kind.get('udyam')
    if not registration: fixes.append('Upload a GST or Udyam registration document')
    for kind in ['signatory','address']:
        if kind not in by_kind: fixes.append(f'Upload {kind} document')
    for d in docs:
        if not d['confirmed']: fixes.append(f"Confirm extracted {d['kind']} fields")
        if d['quality']['warnings']: fixes.extend(d['quality']['warnings'])
        if d['ocrStatus'] != 'extracted': review.append(f"OCR {d['ocrStatus']} for {d['kind']}; human document review required")
    gst_doc = by_kind.get('gst')
    registry = None
    if gst_doc:
        gstin = gst_doc['fields'].get('gstin', '').upper()
        registry = catalogue.registries['gstin'].get(gstin)
        if not gst_format(gstin): fixes.append('GSTIN format or checksum is invalid')
        if not registry: review.append('GSTIN not found in mock registry')
        elif registry['status'].lower() != 'active': fixes.append('GST registration is not active')
        if profile.get('gstin') and gstin != profile['gstin']: fixes.append('Document GSTIN differs from profile')
        if registry:
            if not similar(gst_doc['fields'].get('businessName',''), registry['trade_name']): review.append('GST trade name differs from registry')
            if not similar(gst_doc['fields'].get('legalName',''), registry['legal_name']): review.append('GST legal name differs from registry')
            if not similar(gst_doc['fields'].get('address',''), registry['principal_place_of_business']): review.append('GST address differs from registry')
    udyam_doc = by_kind.get('udyam')
    if udyam_doc:
        number = udyam_doc['fields'].get('udyam', '').upper()
        udyam = catalogue.registries['udyam'].get(number)
        if not re.fullmatch(r'UDYAM-[A-Z]{2}-\d{2}-\d{7}', number): fixes.append('Udyam format is invalid')
        if not udyam: review.append('Udyam not found in mock registry')
        elif not similar(udyam_doc['fields'].get('businessName',''), udyam['enterprise_name']): review.append('Udyam enterprise name differs from registry')
    name = profile.get('businessName','')
    for d in docs:
        if not similar(name, d['fields'].get('businessName','')): review.append(f"Business name mismatch or missing on {d['kind']} document")
    address = by_kind.get('address', {}).get('fields', {})
    if address:
        try:
            age = (reference_date - date.fromisoformat(address.get('billDate',''))).days
            if age < 0 or age > POLICY['address_proof_max_days']: fixes.append('Address proof must be dated within the previous 90 days')
        except ValueError: fixes.append('Confirm a valid address-proof date')
        expected_address = profile.get('installationAddress') or (registry or {}).get('principal_place_of_business','')
        if not similar(address.get('address',''), expected_address): review.append('Address proof does not match installation address')
    signatory = by_kind.get('signatory', {}).get('fields', {})
    if signatory:
        if not signatory.get('signatoryName') or not signatory.get('idNumber'): fixes.append('Signatory name and ID are required')
        if profile.get('contactName') and not similar(signatory.get('signatoryName',''), profile['contactName']): review.append('Signatory name differs from declared contact')
        try:
            if date.fromisoformat(signatory.get('validTill','')) < reference_date: fixes.append('Signatory ID has expired')
        except ValueError: fixes.append('Confirm signatory ID expiry date')
    constitution = (registry or {}).get('constitution', profile.get('constitution',''))
    non_proprietor = 'propriet' not in constitution.lower()
    if not constitution: review.append('Business constitution requires review')
    if non_proprietor or signatory.get('designation','').lower() not in {'owner','proprietor','partner','director'}:
        auth = by_kind.get('authorization')
        if not auth: review.append('Authorisation letter required for this signatory')
        elif not similar(auth['fields'].get('signatoryName',''), signatory.get('signatoryName','')): review.append('Authorisation letter signatory mismatch')
    return {'outcome':'customer_to_fix' if fixes else 'manual_review' if review else 'pass', 'reasons':list(dict.fromkeys(fixes + review)), 'referenceDate':reference_date.isoformat(), 'registryMode':'synthetic', 'checksAreMock':True}
