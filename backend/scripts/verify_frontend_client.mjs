import assert from 'node:assert/strict';
import { randomInt } from 'node:crypto';
import { AdvisorClient } from '../../shared/advisor-client.ts';

const values={segment:'micro',employees:'3',sites:'1',city:'Nagpur',cityTier:'2',fibreAvailable:'yes',needs:'internet',gstin:'none',tools:'Mobile hotspot'};
for(const [channel,base] of [['web',process.env.WEB_API_URL||'http://127.0.0.1:5174/api'],['android','http://127.0.0.1:8000']]){
  const client=new AdvisorClient(base);
  let turn=await client.start('9'+String(randomInt(100000000,999999999)),{problem:'My shop loses UPI payments when Wi-Fi fails',budget:2500,businessName:'Frontend integration shop',contactName:'Test owner'},false,channel);
  assert.equal(turn.question.id,'segment');
  for(let step=0;!turn.completed&&step<35;step++){
    const q=turn.question;
    assert.notEqual(q.id,'budget','The budget from the existing chat form must be retained');
    if(q.id==='needs')assert.match(q.text,/UPI payments/);
    const value=q.id==='confirm'?'yes':values[q.id];
    assert.ok(value,'Unexpected question: '+q.id);
    const option=q.options.find(o=>o.id===value);
    turn=await client.reply(turn,option?{type:'option',optionId:option.id}:{type:'text',text:value},`${turn.sessionId}-smoke-${step}`);
  }
  assert.equal(turn.completed,true);
  assert.equal(turn.recommendation.bundles[0].monthlyTotal,1178.82);
  assert.equal(turn.recommendation.bundles[0].items[0].productId,'P01');
  console.log(`PASS ${channel}: actual shared frontend client -> ${base} -> advisor -> confirmed answers -> catalogue recommendation`);
}
