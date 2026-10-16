import csv, hashlib, hmac, io, json, logging, secrets, uuid
from datetime import datetime, timedelta, timezone
from fastapi import FastAPI, Depends, HTTPException, Request, Response, UploadFile, File, Form, Query
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select, text, update, func
from sqlalchemy.exc import IntegrityError
from .config import settings
from .db import Session, engine, User, Login, Farm, Mission, Photo, Job
from .schemas import Credentials, FarmInput, PlanInput, FeedbackInput, LocationInput
from .geo import area, generate
from .drone import Simulator, transition
from .services import uid, add_photo, notify
from . import storage

app=FastAPI(docs_url='/api/docs',openapi_url='/api/openapi.json',redoc_url='/api/redoc',title='AgriScan API',version='1.0.0',description='Simulation-first crop survey workspace. All current analysis is simulated. No live aircraft control.')
origins=settings.allowed_origins.split(',')
if settings.environment=='production' and not settings.cookie_secure: raise RuntimeError('Production requires COOKIE_SECURE=true and HTTPS')
app.add_middleware(CORSMiddleware,allow_origins=origins,allow_credentials=True,allow_methods=['GET','POST','PUT','DELETE'],allow_headers=['Content-Type','X-AgriScan'])
logging.basicConfig(level=logging.INFO,format='%(message)s')

@app.middleware('http')
async def guard(request:Request, call_next):
    if request.method in ('POST','PUT','DELETE','PATCH'):
        origin=request.headers.get('origin')
        if (origin and origin not in origins) or request.headers.get('x-agriscan')!='1':
            return Response('Untrusted origin or missing X-AgriScan header',status_code=403)
    response=await call_next(request)
    response.headers['X-Content-Type-Options']='nosniff'
    logging.getLogger('api').info(json.dumps({'method':request.method,'path':request.url.path,'status':response.status_code}))
    return response

@app.exception_handler(ValueError)
async def invalid(request,exc):
    from fastapi.responses import JSONResponse
    return JSONResponse(status_code=422,content={'detail':str(exc)})

def db_session():
    with Session() as db: yield db

def owner(request:Request,db=Depends(db_session)):
    token=request.cookies.get('agriscan_session','')
    login=db.get(Login,hashlib.sha256(token.encode()).hexdigest())
    if not login or login.expires.replace(tzinfo=timezone.utc)<datetime.now(timezone.utc): raise HTTPException(401,'Sign in required')
    return login.user_id

def farm_owned(db,ident,user):
    f=db.get(Farm,ident)
    if not f or f.owner_id!=user: raise HTTPException(404,'Farm not found')
    return f

def mission_owned(db,ident,user):
    m=db.get(Mission,ident)
    if not m: raise HTTPException(404,'Mission not found')
    farm_owned(db,m.farm_id,user); return m

def photo_owned(db,ident,user):
    p=db.get(Photo,ident)
    if not p: raise HTTPException(404,'Image not found')
    farm_owned(db,p.farm_id,user); return p

def farm_dict(f): return {'id':f.id,'name':f.name,'crop':f.crop,'planting_date':f.planting_date,'boundary':json.loads(f.boundary),'area_ha':f.area_ha,'area_acres':f.area_ha*2.47105381}
def mission_dict(m): return {'id':m.id,'farm_id':m.farm_id,'state':m.state,'plan':json.loads(m.plan),'progress':m.progress,'created':m.created.isoformat(),'telemetry':json.loads(m.telemetry),'error':m.error}
def photo_dict(p): return {'id':p.id,'farm_id':p.farm_id,'mission_id':p.mission_id,'captured':p.captured,'lon':p.lon,'lat':p.lat,'location_source':p.location_source,'metadata':json.loads(p.metadata_json),'domain':p.domain,'simulated_capture':p.simulated,'status':p.status,'result':json.loads(p.result) if p.result else None,'feedback':p.feedback}

def password_hash(password,salt=None):
    salt=salt or secrets.token_hex(16)
    return salt+':'+hashlib.scrypt(password.encode(),salt=salt.encode(),n=16384,r=8,p=1).hex()

def create_login(db,user,response):
    token=secrets.token_urlsafe(32)
    db.add(Login(token_hash=hashlib.sha256(token.encode()).hexdigest(),user_id=user.id,expires=datetime.now(timezone.utc)+timedelta(days=7)))
    db.commit(); response.set_cookie('agriscan_session',token,httponly=True,secure=settings.cookie_secure,samesite='lax',max_age=604800)
    return {'id':user.id,'email':user.email}

