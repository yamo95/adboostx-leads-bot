"""Majestic Million (CC BY 3.0) URL candidates; never contact evidence.
Reservation is persisted BEFORE downloading to honour one request per 24 hours.
Existing publisher-desk-production concurrency serializes all cache writers.
Repository credentials are used only for the cache, never the public dataset.
"""
from __future__ import annotations
import asyncio
import base64
import csv
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import scan

SOURCE='https://downloads.majestic.com/majestic_million.csv'
ATTRIBUTION='Domain candidates derived from Majestic Million by Majestic 12, CC BY 3.0. Ranking is not publisher-fit or contact verification.'
LICENSE='https://creativecommons.org/licenses/by/3.0/'
CACHE_PATH='private-b219-results/discovery/majestic-candidates.json'
LOCAL=Path(__file__).with_name('catalog-candidates.json')
MAX_BYTES=130_000_000
MAX_CANDIDATES=2200
HINT=re.compile(r'apk|(?:^|[-.])mods?(?:[-.]|$)|modapk|modded|(?:123|f|9|yes|hd|put)movies|movierulz|tamil.*movie|movie.*(?:free|watch|hd)|(?:watch|free|hd).*movie|flix|sport.*stream|stream.*sport|cricket.*live|soccer.*stream|repack',re.I)
EXCLUDE=re.compile(r'porn|xxx|casino|betting|iptv|netflix|hulu|disney|hbo|amazon|appbrain|code-project|modsecurity|nexusmods',re.I)
DOMAIN=re.compile(r'(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,24}$')

def selected_domain(raw):
    domain=raw.strip().lower().removeprefix('www.')
    if not DOMAIN.fullmatch(domain) or EXCLUDE.search(domain) or not HINT.search(domain):return None
    try:return scan.safe_url('https://'+domain+'/')
    except ValueError:return None

class CandidateReader:
    def __init__(self):
        self.pending=b'';self.size=0;self.lines=0;self.header=None;self.urls=[];self.seen=set()
    def feed(self,chunk,final=False):
        self.size+=len(chunk)
        if self.size>MAX_BYTES:raise ValueError('CATALOG_SIZE')
        parts=(self.pending+chunk).split(b'\n');self.pending=parts.pop()
        if len(self.pending)>4096:raise ValueError('CATALOG_LINE_SIZE')
        if final and self.pending:parts.append(self.pending);self.pending=b''
        for raw in parts:
            if len(raw)>4096:raise ValueError('CATALOG_LINE_SIZE')
            line=raw.decode('utf-8-sig' if self.header is None else 'utf-8',errors='strict').strip()
            if not line:continue
            self.lines+=1
            if self.lines>1_000_001:raise ValueError('CATALOG_ROW_LIMIT')
            if self.header is None:
                self.header=next(csv.reader([line]))
                if not {'GlobalRank','Domain'}<=set(self.header):raise ValueError('CATALOG_HEADER')
                self.domain_index=self.header.index('Domain');self.rank_index=self.header.index('GlobalRank');continue
            if not HINT.search(line):continue
            row=next(csv.reader([line]))
            if len(row)!=len(self.header):raise ValueError('CATALOG_ROW')
            rank=int(row[self.rank_index])
            if not 1<=rank<=1_000_000:raise ValueError('CATALOG_RANK')
            url=selected_domain(row[self.domain_index])
            if url and url not in self.seen and len(self.urls)<MAX_CANDIDATES:
                self.seen.add(url);self.urls.append(url)
    def finish(self):
        self.feed(b'',True)
        if not self.header:raise ValueError('CATALOG_HEADER')
        return self.urls

def now():return datetime.now(timezone.utc)
def recent_attempt(cache,at=None):
    try:
        age=((at or now())-datetime.fromisoformat(cache['last_attempt_at'])).total_seconds()
        return age<86400
    except (KeyError,TypeError,ValueError):return False

def decode_record(record):
    if not record:return None
    value=json.loads(base64.b64decode(record['content']))
    if value.get('format')!=1 or value.get('source')!=SOURCE or not isinstance(value.get('urls'),list):raise ValueError('CACHE_FORMAT')
    if len(value['urls'])>MAX_CANDIDATES or any(selected_domain(u.removeprefix('https://').removesuffix('/'))!=u for u in value['urls']):raise ValueError('CACHE_URL')
    return value

def store(value,previous):
    body={'branch':'main','message':'Cache attributed public discovery candidates, not contacts','content':base64.b64encode(json.dumps(value,indent=2).encode()).decode()}
    if previous:body['sha']=previous['sha']
    scan.gh('PUT','contents/'+CACHE_PATH,body)

async def download():
    reader=CandidateReader()
    async with scan.Fetcher() as fetcher:
        allowed,policy,delay=await fetcher.policy(SOURCE)
        if not allowed or policy and not policy.can_fetch(scan.UA,SOURCE):raise ValueError('robots_denied_or_unavailable')
        await fetcher.pace(SOURCE,max(delay,2.0))
        async with fetcher.session.get(SOURCE,allow_redirects=False,timeout=scan.aiohttp.ClientTimeout(total=90),headers={'Accept':'text/csv,text/plain,application/octet-stream'}) as response:
            if response.status!=200:raise ValueError('http_'+str(response.status))
            if any(x in response.headers.get('Content-Type','').lower() for x in ['text/html','javascript']):raise ValueError('CATALOG_TYPE')
            async for chunk in response.content.iter_chunked(65536):reader.feed(chunk)
    return reader.finish(),{'rows_read':reader.lines-1,'bytes_read':reader.size}

def prepare():
    previous=scan.gh('GET','contents/'+CACHE_PATH+'?ref=main')
    cache=decode_record(previous)
    if not recent_attempt(cache or {}):
        stamp=now().isoformat()
        cache=cache or {'format':1,'source':SOURCE,'attribution':ATTRIBUTION,'license':LICENSE,'urls':[]}
        cache=dict(cache,last_attempt_at=stamp,state='reserved')
        store(cache,previous)
        try:
            urls,metrics=asyncio.run(download())
            cache.update(urls=urls,state='results' if urls else 'no_results',downloaded_at=stamp,metrics=metrics)
        except Exception as error:
            cache.update(state='cached_stale' if cache['urls'] else str(error)[:80],error=type(error).__name__)
        current=scan.gh('GET','contents/'+CACHE_PATH+'?ref=main')
        store(cache,current)
    LOCAL.write_text(json.dumps(cache),encoding='utf-8')
    print(json.dumps({'discovery_provider':'Majestic Million','state':cache['state'],'candidate_urls':len(cache['urls']),'last_attempt_at':cache['last_attempt_at'],'contact_imports':0}))
    return 0

if __name__=='__main__':
    try:raise SystemExit(prepare())
    except Exception as error:
        LOCAL.write_text(json.dumps({'format':1,'source':SOURCE,'urls':[],'state':'cache_preparation_failed','attribution':ATTRIBUTION,'license':LICENSE}))
        print(json.dumps({'discovery_provider':'Majestic Million','state':'cache_preparation_failed','error_type':type(error).__name__,'contact_imports':0}))
