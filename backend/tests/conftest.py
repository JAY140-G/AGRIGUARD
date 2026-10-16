import os, tempfile
from pathlib import Path
import pytest

TEST_ROOT=tempfile.mkdtemp(prefix='agriscan-tests-')
os.environ['DATABASE_URL']=os.environ.get('TEST_DATABASE_URL','sqlite:///'+TEST_ROOT+'/test.db')
os.environ['STORAGE_DIR']=TEST_ROOT+'/images'
os.environ['REDIS_URL']=''
os.environ['ENVIRONMENT']='development'
from app.db import Base, engine
from app.main import app
from fastapi.testclient import TestClient

@pytest.fixture(scope='session',autouse=True)
def database():
    Base.metadata.create_all(engine)
    if engine.dialect.name=='postgresql':
        from sqlalchemy import text
        with engine.begin() as c:
            c.execute(text('CREATE EXTENSION IF NOT EXISTS postgis'))
            c.execute(text('ALTER TABLE farms ADD COLUMN IF NOT EXISTS boundary_geog geography(Polygon,4326)'))
    yield
    Base.metadata.drop_all(engine)

@pytest.fixture
def client():
    import uuid
    c=TestClient(app,headers={'X-AgriScan':'1'})
    r=c.post('/api/auth/register',json={'email':str(uuid.uuid4())+'@test.example','password':'test-password-123'})
    assert r.status_code==201
    return c

@pytest.fixture
def boundary():
    return {'type':'Polygon','coordinates':[[[75.780,26.910],[75.784,26.910],[75.784,26.913],[75.780,26.913],[75.780,26.910]]]}

@pytest.fixture
def farm(client,boundary):
    r=client.post('/api/farms',json={'name':'Test farm','crop':'Wheat','boundary':boundary})
    assert r.status_code==201,r.text
    return r.json()