@app.post('/api/auth/register',status_code=201)
def register(payload:Credentials,response:Response,db=Depends(db_session)):
    user=User(id=uid(),email=payload.email.lower(),password=password_hash(payload.password))
    db.add(user)
    try: db.flush()
    except IntegrityError: db.rollback(); raise HTTPException(409,'Email already registered')
    return create_login(db,user,response)

@app.post('/api/auth/login')
def login(payload:Credentials,response:Response,db=Depends(db_session)):
    user=db.scalar(select(User).where(User.email==payload.email.lower()))
    encoded=password_hash(payload.password,user.password.split(':')[0] if user else '0'*32)
    if not user or not hmac.compare_digest(encoded,user.password): raise HTTPException(401,'Invalid email or password')
    return create_login(db,user,response)

@app.get('/api/auth/me')
def me(user=Depends(owner),db=Depends(db_session)):
    u=db.get(User,user); return {'id':u.id,'email':u.email}

@app.post('/api/auth/logout')
def logout(request:Request,response:Response,user=Depends(owner),db=Depends(db_session)):
    key=hashlib.sha256(request.cookies.get('agriscan_session','').encode()).hexdigest()
    db.delete(db.get(Login,key)); db.commit(); response.delete_cookie('agriscan_session'); return {'ok':True}

@app.get('/api/health')
def health(db=Depends(db_session)):
    db.execute(text('SELECT 1'))
    redis_status='not configured (DB polling mode)'
    if settings.redis_url:
        try:
            import redis
            redis.Redis.from_url(settings.redis_url,socket_timeout=1).ping(); redis_status='ok'
        except Exception: redis_status='unavailable; durable DB polling fallback'
    return {'database':'ok','redis':redis_status,'analysis':'Simulated analysis','drone':'simulator only'}

@app.get('/api/settings')
def integration(user=Depends(owner)):
    s=Simulator(); return {'drone':s.connect(),'analysis':'Simulated analysis','model':'demo-hash-v1','storage':settings.storage_backend,'map':'configurable MapLibre style; confirm provider licence and attribution before production'}

@app.get('/api/farms')
def farms(user=Depends(owner),db=Depends(db_session),offset:int=Query(0,ge=0),limit:int=Query(100,ge=1,le=200)):
    return [farm_dict(f) for f in db.scalars(select(Farm).where(Farm.owner_id==user).order_by(Farm.name).offset(offset).limit(limit))]

def save_geo(db,f):
    if engine.dialect.name=='postgresql': db.execute(text('UPDATE farms SET boundary_geog=ST_SetSRID(ST_GeomFromGeoJSON(:b),4326)::geography WHERE id=:id'),{'b':f.boundary,'id':f.id})

@app.post('/api/farms',status_code=201)
def create_farm(p:FarmInput,user=Depends(owner),db=Depends(db_session)):
    f=Farm(id=uid(),owner_id=user,name=p.name,crop=p.crop,planting_date=p.planting_date.isoformat() if p.planting_date else None,boundary=json.dumps(p.boundary),area_ha=area(p.boundary))
    db.add(f); db.flush(); save_geo(db,f); db.commit(); return farm_dict(f)

@app.put('/api/farms/{ident}')
def edit_farm(ident:str,p:FarmInput,user=Depends(owner),db=Depends(db_session)):
    f=farm_owned(db,ident,user)
    active=db.scalar(select(Mission.id).where(Mission.farm_id==ident,Mission.state.in_(['queued','running','paused'])))
    if active: raise HTTPException(409,'Finish or abort active simulation before editing farm')
    f.name=p.name; f.crop=p.crop; f.planting_date=p.planting_date.isoformat() if p.planting_date else None; f.boundary=json.dumps(p.boundary); f.area_ha=area(p.boundary)
    db.flush(); save_geo(db,f); db.commit(); return farm_dict(f)

@app.post('/api/farms/{ident}/missions',status_code=201)
def plan(ident:str,p:PlanInput,user=Depends(owner),db=Depends(db_session)):
    f=farm_owned(db,ident,user); route=generate(json.loads(f.boundary),p)
    route['boundary_snapshot']=json.loads(f.boundary)
    m=Mission(id=uid(),farm_id=ident,plan=json.dumps(route),state='planned',progress=0,telemetry='{}')
    db.add(m); db.commit(); return mission_dict(m)

