"""Local HTTP smoke test: WhatsApp adapter -> actual shared advisor -> recommendation.
No Meta, LLM or payment-provider requests are made.
"""
from uuid import uuid4
import httpx

def run():
    customer = 'demo-' + str(uuid4())
    values = {'adviceConsent':'yes','aiConsent':'no','businessName':'Stack test shop','segment':'micro','employees':'3','sites':'1','city':'Nagpur 411231','cityTier':'2','fibreAvailable':'yes','needs':'internet','budget':'3000','gstin':'none','tools':'Mobile hotspot'}
    with httpx.Client(timeout=50) as client:
        def send(answer):
            response = client.post('http://127.0.0.1:3002/demo/turn',json={'customerId':customer,'input':answer})
            response.raise_for_status(); return response.json()['session']
        session = send({'type':'text','text':'/start'})
        for _ in range(40):
            turn = session['turn']
            if turn['completed']:
                assert 'Rs ' in turn['message']
                print('PASS: WhatsApp HTTP adapter -> shared advisor -> confirmed answers -> catalogue recommendation')
                print(turn['message'])
                return
            question = turn['question']; value = 'yes' if question['id']=='confirm' else values[question['id']]
            option = next((o for o in question['options'] if o['id']==value),None)
            answer = {'type':'option','optionId':f"{session['sessionId']}:{session['revision']}:{question['id']}:{value}"} if option else {'type':'text','text':value}
            session = send(answer)
    raise AssertionError('Questionnaire did not complete')

if __name__ == '__main__': run()
