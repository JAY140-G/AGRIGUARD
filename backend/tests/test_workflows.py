import io, json
import pytest
from PIL import Image
from shapely.geometry import shape
from app.geo import transform
from app.geo import area, polygon, generate, projection
from app.schemas import PlanInput
from app.drone import transition, Simulator
from app.inference import DemoAnalyzer
from app.worker import tick_mission, process_job
from app.db import Session, Mission, Job, Photo
from fastapi.testclient import TestClient
from app.main import app

def image(color='green'):
    b=io.BytesIO();Image.new('RGB',(60,50),color).save(b,format='JPEG');return b.getvalue()

def test_area_and_validation(boundary):
    assert 12<area(boundary)<14
    with pytest.raises(ValueError): polygon({'type':'Polygon','coordinates':[[[0,0],[1,1],[0,1],[1,0],[0,0]]]})
    with pytest.raises(ValueError): polygon({'type':'Polygon','coordinates':[[[200,1],[201,1],[200,2],[200,1]]]})
    with pytest.raises(ValueError): area({'type':'Polygon','coordinates':[[[1,1],[1,1],[1,1],[1,1]]]})

def test_concave_route_exclusion(boundary):
    concave={'type':'Polygon','coordinates':[[[75.780,26.910],[75.784,26.910],[75.784,26.913],[75.7825,26.913],[75.7825,26.9115],[75.7815,26.9115],[75.7815,26.913],[75.780,26.913],[75.780,26.910]]]}
    exclusion={'type':'Polygon','coordinates':[[[75.7804,26.9104],[75.781,26.9104],[75.781,26.911],[75.7804,26.911],[75.7804,26.9104]]]}
    plan=generate(concave,PlanInput(exclusions=[exclusion]))
    f,_=projection(shape(concave)); allowed=transform(f,shape(concave)).difference(transform(f,shape(exclusion)))
    assert len(plan['survey_segments'])>10 and plan['transit_segments']
    for s in plan['survey_segments']: assert allowed.buffer(.001).covers(transform(f,shape(s)))
    for p in plan['capture_points']:
        from shapely.geometry import Point
        assert allowed.buffer(.001).covers(transform(f,Point(p)))
    assert plan['provisional'] and plan['image_count']==len(plan['capture_points'])

def test_camera_coverage(boundary):
    p=generate(boundary,PlanInput(sensor_width_mm=13.2,focal_length_mm=8.8))
    assert p['camera_coverage'] and not p['provisional']
    assert p['spacing_m']==31.5
    with pytest.raises(ValueError): PlanInput(sensor_width_mm=13.2)

def test_exclusion_outside(boundary):
    e={'type':'Polygon','coordinates':[[[76,27],[76.001,27],[76,27.001],[76,27]]]}
    with pytest.raises(ValueError):generate(boundary,PlanInput(exclusions=[e]))

@pytest.mark.parametrize('state,action,result',[('draft','plan','planned'),('planned','start','queued'),('queued','run','running'),('running','pause','paused'),('paused','resume','running'),('running','complete','completed'),('running','fail','failed'),('paused','abort','aborted')])
def test_state_transitions(state,action,result): assert transition(state,action)==result

@pytest.mark.parametrize('state,action',[('completed','start'),('running','start'),('planned','resume'),('aborted','resume'),('failed','start')])
def test_invalid_transitions(state,action):
    with pytest.raises(ValueError):transition(state,action)

def test_simulator_contract(boundary):
    s=Simulator();plan=generate(boundary,PlanInput())
    with pytest.raises(ValueError):s.upload(plan)
    assert s.connect()['live_control'] is False
    assert not s.validate(plan)
    s.upload(plan);s.disconnect();assert not s.connected

def test_uploads_and_missing_gps(client,farm):
    path='/api/farms/'+farm['id']+'/images'
    assert client.post(path,files={'file':('bad.jpg',b'not an image')}).status_code==422
    assert client.post(path,files={'file':('big.jpg',b'x'*(12*1024*1024+1))}).status_code==422
    r=client.post(path,files={'file':('crop.jpg',image(),'image/jpeg')})
    assert r.status_code==201,r.text
    p=r.json()['photo'];assert p['lon'] is None and p['lat'] is None and p['location_source']=='missing'
    dup=client.post(path,files={'file':('crop.jpg',image(),'image/jpeg')}).json()
    assert dup['duplicate'] and dup['photo']['id']==p['id']
    assert client.post(path,files={'file':('crop.jpg',image('blue'))},data={'lon':'75'}).status_code==422
    assert client.put('/api/images/'+p['id']+'/location',json={'lon':75.78,'lat':26.91}).json()['location_source']=='manual'

