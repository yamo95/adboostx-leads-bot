import pytest
from fastapi.testclient import TestClient
from leadengine.api import create_app

@pytest.fixture
def client(cfg,monkeypatch):
    monkeypatch.delenv('DASHBOARD_TOKEN',raising=False)
    with TestClient(create_app(cfg),base_url='http://localhost') as c:yield c

def test_home_and_status(client):
    assert client.get('/').status_code==200
    assert client.get('/api/status').json()['counts']['sites']==0
    assert "default-src 'self'" in client.get('/').headers['content-security-policy']

def test_host_guard(client):assert client.get('/api/status',headers={'host':'evil.org'}).status_code==400

def test_write_guard(client):assert client.post('/api/sites',json={'urls':['https://publisher.org/']}).status_code==403

def test_add_and_override(client):
    h={'X-Leadengine-Client':'dashboard'}
    r=client.post('/api/sites',json={'urls':['https://publisher.org/','http://127.0.0.1/']},headers=h)
    assert r.json()['added']==1 and len(r.json()['errors'])==1
    assert client.post('/api/sites/publisher.org/override',json={'decision':'PASS','reason':'single app'},headers=h).status_code==200
    assert client.get('/api/leads').json()['rows'][0]['effective_classification']=='PASS'
    assert client.get('/api/export/leads').status_code==200
    assert client.post('/api/sites/publisher.org/suppress',json={'enabled':True},headers=h).status_code==200
    assert client.get('/api/leads').json()['total']==0

def test_token_auth(cfg,monkeypatch):
    monkeypatch.setenv('DASHBOARD_TOKEN','test-only-token')
    with TestClient(create_app(cfg),base_url='http://localhost') as c:
        assert c.get('/api/status').status_code==401
        assert c.get('/api/status',headers={'Authorization':'Bearer test-only-token'}).status_code==200
