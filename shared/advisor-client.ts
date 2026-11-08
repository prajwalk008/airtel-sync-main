export type AdvisorQuestion = { id:string; text:string; options:{id:string;label:string}[] }
export type AdvisorLine = { productId:string; name:string; quantity:number; monthlyExTax:number; reason?:string }
export type AdvisorBundle = { name:string; monthlyTotal:number; withinBudget:boolean; items:AdvisorLine[]; gaps:{need:string;reason:string}[] }
export type AdvisorTurn = { sessionId:string; completed:boolean; question?:AdvisorQuestion; message?:string; recommendation?:{bundles:AdvisorBundle[];budgetGap?:number}; aiMode?:string }
export type ChatMessage = { role:'assistant'|'user'; text:string }
export type AdvisorContext = { problem:string; budget:number; businessName?:string; contactName?:string }

// No UI or platform imports: the website and native app use the same API contract.
export class AdvisorClient {
  private token=''
  private customer=''
  private expires=0
  private base:string
  constructor(base:string) { this.base=base.replace(/\/$/,'') }
  private async request<T>(path:string, body:unknown):Promise<T> {
    const controller=new AbortController()
    const timeout=setTimeout(()=>controller.abort(),60000)
    try {
      const response=await fetch(this.base+path,{method:'POST',headers:{'Content-Type':'application/json',...(this.token?{Authorization:'Bearer '+this.token}:{})},body:JSON.stringify(body),signal:controller.signal})
      const value=await response.json()
      if(!response.ok){if(response.status===401)this.token='';throw new Error(typeof value.detail==='string'?value.detail:'The advisor could not process that answer. Please try again.')}
      return value as T
    } catch(error) {
      if(error instanceof Error && error.name==='AbortError')throw new Error('The advisor took too long to reply. Please retry.')
      if(error instanceof TypeError)throw new Error('Cannot reach the advisor. Check that the shared backend is running and the API address is correct.')
      throw error
    } finally {clearTimeout(timeout)}
  }
  async start(mobile:string,context:AdvisorContext,allowAI:boolean,channel:'web'|'android'):Promise<AdvisorTurn> {
    if(!this.token||this.customer!==mobile||Date.now()>this.expires){
      // Existing local demo sign-in is retained. A non-demo server never exposes this code.
      const otp=await this.request<{demoCode?:string}>('/auth/request-otp',{mobile})
      if(!otp.demoCode)throw new Error('Please verify your phone before starting the advisor.')
      const auth=await this.request<{token:string;expiresInSeconds:number}>('/auth/verify-otp',{mobile,code:otp.demoCode})
      this.token=auth.token;this.customer=mobile;this.expires=Date.now()+auth.expiresInSeconds*1000
    }
    await this.request('/consents',{scope:'advice',accepted:true})
    await this.request('/consents',{scope:'ai',accepted:allowAI})
    return this.request<AdvisorTurn>('/sessions',{channel,context})
  }
  reply(turn:AdvisorTurn,answer:{type:'text';text:string}|{type:'option';optionId:string},eventId:string):Promise<AdvisorTurn> {
    if(!turn.question)return Promise.reject(new Error('This conversation has finished. Start a new conversation to continue.'))
    return this.request<AdvisorTurn>('/sessions/'+encodeURIComponent(turn.sessionId)+'/turn',{sessionId:turn.sessionId,eventId,questionId:turn.question.id,answer})
  }
}
