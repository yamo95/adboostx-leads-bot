from __future__ import annotations
import os,json,asyncio,secrets
from pathlib import Path
from contextlib import asynccontextmanager
from fastapi import FastAPI,HTTPException,Request,Depends
from fastapi.responses import HTMLResponse,Response,JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware
from pydantic import BaseModel,Field
from dotenv import set_key
from .engine import Engine
from .urls import hostname,normalize_url
from .export import lead_rows,effective_contacts,csv_text,LEAD_FIELDS,CONTACT_FIELDS
from .providers import KEYS
from .scheduler import scheduler_loop

class SiteInput(BaseModel):urls: list[str]=Field(min_length=1,max_length=200)
class RunInput(BaseModel):
    discover: bool=True
    force: bool=False
    only: list[str] | None=Field(default=None,max_length=100)
    limit: int | None=Field(default=None,ge=1,le=500)
class OverrideInput(BaseModel):
    decision: str | None=None
    reason: str=Field(default='',max_length=500)
class ToggleInput(BaseModel):enabled: bool=True
class SettingsInput(BaseModel):
    keys: dict[str,str]=Field(default_factory=dict)


def create_app(cfg=None):
    engine=Engine(cfg)
    @asynccontextmanager
    async def lifespan(app):
        app.state.scheduler=asyncio.create_task(scheduler_loop(app))
        yield
        app.state.scheduler.cancel()
        if app.state.job and not app.state.job.done():app.state.job.cancel()
        await asyncio.gather(app.state.scheduler,*([app.state.job] if app.state.job else []),return_exceptions=True)
    app=FastAPI(title='Publisher Lead Engine',version='1.0.0',lifespan=lifespan,docs_url=None,redoc_url=None,openapi_url=None)
    app.state.engine=engine;app.state.job=None;app.state.job_error=None
    hosts=['localhost','127.0.0.1','[::1]']+[x.strip() for x in os.getenv('TRUSTED_HOSTS','').split(',') if x.strip()]
    app.add_middleware(TrustedHostMiddleware,allowed_hosts=hosts)
    async def do_run(**kwargs):
        app.state.job_error=None
        try:return await engine.run(**kwargs)
        except Exception as e:
            app.state.job_error=str(e)[:200];engine.db.event('Run failed: '+type(e).__name__,'error');return None
    app.state.do_run=do_run
    @app.middleware('http')
    async def safety_headers(request,call_next):
        if request.method in {'POST','PUT','PATCH','DELETE'}:
            if request.headers.get('x-leadengine-client')!='dashboard':return JSONResponse({'detail':'Required client header missing'},status_code=403)
            length=request.headers.get('content-length','0')
            if not length.isdigit() or int(length)>100000:return JSONResponse({'detail':'Request too large'},status_code=413)
        response=await call_next(request)
        response.headers['Content-Security-Policy']="default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'"
        response.headers['X-Content-Type-Options']='nosniff'
        response.headers['Referrer-Policy']='no-referrer'
        response.headers['Cache-Control']='no-store'
        return response
    async def auth(request:Request):
        expected=os.getenv('DASHBOARD_TOKEN','')
        if expected:
            actual=request.headers.get('authorization','').removeprefix('Bearer ')
            if not secrets.compare_digest(actual,expected):raise HTTPException(401,'Dashboard token required')
    dep=[Depends(auth)]
    static=Path(__file__).parent/'static'
    app.mount('/static',StaticFiles(directory=str(static)),name='static')
    @app.get('/',response_class=HTMLResponse)
    async def home():return (static/'index.html').read_text(encoding='utf-8')
    @app.get('/api/status',dependencies=dep)
    async def status():
        leads=lead_rows(engine.db,engine.cfg)
        job=app.state.job
        return {'running':bool(job and not job.done()),'error':app.state.job_error,
                'counts':{'sites':len(leads),'relevant':sum(x['effective_classification']=='PASS' for x in leads),
                          'ready':sum(x['contact_state']=='READY' and x['effective_classification']=='PASS' for x in leads),
                          'review':sum(x['effective_classification']=='REVIEW' or x['contact_state'] in {'REVIEW','REVIEW_SITE','COMMUNITY_ONLY'} for x in leads)},
                'schedule':engine.cfg['schedule'],'providers':{p:bool(os.getenv(k)) for p,k in KEYS.items()},
                'usage':engine.db.rows('SELECT * FROM usage ORDER BY provider,period'),
                'runs':engine.db.rows('SELECT * FROM runs ORDER BY id DESC LIMIT 10')}
    @app.get('/api/leads',dependencies=dep)
    async def leads(state:str='',q:str='',offset:int=0,limit:int=100):
        rows=lead_rows(engine.db,engine.cfg)
        if state:rows=[r for r in rows if r['contact_state']==state or r['effective_classification']==state]
        if q:rows=[r for r in rows if q.lower() in (r['domain']+' '+(r['category'] or '')+' '+str(r['best_contact'])).lower()]
        offset=max(0,offset);limit=max(1,min(500,limit))
        return {'total':len(rows),'rows':rows[offset:offset+limit]}
    @app.get('/api/sites/{domain}',dependencies=dep)
    async def detail(domain:str):
        rows=engine.db.rows('SELECT * FROM sites WHERE domain=?',(domain,))
        if not rows:raise HTTPException(404,'Unknown site')
        return {'site':rows[0],'contacts':[c for c in effective_contacts(engine.db,engine.cfg) if c['domain']==domain],
                'pages':engine.db.rows('SELECT * FROM pages WHERE domain=? ORDER BY id DESC LIMIT 40',(domain,))}
    @app.post('/api/sites',dependencies=dep)
    async def add(body:SiteInput):
        added=0;errors=[]
        for url in body.urls:
            try:added+=engine.db.add_site(url,'dashboard')
            except ValueError as e:errors.append({'url':url,'error':str(e)})
        return {'added':added,'errors':errors}
    @app.post('/api/run',dependencies=dep)
    async def run(body:RunInput):
        if app.state.job and not app.state.job.done():raise HTTPException(409,'A run is already active')
        if body.only:
            for url in body.only:
                try:normalize_url(url)
                except ValueError:raise HTTPException(400,'Invalid target URL')
        app.state.job=asyncio.create_task(do_run(**body.model_dump()))
        return {'state':'started'}
    @app.post('/api/sites/{domain}/override',dependencies=dep)
    async def override(domain:str,body:OverrideInput):
        if body.decision not in {'PASS','REJECT',None}:raise HTTPException(400,'Use PASS, REJECT, or null')
        if not engine.db.set_override(domain,body.decision,body.reason):raise HTTPException(404,'Unknown site')
        return {'saved':True}
    @app.post('/api/sites/{domain}/suppress',dependencies=dep)
    async def suppress(domain:str,body:ToggleInput):
        if not engine.db.suppress(domain,body.enabled):raise HTTPException(404,'Unknown site')
        return {'saved':True}
    @app.delete('/api/sites/{domain}',dependencies=dep)
    async def purge(domain:str):engine.db.purge(domain);return {'purged':True,'rediscovery':'suppressed'}
    @app.get('/api/export/{kind}',dependencies=dep)
    async def export(kind:str):
        if kind not in {'leads','contacts','ready'}:raise HTTPException(404,'Unknown export')
        rows=effective_contacts(engine.db,engine.cfg) if kind=='contacts' else lead_rows(engine.db,engine.cfg)
        if kind=='ready':rows=[r for r in rows if r['effective_classification']=='PASS' and r['contact_state']=='READY']
        return Response(csv_text(rows,CONTACT_FIELDS if kind=='contacts' else LEAD_FIELDS),media_type='text/csv',headers={'Content-Disposition':f'attachment; filename="{kind}.csv"'})
    @app.get('/api/events',dependencies=dep)
    async def events():return engine.db.rows('SELECT * FROM events ORDER BY id DESC LIMIT 70')
    @app.post('/api/settings/keys',dependencies=dep)
    async def settings(body:SettingsInput):
        if app.state.job and not app.state.job.done():raise HTTPException(409,'Wait for the current run to finish before changing keys')
        allowed=set(KEYS.values())|{'SEARXNG_URL'}
        for key,val in body.keys.items():
            if key not in allowed or len(val)>2000 or any(ord(c)<32 for c in val):raise HTTPException(400,'Invalid settings')
        path=Path(engine.cfg['data_dir'])/'keys.env';path.touch(mode=0o600,exist_ok=True)
        for key,val in body.keys.items():set_key(str(path),key,val.strip());os.environ[key]=val.strip()
        try:path.chmod(0o600)
        except OSError:pass
        return {'saved':list(body.keys)}
    @app.post('/api/sheets/sync',dependencies=dep)
    async def sheets_sync():
        try:
            from .sheets import sync_sheets
            return await asyncio.to_thread(sync_sheets,engine.db,engine.cfg)
        except Exception as e:raise HTTPException(400,'Sheets sync failed ('+type(e).__name__+'); check setup in README')
    return app
