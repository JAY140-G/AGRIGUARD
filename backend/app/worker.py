"""One or more workers: DB row locks prevent duplicate processing on Postgres.
Redis wakes workers; DB jobs remain authoritative and survive Redis loss.
"""
import json, logging, math, time
from datetime import datetime, timezone
from sqlalchemy import select
from .db import Session, Job, Photo, Farm, Mission, now
from .inference import DemoAnalyzer
from .drone import transition
from .services import add_photo, synthetic
from . import storage
from .config import settings
logging.basicConfig(level=logging.INFO,format='%(message)s')
log=logging.getLogger('worker')

def tick_mission():
    with Session.begin() as db:
        m=db.scalar(select(Mission).where(Mission.state.in_(['queued','running','rtl'])).order_by(Mission.created).with_for_update(skip_locked=True))
        if not m: return False
        if m.state=='queued': m.state=transition(m.state,'run')
        plan=json.loads(m.plan); points=plan['capture_points']; index=int(m.progress)
        existing_telem=json.loads(m.telemetry or '{}')
        obstacle=existing_telem.get('obstacle',{'sensor_status':'simulated_operational','is_simulated':True,'detected':False,'distance_m':None,'bearing_deg':None,'safe_state_triggered':False,'reported_response':'none'})

        if m.state=='rtl':
            if index<=0:
                m.state=transition(m.state,'complete')
                m.telemetry=json.dumps({'position':plan.get('launch',points[0]),'battery_percent':round(max(10,100-(index+1)/len(points)*70),1),'captured':index,'total':len(points),'simulated':True,'connected':True,'flight_mode':'RTL','obstacle':obstacle,'captured_events':existing_telem.get('captured_events',[])})
                return True
            step=max(1,len(points)//6); new_idx=max(0,index-step); m.progress=new_idx; loc=points[new_idx]
            m.telemetry=json.dumps({'position':loc,'battery_percent':round(max(10,100-(index+1)/len(points)*70),1),'captured':index,'total':len(points),'simulated':True,'connected':True,'flight_mode':'RTL','obstacle':obstacle,'captured_events':existing_telem.get('captured_events',[])})
            if new_idx==0: m.state=transition(m.state,'complete')
            return True

        if index>=len(points): m.state=transition(m.state,'complete'); return True
        location=points[index]; farm=db.get(Farm,m.farm_id)

        if index<len(points)-1:
            dx=points[index+1][0]-points[index][0]; dy=points[index+1][1]-points[index][1]
            heading=round((math.degrees(math.atan2(dx,dy))+360)%360,1)
        else: heading=0.0

        extra_metadata={
            'altitude_m':plan.get('options',{}).get('altitude_m',60),
            'heading_deg':heading,
            'capture_policy':plan.get('capture_policy','waypoints'),
            'upload_status':'persisted',
            'capture_status':'captured',
            'geolocation_note':'GPS coordinate is aircraft telemetry at shutter release; oblique ground projection requires calibrated camera orientation.'
        }
        photo,_=add_photo(db,farm,synthetic(m.id,index),'aerial',m.id,simulated=True,simulated_location=location,extra_metadata=extra_metadata)
        m.progress=index+1
        events=existing_telem.get('captured_events',[])
        events.append({'photo_id':photo.id,'position':location,'source':'simulated'})
        if len(events)>40: events=events[-40:]
        m.telemetry=json.dumps({'position':location,'battery_percent':round(max(10,100-(index+1)/len(points)*70),1),
                                'altitude_m':plan.get('options',{}).get('altitude_m',60),
                                'heading_deg':heading,
                                'speed_mps':plan.get('options',{}).get('speed_mps',5),
                                'captured':index+1,'total':len(points),'simulated':True,'connected':True,
                                'flight_mode':'AUTO_SURVEY',
                                'obstacle':obstacle,
                                'captured_events':events})
        if m.progress>=len(points): m.state=transition(m.state,'complete')
        return True


def process_job():
    with Session.begin() as db:
        job=db.scalar(select(Job).where(Job.status.in_(['queued','retry'])).order_by(Job.updated).with_for_update(skip_locked=True))
        if not job: return False
        photo=db.get(Photo,job.photo_id); farm=db.get(Farm,photo.farm_id)
        job.attempts+=1; job.status='running'; photo.status='running'; db.flush()
        try:
            result=DemoAnalyzer().analyze(storage.get(photo.storage_key),farm.crop,photo.domain)
            photo.result=result.model_dump_json(); photo.status='completed'; job.status='completed'; job.error=None
        except Exception as e:
            job.error=f'{type(e).__name__}: analysis failed'; job.status='failed' if job.attempts>=3 else 'retry'; photo.status=job.status
            log.exception(json.dumps({'event':'analysis_error','job_id':job.id}))
        job.updated=now()
        return True

def run():
    r=None
    if settings.redis_url:
        import redis
        r=redis.Redis.from_url(settings.redis_url,socket_timeout=2)
    log.info(json.dumps({'event':'worker_started','analysis':'simulated','live_aircraft':False}))
    while True:
        try:
            active=tick_mission()
            for _ in range(4):
                if not process_job(): break
            if r and not active:
                try: r.blpop('agriscan:jobs',timeout=1)
                except Exception: time.sleep(1)
            else: time.sleep(.25 if active else 1)
        except Exception:
            log.exception(json.dumps({'event':'worker_tick_failed'})); time.sleep(2)

if __name__=='__main__': run()
