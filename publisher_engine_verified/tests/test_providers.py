import pytest
from leadengine.providers import Providers

@pytest.mark.asyncio
@pytest.mark.parametrize('name,key,response',[
 ('tavily','TAVILY_API_KEY',{'results':[{'url':'https://publisher.org/','title':'APK','content':'Contact'}]}),
 ('brave','BRAVE_API_KEY',{'web':{'results':[{'url':'https://publisher.org/','title':'APK','description':'Contact'}]}}),
 ('serper','SERPER_API_KEY',{'organic':[{'link':'https://publisher.org/','title':'APK','snippet':'Contact'}]}),
 ('firecrawl','FIRECRAWL_API_KEY',{'data':{'web':[{'url':'https://publisher.org/','title':'APK','description':'Contact'}]}}),
 ('searxng','SEARXNG_URL',{'results':[{'url':'https://publisher.org/','title':'APK','content':'Contact'}]})])
async def test_provider_contract(name,key,response,cfg,db,monkeypatch):
    monkeypatch.setenv(key,'https://search.example.org' if name=='searxng' else 'test-key-not-real')
    cfg['search']['providers']=[name];p=Providers(cfg,db);calls=[]
    async def request(method,url,**kw):calls.append((method,url,kw));return response
    p.request=request
    result=await p.search('apk contact')
    assert result[0]['url']=='https://publisher.org/'
    assert result[0]['provider']==name
    assert db.rows('SELECT * FROM usage')[0]['units']==(2 if name=='firecrawl' else 1)
    assert len(await p.search('apk contact'))==1 and len(calls)==1
    if name=='tavily':
        assert calls[0][2]['json']['search_depth']=='basic'
        assert calls[0][2]['json']['auto_parameters'] is False

@pytest.mark.asyncio
async def test_failed_request_not_retried_or_refunded(cfg,db,monkeypatch):
    monkeypatch.setenv('TAVILY_API_KEY','fake');cfg['search']['providers']=['tavily'];p=Providers(cfg,db);calls=[]
    async def fail(*a,**k):calls.append(1);raise RuntimeError('API HTTP 429')
    p.request=fail
    assert await p.search('first')==[]
    assert await p.search('second')==[]
    assert len(calls)==1 and db.rows('SELECT * FROM usage')[0]['units']==1

@pytest.mark.asyncio
async def test_provider_filters_nonpublic_urls(cfg,db):
    p=Providers(cfg,db)
    async def response(*a,**k):return {'results':[{'url':'http://127.0.0.1/'},{'url':'https://publisher.org/a.apk'}]}
    p.request=response
    assert await p._search('tavily','query')==[]

@pytest.mark.asyncio
async def test_hunter_reserves_per_email_worst_case(cfg,db,monkeypatch):
    monkeypatch.setenv('HUNTER_API_KEY','not-a-real-key');cfg['hunter']['enabled']=True
    p=Providers(cfg,db);calls=[]
    async def response(*args,**kwargs):
        calls.append(kwargs)
        return {'data':{'emails':[]}}
    p.request=response
    await p.hunter('publisher.org')
    assert db.rows('SELECT * FROM usage')[0]['units']==10
    assert calls[0]['params']['limit']==10
    assert 'api_key' not in calls[0]['params']
    assert calls[0]['headers']['X-API-KEY']=='not-a-real-key'

@pytest.mark.asyncio
async def test_api_reads_all_stream_chunks():
    from leadengine.providers import read_limited
    class Stream:
        async def iter_chunked(self,size):
            for chunk in [b'{"data":',b'[]',b'}']:yield chunk
    assert await read_limited(Stream(),100)==b'{"data":[]}'

@pytest.mark.asyncio
async def test_api_limits_streamed_response_size():
    from leadengine.providers import read_limited
    class Stream:
        async def iter_chunked(self,size):
            yield b'1234'
            yield b'5678'
    with pytest.raises(RuntimeError):await read_limited(Stream(),5)