@app.get('/api/farms/{ident}/missions')
def missions(ident:str,user=Depends(owner),db=Depends(db_session),offset:int=Query(0,ge=0),limit:int=Query(50,ge=1,le=200)):
    farm_owned(db,ident,user)
    return [mission_dict(m) for m in db.scalars(select(Mission).where(Mission.farm_id==ident).order_by(Mission.created.desc()).offset(offset).limit(limit))]

@app.get('/api/missions/{ident}')
def mission(ident:str,user=Depends(owner),db=Depends(db_session)): return mission_dict(mission_owned(db,ident,user))

@app.get('/api/missions/{ident}/telemetry')
def telemetry(ident:str,user=Depends(owner),db=Depends(db_session)): return json.loads(mission_owned(db,ident,user).telemetry)

@app.post('/api/missions/{ident}/{action}')
def command(ident:str,action:str,user=Depends(owner),db=Depends(db_session)):
    if action not in ('start','pause','resume','abort','fail'): raise HTTPException(404,'Unknown simulator action')
    m=mission_owned(db,ident,user); old=m.state; new=transition(old,action)
    if action=='start':
        route=json.loads(m.plan)
        if route.get('boundary_snapshot')!=json.loads(db.get(Farm,m.farm_id).boundary): raise HTTPException(409,'Farm boundary changed; generate a new survey')
        sim=Simulator(); sim.connect(); sim.upload(route)
    result=db.execute(update(Mission).where(Mission.id==ident,Mission.state==old).values(state=new,error='Injected simulator connection failure' if action=='fail' else None))
    if result.rowcount!=1: db.rollback(); raise HTTPException(409,'Mission changed; refresh before retrying')
    db.commit(); db.refresh(m); return mission_dict(m)

@app.post('/api/farms/{ident}/images',status_code=201)
async def upload(ident:str,file:UploadFile=File(...),domain:str=Form('aerial'),mission_id:str|None=Form(None),lon:float|None=Form(None),lat:float|None=Form(None),user=Depends(owner),db=Depends(db_session)):
    f=farm_owned(db,ident,user)
    if domain not in ('aerial','closeup','unknown'): raise HTTPException(422,'Invalid image domain')
    if mission_id and mission_owned(db,mission_id,user).farm_id!=ident: raise HTTPException(422,'Mission belongs to another farm')
    manual=None
    if lon is not None or lat is not None:
        if lon is None or lat is None: raise HTTPException(422,'Supply both location coordinates')
        loc=LocationInput(lon=lon,lat=lat); manual=(loc.lon,loc.lat)
    data=await file.read(12*1024*1024+1)
    try:
        photo,created=add_photo(db,f,data,domain,mission_id,manual)
        db.commit()
    except IntegrityError:
        db.rollback(); raise HTTPException(409,'Duplicate upload; refresh image list')
    job=db.scalar(select(Job).where(Job.photo_id==photo.id)); notify(job.id)
    return {'photo':photo_dict(photo),'duplicate':not created}

@app.get('/api/farms/{ident}/images')
def images(ident:str,user=Depends(owner),db=Depends(db_session),offset:int=Query(0,ge=0),limit:int=Query(100,ge=1,le=200),mission_id:str|None=None,date_from:str|None=None,date_to:str|None=None,label:str|None=None,min_score:float|None=Query(None,ge=0,le=1)):
    farm_owned(db,ident,user); q=select(Photo).where(Photo.farm_id==ident)
    if mission_id: q=q.where(Photo.mission_id==mission_id)
    if date_from: q=q.where(Photo.captured>=date_from)
    if date_to: q=q.where(Photo.captured<=date_to+'T23:59:59')
    # Prediction labels and scores are filtered before pagination for consistent pages.
    rows=[photo_dict(p) for p in db.scalars(q.order_by(Photo.captured.desc()))]
    if label: rows=[p for p in rows if label.lower() in (p['result'] or {}).get('label','').lower()]
    if min_score is not None: rows=[p for p in rows if (p['result'] or {}).get('score') is not None and p['result']['score']>=min_score]
    return rows[offset:offset+limit]

