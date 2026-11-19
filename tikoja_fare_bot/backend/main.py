"""Tikoja Flight Fare Intelligence API.
Live TripJack mapping is deliberately gated on Tikoja's account-specific API contract.
"""
from __future__ import annotations
import os, json, sqlite3, uuid, hmac, hashlib, re
from datetime import datetime, timezone, date
from typing import Any, Optional
import httpx
from dotenv import load_dotenv
load_dotenv()
from fastapi import FastAPI, HTTPException, Header, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

DB_PATH=os.getenv('DATABASE_PATH','tikoja_fares.db')
app=FastAPI(title='Tikoja Flight Fare Intelligence',version='1.0.0')
origins=[x.strip() for x in os.getenv('CORS_ORIGINS','*').split(',') if x.strip()]
app.add_middleware(CORSMiddleware,allow_origins=origins,allow_credentials=False,allow_methods=['*'],allow_headers=['*'])

class EstimateRequest(BaseModel):
    origin:str=Field(min_length=3,max_length=10); destination:str=Field(min_length=3,max_length=10)
    departure_date:date; current_fare:float=Field(gt=0); current_fare_seats:int=Field(ge=1)
    next_seats:int=Field(ge=1); currency:str='INR'; assumed_uplift_pct:float=Field(default=15,ge=0,le=200)
    airline:Optional[str]=None; cabin:str='ECONOMY'
class Observation(BaseModel):
    origin:str; destination:str; departure_date:date; airline:Optional[str]=None; flight_number:Optional[str]=None
    fare_basis:Optional[str]=None; booking_class:Optional[str]=None; price:float=Field(gt=0); currency:str='INR'
    seats_at_price:Optional[int]=Field(default=None,ge=1); source:str='tripjack'
class RawSupplierPayload(BaseModel): payload:dict[str,Any]
class WhatsAppTest(BaseModel): to:str; message:str

def db():
    c=sqlite3.connect(DB_PATH); c.row_factory=sqlite3.Row; return c
@app.on_event('startup')
def startup():
    with db() as c:
        c.execute("CREATE TABLE IF NOT EXISTS fare_observations(id TEXT PRIMARY KEY,created_at TEXT NOT NULL,origin TEXT NOT NULL,destination TEXT NOT NULL,departure_date TEXT NOT NULL,airline TEXT,flight_number TEXT,fare_basis TEXT,booking_class TEXT,price REAL NOT NULL,currency TEXT NOT NULL,seats_at_price INTEGER,source TEXT NOT NULL)")
@app.get('/health')
def health():
    return {'ok':True,'service':'tikoja-fare-intelligence','tripjack_configured':bool(os.getenv('TRIPJACK_API_KEY') and os.getenv('TRIPJACK_FLIGHT_SEARCH_URL') and os.getenv('TRIPJACK_FLIGHT_REVALIDATE_URL')),'whatsapp_configured':bool(os.getenv('META_WHATSAPP_TOKEN') and os.getenv('META_PHONE_NUMBER_ID')),'live_flight_mapping_ready':bool(os.getenv('TRIPJACK_FLIGHT_SEARCH_URL') and os.getenv('TRIPJACK_FLIGHT_REVALIDATE_URL'))}
@app.post('/fare/estimate')
def estimate(r:EstimateRequest):
    p=r.assumed_uplift_pct; f=r.current_fare
    return {'status':'SCENARIO_ESTIMATE_ONLY','route':f'{r.origin.upper()}-{r.destination.upper()}','departure_date':str(r.departure_date),'current':{'fare_per_person':f,'seats_at_fare':r.current_fare_seats,'currency':r.currency},'next_seats_requested':r.next_seats,'prediction':{'low':round(f*(1+max(0,p-5)/100),2),'expected':round(f*(1+p/100),2),'high':round(f*(1+(p+5)/100),2),'assumed_uplift_pct':p,'confidence':'NOT_CALIBRATED'},'warning':'This is a scenario estimate, not a supplier quote. Seat count and current fare alone do not reveal the next fare bucket.'}
@app.post('/fares/observations')
def save_observation(o:Observation):
    oid=str(uuid.uuid4()); ts=datetime.now(timezone.utc).isoformat()
    with db() as c: c.execute('INSERT INTO fare_observations VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)',(oid,ts,o.origin.upper(),o.destination.upper(),str(o.departure_date),o.airline,o.flight_number,o.fare_basis,o.booking_class,o.price,o.currency,o.seats_at_price,o.source))
    return {'saved':True,'id':oid,'created_at':ts}
@app.get('/fares/history')
def history(origin:str,destination:str,departure_date:date,limit:int=100):
    limit=max(1,min(limit,500))
    with db() as c: rows=c.execute('SELECT * FROM fare_observations WHERE origin=? AND destination=? AND departure_date=? ORDER BY created_at DESC LIMIT ?',(origin.upper(),destination.upper(),str(departure_date),limit)).fetchall()
    return {'items':[dict(x) for x in rows]}
