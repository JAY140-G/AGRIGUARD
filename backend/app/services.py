import hashlib, io, json, logging, uuid
from datetime import datetime, timezone
from PIL import Image, ImageDraw, ExifTags
from sqlalchemy import select
from .db import Photo, Job, Farm
from . import storage
from .config import settings

log=logging.getLogger('agriscan')
def uid(): return str(uuid.uuid4())
def notify(job_id):
    if settings.redis_url:
        try:
            import redis
            redis.Redis.from_url(settings.redis_url,socket_timeout=1).rpush('agriscan:jobs',job_id)
        except Exception: log.warning(json.dumps({'event':'redis_unavailable','action':'database_poll_fallback'}))

def read_image(data):
    if not data or len(data)>12*1024*1024: raise ValueError('Images must be between 1 byte and 12 MiB')
    try:
        with Image.open(io.BytesIO(data)) as im:
            if im.format not in ('JPEG','PNG'): raise ValueError('Only JPEG and PNG are supported')
            if im.width*im.height>25_000_000: raise ValueError('Image exceeds 25 megapixels')
            fmt=im.format; metadata={'width':im.width,'height':im.height,'format':fmt}
            exif=im.getexif()
            for tag,name in [(271,'make'),(272,'model'),(36867,'capture_time_raw'),(306,'modified_time_raw')]:
                if tag in exif: metadata[name]=str(exif[tag])[:200]
            location=None
            gps=exif.get_ifd(34853)
            if gps:
                def degree(v): return float(v[0])+float(v[1])/60+float(v[2])/3600
                lat=degree(gps[2])*(-1 if gps.get(1)=='S' else 1)
                lon=degree(gps[4])*(-1 if gps.get(3)=='W' else 1)
                if not (-90<=lat<=90 and -180<=lon<=180): raise ValueError('Invalid EXIF GPS')
                location=(lon,lat)
            im.verify()
        with Image.open(io.BytesIO(data)) as decoded: decoded.load()
        return metadata,location,'.jpg' if fmt=='JPEG' else '.png'
    except (OSError, SyntaxError, KeyError, TypeError, ZeroDivisionError, Image.DecompressionBombError) as e:
        raise ValueError('Corrupt or invalid image metadata') from e

def add_photo(db,farm, data, domain, mission_id=None, manual=None, simulated=False, simulated_location=None):
    metadata,location,ext=read_image(data)
    digest=hashlib.sha256(data).hexdigest()
    existing=db.scalar(select(Photo).where(Photo.farm_id==farm.id,Photo.digest==digest))
    if existing: return existing,False
    source='exif' if location else 'missing'
    if manual is not None: location=manual; source='manual'
    if simulated_location is not None: location=simulated_location; source='simulated'
    ident=uid(); key=ident+ext
    storage.put(key,data)
    raw_time=metadata.get('capture_time_raw')
    captured=datetime.now(timezone.utc).isoformat()
    metadata['capture_time_source']='upload_or_simulator_time'
    if raw_time:
        try:
            captured=datetime.strptime(raw_time,'%Y:%m:%d %H:%M:%S').isoformat(); metadata['capture_timezone']='unknown'; metadata['capture_time_source']='exif'
        except ValueError: pass
    photo=Photo(id=ident,farm_id=farm.id,mission_id=mission_id,digest=digest,storage_key=key,captured=captured,
                lon=location[0] if location else None,lat=location[1] if location else None,location_source=source,
                metadata_json=json.dumps(metadata),domain=domain,simulated=simulated,status='queued')
    db.add(photo); db.flush()
    job=Job(id=uid(),photo_id=ident,status='queued'); db.add(job); db.flush()
    return photo,True

def synthetic(mission_id,index):
    import random
    rng=random.Random(f'{mission_id}:{index}')
    im=Image.new('RGB',(640,480),(83,110,48)); d=ImageDraw.Draw(im)
    for x in range(-480,900,28): d.line((x,0,x+480,480),fill=(49+rng.randrange(20),82+rng.randrange(30),35),width=14)
    for _ in range(12):
        x,y=rng.randrange(600),rng.randrange(440)
        d.ellipse((x,y,x+30,y+24),fill=(136,130+rng.randrange(30),60))
    d.rectangle((0,440,640,480),fill=(20,40,27)); d.text((15,454),f'SIMULATED CAPTURE / {index:04d} / {mission_id[:8]}',fill='white')
    out=io.BytesIO(); im.save(out,format='JPEG',quality=85); return out.getvalue()
