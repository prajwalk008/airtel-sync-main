import { useRef, useState } from 'react'
import { AdvisorClient, type AdvisorTurn, type ChatMessage } from '../../shared/advisor-client'
import './AdvisorChat.css'

type Props={mobile:string;businessName:string;contactName:string;problem:string;setProblem:(v:string)=>void;budget:string;setBudget:(v:string)=>void;onHelp:()=>void}
export default function AdvisorChat({mobile,businessName,contactName,problem,setProblem,budget,setBudget,onHelp}:Props){
  const client=useRef(new AdvisorClient(import.meta.env.VITE_API_URL||'/api'))
  const [turn,setTurn]=useState<AdvisorTurn|null>(null),[messages,setMessages]=useState<ChatMessage[]>([])
  const [busy,setBusy]=useState(false),[error,setError]=useState(''),[consent,setConsent]=useState(false),[allowAI,setAllowAI]=useState(false)
  const pending=useRef<{key:string;payload:string}|null>(null)
  const feed=useRef<HTMLDivElement>(null)
  function restart(text=problem){setTurn(null);setMessages([]);setError('');pending.current=null;setProblem(text)}
  async function send(option?:{id:string;label:string}){
    if(busy)return
    const text=problem.trim()
    if(!option&&!text)return
    setBusy(true);setError('')
    try{
      let next:AdvisorTurn
      if(!turn){
        if(!consent)throw new Error('Please allow us to use your business answers before starting.')
        next=await client.current.start(mobile,{problem:text,budget:Number(budget)||0,businessName,contactName},allowAI,'web')
      }else{
        const answer=option?{type:'option' as const,optionId:option.id}:{type:'text' as const,text}
        const payload=JSON.stringify({sessionId:turn.sessionId,questionId:turn.question?.id,answer})
        if(pending.current?.payload!==payload)pending.current={key:crypto.randomUUID(),payload}
        next=await client.current.reply(turn,answer,pending.current.key)
      }
      setMessages(old=>[...old,{role:'user',text:option?.label||text},...(next.message?[{role:'assistant' as const,text:next.message}]:[]),...(next.question?[{role:'assistant' as const,text:next.question.text}]:[])])
      setTurn(next);setProblem('');pending.current=null
      requestAnimationFrame(()=>feed.current?.scrollTo({top:feed.current.scrollHeight,behavior:'smooth'}))
    }catch(e){setError(e instanceof Error?e.message:'Could not reach the advisor. Please retry.')}finally{setBusy(false)}
  }
  return <section className="wrap section inner"><span className="eyebrow red">AVAILABLE ANY TIME</span><h1>Meet your AI business partner<span className="red">.</span></h1><p className="intro">Describe a problem and monthly budget. We’ll find a relevant service from the catalogue.</p><div className="columns"><div className="panel chat"><div className="chat-title"><span className="symbol">✦</span><div><b>Accel AI business partner</b><small>Here to help you find the right fit</small></div><span className="online">● {busy?'Thinking…':'Here to help'}</span></div><div className="messages advisor-feed" ref={feed} role="log" aria-live="polite"><div className="bubble">Hi! What is your business finding difficult right now? Describe it in your own words.</div>{messages.map((m,i)=><div key={i} className={'bubble'+(m.role==='user'?' you':'')}>{m.text}</div>)}{turn?.completed&&turn.recommendation?.bundles.map(b=><article className="bubble advisor-bundle" key={b.name}><b>{b.name}</b><strong>₹{b.monthlyTotal.toLocaleString('en-IN',{minimumFractionDigits:2})}<small> / month, including GST</small></strong><ul>{b.items.map(i=><li key={i.productId}>{i.name} × {i.quantity}{i.reason&&<small className="advisor-product-reason">{i.reason}</small>}</li>)}</ul><small>{b.withinBudget?'Within your budget':'Above your budget'}</small>{b.gaps.map((g,i)=><p key={i}>{g.need}: {g.reason}</p>)}</article>)}{busy&&<div className="bubble" role="status">Thinking…</div>}</div>{turn?.question&&turn.question.options.length>0&&<div className="advisor-options">{turn.question.options.map(o=><button className="outline" key={o.id} disabled={busy} onClick={()=>void send(o)}>{o.label}</button>)}</div>}{error&&<div className="advisor-error" role="alert">{error}</div>}{turn?.completed?<div className="chat-form"><button className="primary" onClick={()=>restart('')}>Start a new conversation →</button></div>:<form className="chat-form" onSubmit={e=>{e.preventDefault();void send()}}>{!turn&&<><label>Monthly budget (₹)<input inputMode="numeric" value={budget} onChange={e=>setBudget(e.target.value.replace(/\D/g,''))} disabled={busy}/></label><label className="advisor-consent"><input type="checkbox" checked={consent} onChange={e=>setConsent(e.target.checked)} disabled={busy}/>Use my business answers to recommend suitable services.</label><label className="advisor-consent"><input type="checkbox" checked={allowAI} onChange={e=>setAllowAI(e.target.checked)} disabled={busy}/>Optional: allow AI processing of my answers.</label></>}<label>{turn?'Your answer':'Describe your business problem'}<textarea required value={problem} onChange={e=>setProblem(e.target.value)} disabled={busy} placeholder={turn?'Type your answer in your own words…':"e.g. My clinic's internet drops during online appointments..."}/></label><button className="primary" disabled={busy}>{busy?'Thinking…':turn?'Send answer →':'Find a solution ↗'}</button>{turn&&<button type="button" className="link" onClick={()=>restart('')} disabled={busy}>Start again</button>}</form>}</div><aside><div className="panel aside"><span className="symbol">✦</span><h3>Built around your needs</h3><p>Ask about connectivity, payments, reaching customers or securing your business.</p>{['My shop loses UPI payments when Wi-Fi fails','I need appointment reminders','How can I secure client files?'].map(x=><button key={x} onClick={()=>restart(x)} disabled={busy}>{x} →</button>)}</div><div className="panel aside"><h3>Prefer a human?</h3><p>Pass your question to a specialist.</p><button className="link" onClick={onHelp}>Request a callback →</button></div></aside></div></section>
}