async def supplier_post(url:str,payload:dict):
    key=os.getenv('TRIPJACK_API_KEY'); header=os.getenv('TRIPJACK_API_KEY_HEADER')
    if not(url and key and header): raise HTTPException(503,'TripJack live API is not activated. Configure the account-issued flight API URL, authentication header and credentials in backend/.env.')
    headers={header:f"{os.getenv('TRIPJACK_API_KEY_PREFIX','')}{key}",'Content-Type':'application/json'}
    try:
        async with httpx.AsyncClient(timeout=float(os.getenv('TRIPJACK_TIMEOUT_SECONDS','25'))) as client: res=await client.post(url,headers=headers,json=payload)
        if res.status_code>=400: raise HTTPException(502,f'TripJack returned HTTP {res.status_code}. Check the documented request schema and supplier response.')
        return res.json()
    except httpx.TimeoutException: raise HTTPException(504,'TripJack request timed out.')
    except httpx.RequestError: raise HTTPException(502,'Could not connect to TripJack.')
@app.post('/tripjack/flights/search')
async def tripjack_search(r:RawSupplierPayload):
    # Opaque payload is passed through only after customer-specific API docs define schema.
    return {'source':'tripjack','live_supplier_response':await supplier_post(os.getenv('TRIPJACK_FLIGHT_SEARCH_URL',''),r.payload)}
@app.post('/tripjack/flights/revalidate')
async def tripjack_revalidate(r:RawSupplierPayload):
    return {'source':'tripjack','live_supplier_response':await supplier_post(os.getenv('TRIPJACK_FLIGHT_REVALIDATE_URL',''),r.payload)}

def verify_meta(raw:bytes,signature:Optional[str])->bool:
    secret=os.getenv('META_APP_SECRET')
    if not secret: return False
    expected='sha256='+hmac.new(secret.encode(),raw,hashlib.sha256).hexdigest()
    return bool(signature and hmac.compare_digest(expected,signature))
async def send_whatsapp(to:str,text:str):
    token=os.getenv('META_WHATSAPP_TOKEN'); phone=os.getenv('META_PHONE_NUMBER_ID'); version=os.getenv('META_GRAPH_VERSION','v21.0')
    if not(token and phone): raise HTTPException(503,'WhatsApp Cloud API is not configured.')
    url=f'https://graph.facebook.com/{version}/{phone}/messages'
    async with httpx.AsyncClient(timeout=20) as client:
        r=await client.post(url,headers={'Authorization':f'Bearer {token}'},json={'messaging_product':'whatsapp','to':to,'type':'text','text':{'body':text}})
    if r.status_code>=400: raise HTTPException(502,'Meta WhatsApp API rejected the message. Check token, phone number ID and recipient permissions.')
    return r.json()
def parse_search(text:str):
    # Simple first-stage text parser: e.g. "AMD PQC 2026-12-20 2"
    m=re.search(r'\b([A-Z]{3})\s+([A-Z]{3})\s+(\d{4}-\d{2}-\d{2})(?:\s+(\d+))?\b',text.upper())
    return m.groups() if m else None
@app.get('/whatsapp/webhook')
async def verify_webhook(request:Request):
    q=request.query_params
    if q.get('hub.mode')=='subscribe' and q.get('hub.verify_token')==os.getenv('META_VERIFY_TOKEN'):
        return Response(content=q.get('hub.challenge',''),media_type='text/plain')
    raise HTTPException(403,'WhatsApp webhook verification failed.')
@app.post('/whatsapp/webhook')
async def whatsapp_webhook(request:Request,x_hub_signature_256:Optional[str]=Header(default=None)):
    raw=await request.body()
    if os.getenv('META_APP_SECRET') and not verify_meta(raw,x_hub_signature_256): raise HTTPException(401,'Invalid Meta webhook signature.')
    body=json.loads(raw or b'{}'); replies=[]
    for entry in body.get('entry',[]):
      for change in entry.get('changes',[]):
       value=change.get('value',{})
       for msg in value.get('messages',[]):
        sender=msg.get('from',''); text=msg.get('text',{}).get('body','').strip()
        parsed=parse_search(text)
        if parsed:
            a,b,d,pax=parsed; pax=pax or '1'
            reply=(f'TIKOJA flight request received: {a} to {b}, {d}, {pax} passenger(s).\\n'
                   'To return live fares, Tikoja must first activate its TripJack flight search API mapping. Please use the website or contact our agent meanwhile.')
        else:
            reply=('Welcome to TIKOJA Flight Assistant!\\nSend your request in this format:\\n'
                   'ORIGIN DESTINATION YYYY-MM-DD PASSENGERS\\nExample: AMD PQC 2026-12-20 2\\n'
                   'You can also use our website for country selection, dates, cabin and passenger details.')
        if sender and os.getenv('META_WHATSAPP_TOKEN') and os.getenv('META_PHONE_NUMBER_ID'):
            try: await send_whatsapp(sender,reply); replies.append({'to':sender,'sent':True})
            except HTTPException as e: replies.append({'to':sender,'sent':False,'error':e.detail})
    return {'received':True,'replies':replies}
@app.post('/whatsapp/send-test')
async def whatsapp_test(r:WhatsAppTest): return {'sent':True,'result':await send_whatsapp(r.to,r.message)}