@app.get('/api/images/{ident}/original')
def original(ident:str,user=Depends(owner),db=Depends(db_session)):
    p=photo_owned(db,ident,user)
    return Response(storage.get(p.storage_key),media_type='image/jpeg' if p.storage_key.endswith('.jpg') else 'image/png',headers={'Cache-Control':'private, max-age=300'})

@app.put('/api/images/{ident}/location')
def location(ident:str,p:LocationInput,user=Depends(owner),db=Depends(db_session)):
    photo=photo_owned(db,ident,user); photo.lon=p.lon; photo.lat=p.lat; photo.location_source='manual'; db.commit(); return photo_dict(photo)

@app.put('/api/images/{ident}/feedback')
def feedback(ident:str,p:FeedbackInput,user=Depends(owner),db=Depends(db_session)):
    photo=photo_owned(db,ident,user); photo.feedback=p.verdict; db.commit(); return photo_dict(photo)

@app.get('/api/images/{ident}/job')
def job(ident:str,user=Depends(owner),db=Depends(db_session)):
    photo_owned(db,ident,user); j=db.scalar(select(Job).where(Job.photo_id==ident))
    return {'id':j.id,'status':j.status,'attempts':j.attempts,'error':j.error}

@app.post('/api/images/{ident}/retry')
def retry(ident:str,user=Depends(owner),db=Depends(db_session)):
    p=photo_owned(db,ident,user); j=db.scalar(select(Job).where(Job.photo_id==ident))
    if j.status!='failed': raise HTTPException(409,'Only failed jobs can be retried')
    j.status='queued'; j.attempts=0; j.error=None; p.status='queued'; db.commit(); notify(j.id); return {'status':'queued'}

@app.get('/api/farms/{ident}/summary')
def summary(ident:str,user=Depends(owner),db=Depends(db_session)):
    f=farm_owned(db,ident,user); photos=list(db.scalars(select(Photo).where(Photo.farm_id==ident)))
    return {'area_ha':f.area_ha,'images':len(photos),'analysed':sum(p.status=='completed' for p in photos),
            'suspected':sum(bool(p.result and json.loads(p.result)['label'].startswith('Suspected')) for p in photos),
            'inspection':sum(p.feedback=='inspection' for p in photos),'confirmed_by_user':sum(p.feedback=='confirmed' for p in photos),'analysis_mode':'Simulated analysis'}

@app.get('/api/farms/{ident}/export/{kind}')
def export(ident:str,kind:str,user=Depends(owner),db=Depends(db_session)):
    f=farm_owned(db,ident,user); photos=list(db.scalars(select(Photo).where(Photo.farm_id==ident)))
    if kind=='csv':
        buf=io.StringIO(); w=csv.writer(buf); w.writerow(['image_id','captured','longitude','latitude','location_source','label','model_score','model_version','analysis_mode','feedback'])
        for p in photos:
            r=json.loads(p.result) if p.result else {}
            # Avoid spreadsheet formula execution from user-editable cells.
            row=[p.id,p.captured,p.lon,p.lat,p.location_source,r.get('label'),r.get('score'),r.get('model_version'),r.get('analysis_mode','pending'),p.feedback]
            w.writerow([("'"+v if isinstance(v,str) and v.startswith(('=','+','-','@')) else v) for v in row])
        return Response(buf.getvalue(),media_type='text/csv',headers={'Content-Disposition':'attachment; filename=agriscan-findings.csv'})
    if kind!='geojson': raise HTTPException(404,'Use csv or geojson')
    features=[{'type':'Feature','geometry':json.loads(f.boundary),'properties':{'type':'farm','name':f.name}}]
    for m in db.scalars(select(Mission).where(Mission.farm_id==ident)):
        plan=json.loads(m.plan)
        for field in ('survey_segments','transit_segments'):
            for geom in plan[field]: features.append({'type':'Feature','geometry':geom,'properties':{'type':field,'mission_id':m.id,'simulated':True,'approved_flight_plan':False}})
    for p in photos:
        if p.lon is not None:
            features.append({'type':'Feature','geometry':{'type':'Point','coordinates':[p.lon,p.lat]},'properties':{**photo_dict(p),'precision':'photo-level'}})
    return Response(json.dumps({'type':'FeatureCollection','features':features}),media_type='application/geo+json',headers={'Content-Disposition':'attachment; filename=agriscan.geojson'})