def test_exif_gps(client,farm):
    exif=Image.Exif();exif[34853]={1:'N',2:(26.,54.,36.),3:'E',4:(75.,46.,48.)}
    data=io.BytesIO();Image.new('RGB',(50,50),'green').save(data,format='JPEG',exif=exif)
    r=client.post('/api/farms/'+farm['id']+'/images',files={'file':('gps.jpg',data.getvalue())})
    assert r.status_code==201,r.text
    p=r.json()['photo'];assert p['location_source']=='exif';assert p['lat']==pytest.approx(26.91)

def test_inference_domain_contract():
    adapter=DemoAnalyzer();a=adapter.analyze(image(),'wheat','aerial');b=adapter.analyze(image(),'wheat','aerial')
    assert a==b and a.simulated and a.score is None and a.uncertain
    assert adapter.analyze(image(),'potato','aerial').unsupported
    assert adapter.analyze(image(),'wheat','unknown').unsupported
    assert adapter.analyze(image(),'wheat','closeup').domain=='closeup'

def test_access_control(client,farm):
    other=TestClient(app,headers={'X-AgriScan':'1'})
    other.post('/api/auth/register',json={'email':__import__('uuid').uuid4().hex+'@test.example','password':'other-password-123'})
    assert other.get('/api/farms/'+farm['id']+'/missions').status_code==404
    assert not other.get('/api/farms').json()
    assert TestClient(app).get('/api/farms').status_code==401
    assert client.post('/api/farms',headers={'Origin':'https://evil.example'},json={}).status_code==403
    p=client.post('/api/farms/'+farm['id']+'/images',files={'file':('a.jpg',image())}).json()['photo']
    for path in ['/api/images/'+p['id']+'/original','/api/images/'+p['id']+'/job','/api/farms/'+farm['id']+'/export/csv']:
        assert other.get(path).status_code==404
    assert other.put('/api/images/'+p['id']+'/feedback',json={'verdict':'confirmed'}).status_code==404


def test_complete_simulated_survey(client,farm):
    m=client.post('/api/farms/'+farm['id']+'/missions',json={'altitude_m':120,'side_overlap':0,'front_overlap':0}).json()
    ident=m['id'];base='/api/missions/'+ident
    assert client.post(base+'/start').json()['state']=='queued'
    assert client.post(base+'/start').status_code==422
    tick_mission()
    assert client.post(base+'/pause').json()['state']=='paused'
    before=client.get(base).json()['progress'];tick_mission();assert client.get(base).json()['progress']==before
    assert client.post(base+'/resume').json()['state']=='running'
    for _ in range(m['plan']['image_count']+2):tick_mission()
    for _ in range(m['plan']['image_count']+10):process_job()
    final=client.get(base).json();assert final['state']=='completed'
    photos=client.get('/api/farms/'+farm['id']+'/images?limit=200').json()
    assert len(photos)==m['plan']['image_count']
    assert all(p['status']=='completed' and p['result']['simulated'] and p['location_source']=='simulated' for p in photos)
    p=photos[0]; original_result=p['result']
    feedback=client.put('/api/images/'+p['id']+'/feedback',json={'verdict':'inspection'}).json()
    assert feedback['feedback']=='inspection' and feedback['result']==original_result
    assert client.get('/api/images/'+p['id']+'/original').headers['content-type']=='image/jpeg'
    assert 'Simulated analysis' in client.get('/api/farms/'+farm['id']+'/export/csv').text
    geo=client.get('/api/farms/'+farm['id']+'/export/geojson').json()
    assert geo['type']=='FeatureCollection' and any(f['properties']['type']=='survey_segments' for f in geo['features'] if 'type' in f['properties'])
    assert client.get('/api/farms/'+farm['id']+'/images?min_score=0.1').json()==[]
    assert client.get('/api/images/'+p['id']+'/job').json()['attempts']==1

def test_failure_and_abort(client,farm):
    base='/api/farms/'+farm['id']+'/missions'
    m=client.post(base,json={}).json();url='/api/missions/'+m['id'];client.post(url+'/start');tick_mission()
    assert client.post(url+'/fail').json()['state']=='failed'
    assert client.post(url+'/start').status_code==422
    m2=client.post(base,json={}).json();url2='/api/missions/'+m2['id'];client.post(url2+'/start')
    assert client.post(url2+'/abort').json()['state']=='aborted'


def test_analysis_retries(client,farm,monkeypatch):
    while process_job(): pass
    p=client.post('/api/farms/'+farm['id']+'/images',files={'file':('fail.jpg',image('red'))}).json()['photo']
    def fail(*args):raise RuntimeError('Injected storage outage')
    monkeypatch.setattr('app.worker.storage.get',fail)
    for _ in range(3): process_job()
    job=client.get('/api/images/'+p['id']+'/job').json()
    assert job['status']=='failed' and job['attempts']==3
    assert client.post('/api/images/'+p['id']+'/retry').json()['status']=='queued'
