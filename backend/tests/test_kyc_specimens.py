from datetime import date
from pathlib import Path
import pytest
from backend.catalogue import Catalogue, ROOT
from backend.kyc import extract_document, validate_kyc

TESSERACT = r'C:\Program Files\Tesseract-OCR\tesseract.exe'

@pytest.mark.skipif(not Path(TESSERACT).is_file(), reason='Install/configure Tesseract for real specimen OCR tests')
def test_all_47_specimen_images_and_12_applicants():
    catalogue = Catalogue(); outcomes = {}; count = 0
    for n in range(1,13):
        applicant = f'K{n:02}'; docs = []
        for path in sorted((ROOT/'data/source/kyc_documents').glob(applicant+'_*.png')):
            kind = {'gst_certificate':'gst','udyam_certificate':'udyam','address_proof':'address','signatory_id':'signatory'}[path.stem.split('_',1)[1]]
            doc = extract_document(path.read_bytes(),kind,TESSERACT); count += 1
            assert doc['ocrStatus'] == 'extracted', path.name
            doc['confirmed'] = True  # Isolate validator observations; UI confirmation is tested separately.
            docs.append(doc)
        gst = next(d for d in docs if d['kind']=='gst')['fields']
        profile = {'businessName':gst.get('businessName',''),'gstin':gst.get('gstin',''),'installationAddress':gst.get('address','')}
        result = validate_kyc(profile,docs,catalogue,date(2026,7,15)); outcomes[applicant] = result['outcome']
        assert result['outcome'] in {'pass','customer_to_fix','manual_review'}
        assert bool(result['reasons']) == (result['outcome'] != 'pass')
    assert count == 47
    # Regression for this local OCR pipeline, not a claim of supplied ground-truth labels.
    assert {id for id,outcome in outcomes.items() if outcome == 'pass'} == {'K03','K12'}
