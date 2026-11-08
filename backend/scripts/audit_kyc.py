"""Read all supplied specimen images and print extraction/validation observations.
This is an OCR audit, not a fabricated ground-truth label file.
"""
import json
import argparse
from datetime import date
from backend.catalogue import Catalogue, ROOT
from backend.kyc import extract_document, validate_kyc

def run(output=None):
    catalogue = Catalogue(); cases = []
    for n in range(1,13):
        applicant = f'K{n:02}'
        docs = []
        for path in sorted((ROOT / 'data/source/kyc_documents').glob(applicant + '_*.png')):
            suffix = path.stem.split('_', 1)[1]
            kind = {'gst_certificate':'gst','udyam_certificate':'udyam','signatory_id':'signatory','address_proof':'address'}[suffix]
            d = extract_document(path.read_bytes(), kind, r'C:\Program Files\Tesseract-OCR\tesseract.exe')
            d['confirmed'] = True  # Audit only; customer-facing API requires explicit field confirmation.
            docs.append(d)
        registration = next((d for d in docs if d['kind']=='gst'), next((d for d in docs if d['kind']=='udyam'), {}))
        profile = {'businessName':registration.get('fields',{}).get('businessName',''), 'gstin':registration.get('fields',{}).get('gstin',''), 'installationAddress':registration.get('fields',{}).get('address','')}
        result = validate_kyc(profile, docs, catalogue, date(2026,7,15))
        cases.append({'applicant':applicant, 'profile':profile, 'documents':[{'kind':d['kind'],'fields':d['fields'],'quality':d['quality'],'ocrStatus':d['ocrStatus']} for d in docs], 'result':result})
    report = {'note':'Raw local OCR regression observations; no labelled ground truth was supplied. Confirmation is simulated for this audit only.', 'referenceDate':'2026-07-15', 'cases':cases}
    if output:
        from pathlib import Path
        path = Path(output); path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, indent=2, ensure_ascii=True), encoding='utf-8')
        print(json.dumps({c['applicant']:c['result']['outcome'] for c in cases}, indent=2))
    else: print(json.dumps(report, indent=2, ensure_ascii=True))

if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('--output'); run(parser.parse_args().output)
