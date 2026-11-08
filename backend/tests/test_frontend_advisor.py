import json
from uuid import uuid4
import httpx
from backend.tests.test_backend import client, login, consent

def test_original_frontend_context_drives_pipeline(client):
    login(client); consent(client); consent(client,'ai',False)
    start = client.post('/sessions',json={'channel':'web','context':{'problem':'My shop loses UPI payments when Wi-Fi fails','budget':2500,'businessName':'Test shop','contactName':'Test owner'}})
    assert start.status_code == 200, start.text
    result = start.json(); sid = result['sessionId']
    assert result['question']['id'] == 'segment'
    answers = {'segment':'micro','employees':'3','sites':'1','city':'Nagpur','cityTier':'2','fibreAvailable':'yes','needs':'internet','gstin':'none','tools':'Mobile hotspot'}
    for _ in range(30):
        if result['completed']: break
        q = result['question']; value = 'yes' if q['id']=='confirm' else answers[q['id']]
        if q['id']=='needs': assert 'UPI payments' in q['text']
        option = next((o for o in q['options'] if o['id']==value),None)
        answer = {'type':'option','optionId':value} if option else {'type':'text','text':value}
        response = client.post('/sessions/'+sid+'/turn',json={'sessionId':sid,'eventId':str(uuid4()),'questionId':q['id'],'answer':answer})
        assert response.status_code == 200, response.text
        result = response.json()
    assert result['completed']
    assert result['recommendation']['bundles'][0]['monthlyTotal'] == 1178.82
    assert result['recommendation']['bundles'][0]['items'][0]['reason']
    session = client.get('/sessions/'+sid).json()
    assert session['profile']['budget'] == 2500
    assert session['context']['problem'].startswith('My shop')
    assert session['sources']['budget']['source'] == 'customer_form'

def test_android_starts_same_pipeline_and_context_needs_consent(client):
    login(client)
    body = {'channel':'android','context':{'problem':'Secure client files','budget':3000}}
    assert client.post('/sessions',json=body).status_code == 403
    consent(client)
    result = client.post('/sessions',json=body)
    assert result.status_code == 200
    assert result.json()['question']['id'] == 'businessName'

def test_llm_explanations_cannot_invent_product_or_price(monkeypatch):
    import backend.ai as module
    ai = module.AI({'OPENAI_API_KEY':'test-key','OPENAI_MODEL':'configured-model'})
    original = httpx.Client
    def response(request):
        body = json.loads(request.content)
        assert body['text']['format']['schema']['properties']['reasons']['items']['properties']['productId']['enum'] == ['P01','P20']
        return httpx.Response(200,json={'output':[{'content':[{'type':'output_text','text':json.dumps({'reasons':[{'productId':'P01','reason':'Protect your shop with guaranteed free broadband for Rs 1.'},{'productId':'P20','reason':'Helps protect the devices used to store your client files.'},{'productId':'UNKNOWN','reason':'Buy another invented product.'}]})}]}]})
    monkeypatch.setattr(module.httpx,'Client',lambda **kw:original(transport=httpx.MockTransport(response),**kw))
    result = ai.explain_products({'needs':['security']},[{'productId':'P01'},{'productId':'P20'}])
    assert set(result) == {'P20'}
