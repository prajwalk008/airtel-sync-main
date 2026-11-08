from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, StrictInt

class Model(BaseModel):
    model_config = ConfigDict(extra='forbid')

class Profile(Model):
    businessName: str = Field(min_length=2, max_length=200)
    contactName: str = Field(default='Business owner', min_length=2, max_length=100)
    segment: Literal['micro','prof','multi','mfg'] = 'micro'
    employees: int = Field(default=1, ge=1, le=1000)
    sites: int = Field(default=1, ge=1, le=1000)
    city: str = Field(default='', max_length=200)
    cityTier: Literal[1,2] | None = None
    fibreAvailable: bool = False
    budget: int = Field(default=0, ge=0, le=10000000)
    needs: list[Literal['internet','backup','email','security','storage','messaging','sms','pos','cctv','website','sim','static_ip']] = Field(default_factory=list, max_length=12)
    gstin: str = Field(default='', max_length=15)
    udyam: str = Field(default='', max_length=25)
    constitution: str = Field(default='', max_length=100)
    installationAddress: str = Field(default='', max_length=500)
    tools: str = Field(default='', max_length=200)

class Item(Model):
    productId: str = Field(pattern=r'^P\d{2}$')
    quantity: StrictInt = Field(ge=1, le=1000)

class QuoteInput(Model):
    profileId: str
    items: list[Item] = Field(min_length=1, max_length=25)

class Consent(Model):
    scope: Literal['advice','kyc','ai']
    accepted: bool

class AdvisorContext(Model):
    problem: str = Field(min_length=1, max_length=4000)
    budget: int = Field(ge=0, le=10000000)
    businessName: str = Field(default='', max_length=200)
    contactName: str = Field(default='', max_length=100)

class SessionInput(Model):
    language: Literal['English','Hindi','Hinglish'] = 'English'
    channel: Literal['web','android'] = 'web'
    context: AdvisorContext | None = None

class Answer(Model):
    type: Literal['text','option','audio']
    text: str = Field(default='', max_length=4000)
    optionId: str | None = Field(default=None, max_length=64)
    audio: dict | None = None

class Turn(Model):
    eventId: str = Field(min_length=1, max_length=200)
    sessionId: str = Field(min_length=1, max_length=100)
    customerId: str | None = Field(default=None, max_length=100)
    channel: Literal['whatsapp','web','android'] = 'web'
    questionId: str | None = Field(default=None, max_length=64)
    answer: Answer | None = None
    history: list = Field(default_factory=list, max_length=100)
    initialMessage: str | None = Field(default=None, max_length=4000)
