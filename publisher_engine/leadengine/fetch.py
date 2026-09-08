from __future__ import annotations
import asyncio,hashlib,ipaddress,socket,time
from urllib.parse import urlsplit,urljoin
from urllib.robotparser import RobotFileParser
from dataclasses import dataclass
import aiohttp
from aiohttp.abc import AbstractResolver
from .models import Page
from .urls import normalize_url,within_site

class PublicResolver(AbstractResolver):
    """Validate the actual IPs supplied to the connector, not a separate preflight lookup."""
    def __init__(self):self.delegate=aiohttp.resolver.ThreadedResolver()
    async def resolve(self,host,port=0,family=socket.AF_INET):
        results=await self.delegate.resolve(host,port,family)
        if not results or any(not ipaddress.ip_address(r['host'].split('%')[0]).is_global for r in results):
            raise OSError('Blocked non-public DNS resolution')
        return results
    async def close(self):await self.delegate.close()

@dataclass
class RobotsPolicy:
    allowed: bool
    parser: RobotFileParser | None
    state: str
    delay: float=0
    sitemaps: tuple[str,...]=()

class Fetcher:
    def __init__(self,cfg):
        self.cfg=cfg;self.cc=cfg['crawl'];self.ua=cfg['user_agent']
        self.session=None;self.robots={};self.locks={};self.robots_locks={};self.last={}
    async def __aenter__(self):
        connector=aiohttp.TCPConnector(resolver=PublicResolver(),ttl_dns_cache=60,limit=20,limit_per_host=2)
        self.session=aiohttp.ClientSession(connector=connector,timeout=aiohttp.ClientTimeout(total=self.cc['request_timeout_seconds']),
            headers={'User-Agent':self.ua,'Accept':'text/html,application/xhtml+xml,text/plain;q=0.9,application/xml;q=0.8'},
            trust_env=False,cookie_jar=aiohttp.DummyCookieJar())
        return self
    async def __aexit__(self,*args):await self.session.close()
    @staticmethod
    def origin(url):
        p=urlsplit(url);return p.scheme+'://'+p.netloc
    async def pace(self,url,extra=0):
        host=urlsplit(url).netloc
        lock=self.locks.setdefault(host,asyncio.Lock())
        async with lock:
            delay=max(self.cc['delay_seconds'],extra)
            await asyncio.sleep(max(0,self.last.get(host,0)+delay-time.monotonic()))
            self.last[host]=time.monotonic()
    async def _request(self,url, *, text_mode=False, check_redirect_robots=False, allowed_root=None):
        page=Page(url=url,final_url=url);current=url;seen=set()
        try:
            for _ in range(self.cc['max_redirects']+1):
                current=normalize_url(current)
                if current in seen:page.state='redirect_loop';return page
                seen.add(current);page.final_url=current
                if allowed_root and not within_site(current,allowed_root):
                    page.state='external_redirect';page.error='Cross-site redirect requires a separate site record';return page
                delay=0
                if check_redirect_robots:
                    policy=await self.policy(current)
                    if not policy.allowed or (policy.parser and not policy.parser.can_fetch(self.ua,current)):
                        page.state='robots_denied' if policy.state=='ok' else policy.state;return page
                    delay=policy.delay
                await self.pace(current,delay)
                async with self.session.get(current,allow_redirects=False) as r:
                    page.status=r.status
                    if r.status in {301,302,303,307,308}:
                        if not r.headers.get('Location'):page.state='bad_redirect';return page
                        current=urljoin(current,r.headers['Location']);page.redirected.append(current);continue
                    if r.status in {401,403}:page.state='access_denied';return page
                    if r.status==429:page.state='rate_limited';return page
                    if r.status>=400:page.state='http_error';return page
                    ctype=r.headers.get('Content-Type','').lower()
                    if 'attachment' in r.headers.get('Content-Disposition','').lower():
                        page.state='download_blocked';return page
                    valid=('text/html','application/xhtml+xml','text/plain')+ (('application/xml','text/xml','application/json') if text_mode else ())
                    if not any(t in ctype for t in valid):page.state='non_html';return page
                    chunks=[];size=0
                    async for chunk in r.content.iter_chunked(16384):
                        size+=len(chunk)
                        if size>self.cc['max_page_bytes']:page.state='too_large';return page
                        chunks.append(chunk)
                    raw=b''.join(chunks)
                    try:page.html=raw.decode(r.charset or 'utf-8',errors='replace')
                    except LookupError:page.html=raw.decode('utf-8',errors='replace')
                    page.content_hash=hashlib.sha256(raw).hexdigest()
                    low=page.html.lower()
                    if ('<title>just a moment' in low or 'cf-chl-' in low or
                       ('verify you are human' in low and len(raw)<60000) or '<title>attention required!' in low):
                        page.state='challenge';page.html='';return page
                    page.state='ok';return page
            page.state='too_many_redirects';return page
        except asyncio.TimeoutError:page.state='timeout';page.error='Request timed out'
        except (aiohttp.ClientError,OSError,ValueError) as e:
            page.state='network_error';page.error=type(e).__name__+': '+str(e)[:300]
        return page
    async def policy(self,url):
        origin=self.origin(url)
        if origin in self.robots:return self.robots[origin]
        async with self.robots_locks.setdefault(origin,asyncio.Lock()):
            if origin in self.robots:return self.robots[origin]
            p=await self._request(origin+'/robots.txt',text_mode=True)
            if p.status in {404,410}:out=RobotsPolicy(True,None,'ok')
            elif p.state=='ok' and not p.html.lstrip().lower().startswith(('<!doctype html','<html')):
                parser=RobotFileParser();parser.set_url(origin+'/robots.txt');parser.parse(p.html.splitlines())
                delay=parser.crawl_delay(self.ua) or parser.crawl_delay('*') or 0
                out=RobotsPolicy(delay<=60,parser,'ok' if delay<=60 else 'robots_delay_deferred',float(delay),tuple(parser.site_maps() or ()))
            elif p.status in {401,403}:out=RobotsPolicy(False,None,'robots_denied')
            else:out=RobotsPolicy(False,None,'robots_unavailable')
            self.robots[origin]=out;return out
    async def fetch(self,url,*,text_mode=False,allowed_root=None):
        try:url=normalize_url(url)
        except ValueError as e:return Page(url=url,state='unsafe_url',error=str(e))
        return await self._request(url,text_mode=text_mode,check_redirect_robots=True,allowed_root=allowed_root)
