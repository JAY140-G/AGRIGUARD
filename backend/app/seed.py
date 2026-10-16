"""Explicit local-only seed; credentials must be provided through environment."""
import json, os
from sqlalchemy import select
from .db import Session, User, Farm
from .main import password_hash, save_geo
from .services import uid

def run():
    from .config import settings
    if settings.environment!='development': raise SystemExit('Demo seed is disabled outside development')
    email=os.environ.get('DEMO_EMAIL','farmer@example.test'); password=os.environ.get('DEMO_PASSWORD')
    if not password or len(password)<10: raise SystemExit('Set DEMO_PASSWORD (at least 10 characters) before seeding')
    with Session.begin() as db:
        u=db.scalar(select(User).where(User.email==email))
        if not u: u=User(id=uid(),email=email,password=password_hash(password)); db.add(u); db.flush()
        if not db.scalar(select(Farm).where(Farm.owner_id==u.id)):
            p={'type':'Polygon','coordinates':[[[75.780,26.910],[75.784,26.910],[75.784,26.913],[75.780,26.913],[75.780,26.910]]]}
            from .geo import area
            f=Farm(id=uid(),owner_id=u.id,name='North field',crop='Wheat',boundary=json.dumps(p),area_ha=area(p)); db.add(f); db.flush(); save_geo(db,f)
    print('Demo farm ready. Sign in with the configured demo email and password.')
if __name__=='__main__': run()
