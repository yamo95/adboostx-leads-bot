from __future__ import annotations
import os,json,asyncio
from urllib.parse import urlsplit
import aiohttp
from .urls import normalize_url,within_site,hostname
from .parse import normalized_email,purpose
from .models import Contact

async def read_limited(stream,maximum):
    chunks=[];size=0
    async for chunk in stream.iter_chunked(16384):
        size+=len(chunk)
        if size>maximum:raise RuntimeError('Oversized API response')
        chunks.append(chunk)
    return b''.join(chunks)

KEYS={'tavily':'TAVILY_API_KEY','brave':'BRAVE_API_KEY','serper':'SERPER_API_KEY','firecrawl':'FIRECRAWL_API_KEY','hunter':'HUNTER_API_KEY'}

class Providers:
    def __init__(self,cfg,db):
        self.cfg=cfg;self.db=db;self.session=None;self.blocked=set();self.lock=asyncio.Lock()
        self.counter=int(db.get('provider_cursor','0'));self.last_call={}
    async def __aenter__(self):
        self.session=aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=35),trust_env=False);return self
    async def __aexit__(self,*a):await self.session.close()
    def available(self):
        return [p for p in self.cfg['search']['providers'] if p not in self.blocked and
                (os.getenv(KEYS.get(p,''),'').strip() if p!='searxng' else os.getenv('SEARXNG_URL','').strip())]
    def reserve(self,provider,units):
        limit=self.cfg['search']['limits'].get(provider,{'period':'month','units':0})
        good=self.db.reserve(provider,units,int(limit['units']),limit['period'])
        if not good:self.db.event(f'{provider}: local quota reached; skipped','warning')
        return good
    async def request(self,method,url,**kwargs):
        # API endpoints are fixed / operator-configured, never taken from untrusted page content.
        async with self.session.request(method,url,allow_redirects=False,**kwargs) as r:
            if r.status>=300:raise RuntimeError(f'API HTTP {r.status}')
            if int(r.headers.get('Content-Length','0') or 0)>3000000:raise RuntimeError('Oversized API response')
            raw=await read_limited(r.content,3000000)
            return json.loads(raw)
    async def search(self,query):
        async with self.lock:
            providers=self.available()
            if not providers:return []
            start=self.counter%len(providers);self.counter+=1;self.db.put('provider_cursor',self.counter)
            ordered=providers[start:]+providers[:start]
            for provider in ordered:
                cached=self.db.get_cache(provider,query,self.cfg['search']['cache_days'])
                if cached is not None:return cached
                units=2 if provider=='firecrawl' else 1
                if not self.reserve(provider,units):continue
                # Conservative: reserve even for failed / timed-out calls; never blind retry a billable request.
                try:
                    import time
                    interval=6.2 if provider=='firecrawl' else 1.2
                    await asyncio.sleep(max(0,interval+self.last_call.get(provider,0)-time.monotonic()))
                    self.last_call[provider]=time.monotonic()
                    results=await self._search(provider,query)
                    self.db.cache(provider,query,results)
                    self.db.event(f'{provider}: {len(results)} results for {query[:130]}')
                    return results
                except (aiohttp.ClientError,asyncio.TimeoutError,RuntimeError,ValueError,KeyError,TypeError) as e:
                    # Never log keys, response bodies, or full authenticated request URLs.
                    self.db.event(f'{provider}: {type(e).__name__}; disabled for this run','warning');self.blocked.add(provider)
            return []
    async def _search(self,provider,query):
        n=self.cfg['search']['results_per_query'];key=os.getenv(KEYS.get(provider,''),'')
        if provider=='tavily':
            data=await self.request('POST','https://api.tavily.com/search',headers={'Authorization':'Bearer '+key},json={
                'query':query,'search_depth':'basic','max_results':n,'include_answer':False,'include_raw_content':False,'auto_parameters':False})
            rows=data.get('results',[]);keys=('url','title','content')
        elif provider=='brave':
            data=await self.request('GET','https://api.search.brave.com/res/v1/web/search',headers={'X-Subscription-Token':key},params={'q':query,'count':n})
            rows=data.get('web',{}).get('results',[]);keys=('url','title','description')
        elif provider=='serper':
            data=await self.request('POST','https://google.serper.dev/search',headers={'X-API-KEY':key},json={'q':query,'num':n})
            rows=data.get('organic',[]);keys=('link','title','snippet')
        elif provider=='firecrawl':
            data=await self.request('POST','https://api.firecrawl.dev/v2/search',headers={'Authorization':'Bearer '+key},json={'query':query,'limit':n,'sources':['web']})
            rows=data.get('data',{}).get('web',[]);keys=('url','title','description')
        elif provider=='searxng':
            base=os.environ['SEARXNG_URL'].rstrip('/')
            p=urlsplit(base)
            if p.scheme not in {'http','https'} or not p.hostname or p.username or p.password:raise ValueError('Invalid SearXNG URL')
            data=await self.request('GET',base+'/search',params={'q':query,'format':'json','categories':'general'})
            rows=data.get('results',[])[:n];keys=('url','title','content')
        else:return []
        results=[]
        for r in rows:
            try:url=normalize_url(r.get(keys[0],''))
            except ValueError:continue
            results.append({'url':url,'title':str(r.get(keys[1],''))[:250],'snippet':str(r.get(keys[2],''))[:600],'provider':provider,'query':query})
        return results
    async def hunter(self,domain):
        if not self.cfg['hunter']['enabled'] or not os.getenv('HUNTER_API_KEY') or 'hunter' in self.blocked:return []
        cached=self.db.get_cache('hunter',domain,30)
        if cached is None:
            # Unified plans can charge per revealed email. Reserve the maximum 10, not one domain call.
            if not self.reserve('hunter',10):return []
            try:
                data=await self.request('GET','https://api.hunter.io/v2/domain-search',headers={'X-API-KEY':os.environ['HUNTER_API_KEY']},params={
                    'domain':domain,'limit':10,'type':'generic'})
                cached=data.get('data',{}).get('emails',[])
                self.db.cache('hunter',domain,cached)
            except (aiohttp.ClientError,asyncio.TimeoutError,RuntimeError,ValueError):
                self.blocked.add('hunter');self.db.event('hunter: request failed; disabled for this run','warning');return []
        out=[]
        for r in cached:
            em=normalized_email(r.get('value',''))
            if not em or r.get('type')!='generic':continue
            for src in r.get('sources',[])[:2]:
                uri=src.get('uri','')
                if uri and not uri.startswith(('http://','https://')):uri='https://'+uri
                try:uri=normalize_url(uri)
                except ValueError:continue
                c=Contact('email',em,uri,'Hunter source-backed generic email; live source not yet confirmed.','hunter_domain_search',purpose(em,'',uri),association='external_source_unconfirmed',contact_url='mailto:'+em)
                c.notes+=['Hunter source date: '+str(src.get('last_seen_on','unknown')),'Must re-fetch source and observe exact address before promotion to READY.']
                out.append(c)
        return out
    async def commoncrawl_paths(self,domain):
        if not self.cfg['crawl']['commoncrawl']:return []
        cached=self.db.get_cache('commoncrawl',domain,30)
        if cached is not None:return cached
        # Known-domain path recovery only. Not a full-text web search and no archive contacts are imported.
        try:
            await asyncio.sleep(2)
            indexes=await self.request('GET','https://index.commoncrawl.org/collinfo.json')
            endpoint=indexes[0]['cdx-api']
            if not endpoint.startswith('https://index.commoncrawl.org/'):return []
            async with self.session.get(endpoint,params=[('url',domain+'/*'),('output','json'),('filter','status:200'),('filter','url:.*(contact|advertis|about|support).*'),('collapse','urlkey'),('limit','20')],allow_redirects=False) as r:
                if r.status!=200:return []
                raw=await read_limited(r.content,200000)
            urls=[]
            for line in raw.decode().splitlines():
                url=normalize_url(json.loads(line)['url'])
                if within_site(url,'https://'+domain):urls.append(url)
            self.db.cache('commoncrawl',domain,urls[:10]);return urls[:10]
        except (aiohttp.ClientError,asyncio.TimeoutError,ValueError,KeyError,IndexError,RuntimeError):return []
