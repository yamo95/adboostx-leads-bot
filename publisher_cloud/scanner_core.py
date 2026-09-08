"""Keyless cloud companion to the local Publisher Lead Engine.

No outreach, authentication to publishers, downloads, CAPTCHA bypass, search-engine
scraping, or private-group access. Public repository outputs are encrypted before
upload. The decryption key never enters the runner. Each run is a fresh snapshot;
the private viewer merges snapshots. This is not unlimited whole-web discovery.
"""
from __future__ import annotations
import argparse
import asyncio
import base64
from collections import Counter
import csv
from datetime import datetime, timezone
import hashlib
import io
import ipaddress
import json
import os
from pathlib import Path
import re
import socket
import time
from urllib.parse import urlsplit, urlunsplit, urljoin, parse_qs, quote
from urllib.robotparser import RobotFileParser
import urllib.request
import urllib.error
from zoneinfo import ZoneInfo
import aiohttp
from aiohttp.abc import AbstractResolver
from bs4 import BeautifulSoup, Comment
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

ROOT = Path(__file__).resolve().parent
UA = 'PublisherContactResearch/1.2 (+public-business-contact-research)'
AAD = b'PublisherLeadEngineEncrypted/v1'
FORMAT = 'publisher-leads-rsa-oaep-aesgcm-v1'
BIN = re.compile(r'\.(?:apk|xapk|apks|exe|msi|dmg|zip|rar|7z|tar|gz|torrent|mp4|m3u8|mp3|avi|mkv|pdf|png|jpe?g|webp|svg|gif|woff2?|ttf|js|css)$', re.I)
TG_HOSTS = {'t.me', 'telegram.me', 'telegram.dog'}
SOCIAL = TG_HOSTS | {'wa.me','wa.link','api.whatsapp.com','web.whatsapp.com','chat.whatsapp.com','whatsapp.com','facebook.com','instagram.com','youtube.com','x.com','twitter.com','reddit.com','github.com','play.google.com','apps.apple.com','google.com','bing.com','cloudflare.com','ad-maven.com','admaven.com'}
CONTACT_PATH = re.compile(r'contact|advertis|partner|about|support|faq|help|contato|contacto|kontak|reklam', re.I)
BUSINESS = re.compile(r'advertis|partnership|business|cooperation|paid\s+promo|contact\s+owner|contact\s+admin|\bowner\b|marketing|reklam|publicit|\u0440\u0435\u043a\u043b\u0430\u043c', re.I)
LEGAL = re.compile(r'dmca|copyright\s+(?:claim|complaint)|abuse@|privacy@|noreply|no-reply|legal@', re.I)
SEO = re.compile(r'guest\s+post|niche\s+edit|backlink|link\s+insertion', re.I)
HANDLE = re.compile(r'(?<![\w@])@([A-Za-z][A-Za-z0-9_]{2,31})\b')
MAIL = re.compile(r'(?<![\w.+-])[A-Z0-9.!#$%&\x27*+/=?^_`{|}~-]+@[A-Z0-9](?:[A-Z0-9.-]*[A-Z0-9])?\.[A-Z]{2,24}', re.I)
COMMON = ['/contact','/contact-us','/contact-us/','/pages/contact-us','/pages/contactus','/advertise','/faqs/']


def stamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def clean(value: str) -> str:
    return re.sub(r'\s+', ' ', value).strip()


def host(value: str) -> str:
    h = (urlsplit(value).hostname or '').lower().rstrip('.')
    return h[4:] if h.startswith('www.') else h


def safe_url(value: str) -> str:
    if not isinstance(value, str) or len(value) > 2048 or '\\' in value or any(ord(c) < 32 for c in value):
        raise ValueError('Invalid URL')
    p = urlsplit(value.strip())
    if p.scheme not in {'https','http'} or not p.hostname or p.username or p.password or p.port not in {None,80,443}:
        raise ValueError('Public HTTP(S) URLs only')
    h = p.hostname.lower().rstrip('.')
    if '.' not in h or h in {'localhost','metadata.google.internal'} or h.endswith(('.local','.internal','.localhost','.test','.invalid')):
        raise ValueError('Private or invalid host')
    try:
        address = ipaddress.ip_address(h)
    except ValueError:
        if re.fullmatch(r'[0-9.]+', h):
            raise ValueError('Invalid numeric host')
    else:
        if not address.is_global:
            raise ValueError('Non-public IP')
    if BIN.search(p.path):
        raise ValueError('Binary or media path')
    return urlunsplit((p.scheme, p.netloc, p.path or '/', p.query, ''))


def same_site(url: str, base: str) -> bool:
    h, b = host(url), host(base)
    return bool(h and b and (h == b or h.endswith('.' + b)))


def origin(url: str) -> str:
    p = urlsplit(url)
    return p.scheme + '://' + p.netloc


class PublicResolver(AbstractResolver):
    def __init__(self):
        self.delegate = aiohttp.resolver.ThreadedResolver()
    async def resolve(self, name, port=0, family=socket.AF_INET):
        records = await self.delegate.resolve(name, port, family)
        if not records or any(not ipaddress.ip_address(r['host'].split('%')[0]).is_global for r in records):
            raise OSError('Non-public DNS resolution blocked')
        return records
    async def close(self):
        await self.delegate.close()


class Fetcher:
    def __init__(self):
        self.policies, self.policy_locks, self.last, self.locks = {}, {}, {}, {}
        self.pages = []
    async def __aenter__(self):
        self.session = aiohttp.ClientSession(connector=aiohttp.TCPConnector(resolver=PublicResolver(), limit=12, limit_per_host=2),
            timeout=aiohttp.ClientTimeout(total=15), cookie_jar=aiohttp.DummyCookieJar(), trust_env=False,
            headers={'User-Agent':UA, 'Accept':'text/html,text/plain;q=0.8,application/xhtml+xml;q=0.8'})
        return self
    async def __aexit__(self, *args):
        await self.session.close()
    async def pace(self, url, delay=1.5):
        h = host(url)
        async with self.locks.setdefault(h, asyncio.Lock()):
            await asyncio.sleep(max(0, self.last.get(h, 0) + delay - time.monotonic()))
            self.last[h] = time.monotonic()
    async def policy(self, url):
        root = origin(url)
        async with self.policy_locks.setdefault(root, asyncio.Lock()):
            if root in self.policies:
                return self.policies[root]
            page = await self.get(root + '/robots.txt', robots=False, record=False)
            parser, delay = None, 1.5
            if page['status'] in {404,410}:
                allowed = True
            elif page['state'] == 'ok' and not page['html'].lstrip().lower().startswith(('<html','<!doctype')):
                parser = RobotFileParser()
                parser.parse(page['html'].splitlines())
                delay = max(1.5, float(parser.crawl_delay(UA) or parser.crawl_delay('*') or 0))
                allowed = delay <= 30
            else:
                allowed = False
            self.policies[root] = (allowed, parser, delay)
            return self.policies[root]
    async def get(self, url, *, robots=True, record=True, site=None):
        result = {'url':url, 'final_url':url, 'status':0, 'state':'error', 'html':'', 'at':stamp()}
        seen = set()
        try:
            for _ in range(6):
                url = safe_url(url)
                if url in seen:
                    result['state'] = 'redirect_loop'; break
                seen.add(url); result['final_url'] = url
                if site and not same_site(url, site):
                    result['state'] = 'cross_site_redirect'; break
                delay = 1.5
                if robots:
                    allowed, parser, delay = await self.policy(url)
                    if not allowed or (parser and not parser.can_fetch(UA, url)):
                        result['state'] = 'robots_denied_or_unavailable'; break
                await self.pace(url, delay)
                async with self.session.get(url, allow_redirects=False) as response:
                    result['status'] = response.status
                    if response.status in {301,302,303,307,308}:
                        location = response.headers.get('Location')
                        if not location:
                            result['state'] = 'invalid_redirect'; break
                        url = urljoin(url, location); continue
                    if response.status >= 400:
                        result['state'] = 'http_' + str(response.status); break
                    content_type = response.headers.get('Content-Type','').lower()
                    if 'attachment' in response.headers.get('Content-Disposition','').lower() or not any(t in content_type for t in ('text/html','text/plain','application/xhtml+xml')):
                        result['state'] = 'non_html'; break
                    data = bytearray()
                    async for chunk in response.content.iter_chunked(16384):
                        data.extend(chunk)
                        if len(data) > 1500000:
                            result['state'] = 'too_large'; break
                    if result['state'] == 'too_large': break
                    try: text = data.decode(response.charset or 'utf-8', errors='replace')
                    except LookupError: text = data.decode('utf-8', errors='replace')
                    low = text.lower()
                    if '<title>just a moment' in low or 'cf-chl-' in low or ('verify you are human' in low and len(text) < 60000):
                        result['state'] = 'challenge'; break
                    result.update(state='ok', html=text); break
            else:
                result['state'] = 'too_many_redirects'
        except (aiohttp.ClientError, OSError, ValueError, asyncio.TimeoutError) as error:
            result['state'] = type(error).__name__
        if record:
            self.pages.append({k:v for k,v in result.items() if k != 'html'})
        return result


def role(context: str, source: str) -> str:
    if LEGAL.search(context): return 'legal'
    if SEO.search(context): return 'seo_service'
    if BUSINESS.search(context): return 'business'
    if re.search(r'support|help|assistan', context, re.I): return 'support'
    if re.search(r'contact|reach\s+us|contato|contacto|kontak', context + ' ' + urlsplit(source).path, re.I): return 'contact'
    return 'unknown'


def phone(value: str) -> str | None:
    value = re.sub(r'[\s().-]', '', value)
    if re.fullmatch(r'\+?[1-9][0-9]{7,14}', value):
        digits = value.lstrip('+')
        if len(set(digits)) > 2 and digits not in {'1234567890','12345678901','123456789012'}:
            return '+' + digits
    return None


def route(raw: str, context: str, source: str) -> dict | None:
    raw = raw.strip()
    try: p = urlsplit(raw)
    except ValueError: return None
    h, parts = (p.hostname or '').lower(), p.path.strip('/').split('/')
    item = {'channel':'', 'contact':'', 'contact_url':'', 'role':role(context,source), 'profile_type':'unverified',
            'source_url':source, 'via':'', 'evidence':clean(context)[:350], 'observed_at':stamp(), 'notes':''}
    if p.scheme == 'mailto':
        address = p.path.split('?')[0]
        if not MAIL.fullmatch(address) or address.lower().endswith(('@example.com','@domain.com','@test.com')): return None
        item.update(channel='email', contact=address, contact_url='mailto:' + address)
    elif h in TG_HOSTS:
        if parts[0] == 's' and len(parts) == 2: parts = parts[1:]
        if parts[0] in {'share','proxy','socks','login','c','iv','addstickers','addemoji'}: return None
        if parts[0].startswith('+') or parts[0] == 'joinchat':
            item.update(channel='telegram', contact=raw, contact_url=raw, profile_type='community')
        elif len(parts) == 2 and parts[0] == 'm':
            item.update(channel='telegram', contact=raw, contact_url=raw, profile_type='short_link_unresolved')
        elif len(parts) == 1 and re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{2,31}', parts[0]):
            value = 'https://t.me/' + parts[0]
            kind = 'bot' if parts[0].lower().endswith('bot') else 'unverified'
            item.update(channel='telegram', contact='@'+parts[0], contact_url=value, profile_type=kind)
        else: return None
    elif h in {'wa.me','api.whatsapp.com','web.whatsapp.com'} or p.scheme == 'whatsapp':
        value = parts[0] if h == 'wa.me' and len(parts) == 1 else parse_qs(p.query).get('phone',[''])[0]
        number = phone(value)
        if number:
            item.update(channel='whatsapp', contact=number, contact_url='https://wa.me/'+number[1:])
        elif h == 'wa.me' and len(parts) == 2 and parts[0] == 'message' and re.fullmatch(r'[A-Za-z0-9]+',parts[1]):
            item.update(channel='whatsapp', contact=raw, contact_url=raw, profile_type='short_link_unresolved')
        else: return None
    elif h == 'wa.link' and len(parts) == 1 and re.fullmatch(r'[A-Za-z0-9]{4,20}',parts[0]):
        item.update(channel='whatsapp', contact=raw, contact_url=raw, profile_type='short_link_unresolved')
    elif h in {'chat.whatsapp.com','whatsapp.com'}:
        item.update(channel='whatsapp', contact=raw, contact_url=raw, profile_type='community')
    else: return None
    return item


def parse(html: str, source: str) -> tuple[list[dict],list[tuple[str,str]],str]:
    soup = BeautifulSoup(html, 'html.parser')
    for element in soup(['script','style','form','noscript','template','svg']): element.decompose()
    for element in soup.select('[hidden],[aria-hidden="true"]'): element.decompose()
    for comment in soup.find_all(string=lambda s:isinstance(s, Comment)): comment.extract()
    contacts, links = [], []
    for anchor in soup.select('a[href]'):
        raw = urljoin(source, anchor.get('href','').strip())
        label = clean(anchor.get_text(' ',strip=True))
        parent = anchor.find_parent(['p','li','td'])
        context = clean(parent.get_text(' ',strip=True))[:500] if parent else label
        if not context: context = clean(anchor.get('title','') + ' ' + anchor.get('aria-label',''))
        found = route(raw, context, source)
        if found: contacts.append(found)
        try: links.append((safe_url(raw),label))
        except ValueError: pass
    for tag in soup.select('[data-cfemail]'):
        try:
            raw = bytes.fromhex(tag.get('data-cfemail',''))
            address = ''.join(chr(b ^ raw[0]) for b in raw[1:])
            found = route('mailto:'+address,'Published contact',source)
            if found: contacts.append(found)
        except (ValueError,IndexError): pass
    text = soup.get_text('\n',strip=True)
    for line in text.splitlines():
        line = clean(line)
        if len(line) > 600: continue
        for address in MAIL.findall(line):
            found = route('mailto:'+address,line,source)
            if found: contacts.append(found)
        if re.search(r'whats\s*app',line,re.I):
            for candidate in re.findall(r'\+[1-9][0-9\s().-]{7,22}[0-9]',line):
                number = phone(candidate)
                if number:
                    found = route('https://wa.me/'+number[1:],line,source)
                    if found: contacts.append(found)
        if re.search(r'telegram',line,re.I):
            for handle in HANDLE.findall(line):
                found = route('https://t.me/'+handle,line,source)
                if found: contacts.append(found)
    return contacts, links, clean(text)[:30000]


def category(text: str, links: list[tuple[str,str]]) -> tuple[str,str]:
    t = text.lower()
    if re.search(r'\bapk\b|\bxapk\b',t) and re.search(r'download|descargar|baixar|unduh',t): return 'APK / app downloads','PASS'
    if re.search(r'\bmods?\b|modpacks?',t) and re.search(r'download|gta|minecraft|skyrim|sims',t): return 'Game mods','PASS'
    if re.search(r'shorten|short\s+links?|url\s+short',t): return 'URL shortener','PASS'
    if re.search(r'(?:file|video)\s+(?:host|stor)|upload\s+(?:your\s+)?(?:files?|videos?)',t): return 'File / video hosting','PASS'
    if re.search(r'sport|football|soccer|cricket|basketball|\bnba\b|\bufc\b',t) and re.search(r'live\s+stream|watch\s+live|live\s+match',t): return 'Sports streaming','PASS'
    if re.search(r'movie|film|series|episod',t) and re.search(r'watch\s+(?:online|now|free)|streaming|regarder|assistir',t): return 'Movies / TV streaming','PASS'
    return 'Unclassified','REVIEW'


def unique(contacts: list[dict]) -> list[dict]:
    out = {}
    order = {'business':4,'contact':3,'support':2,'unknown':1,'legal':0,'seo_service':0}
    for item in contacts:
        key = (item['channel'],item['contact'].casefold())
        if key not in out or order.get(item['role'],0) > order.get(out[key]['role'],0): out[key] = item
    return list(out.values())


async def telegram_hops(contacts: list[dict], fetcher: Fetcher) -> list[dict]:
    output = unique(contacts)
    queue = [(c,0) for c in output if c['channel']=='telegram' and c['profile_type']=='unverified']
    seen, calls = set(), 0
    while queue and calls < 6:
        item, depth = queue.pop(0)
        address = item['contact_url'].casefold()
        if address in seen: continue
        seen.add(address); calls += 1
        page = await fetcher.get(item['contact_url'],site='https://t.me/')
        if page['state'] != 'ok':
            item['notes'] += ' Telegram preview unavailable.'; continue
        soup = BeautifulSoup(page['html'],'html.parser')
        extra = soup.select_one('.tgme_page_extra')
        extra_text = clean(extra.get_text(' ',strip=True)) if extra else ''
        text = clean(soup.get_text(' ',strip=True))
        if re.search(r'subscribers|members|abonn|membres|\u043f\u043e\u0434\u043f\u0438\u0441\u0447\u0438\u043a',extra_text,re.I):
            item['profile_type'] = 'community'
            desc = soup.select_one('.tgme_page_description')
            if depth == 0 and desc:
                for br in desc.find_all('br'): br.replace_with('\n')
                for line in re.split(r'[\n|;]+',desc.get_text(' ',strip=True)):
                    if not BUSINESS.search(line) and not re.search(r'contact|support|help',line,re.I): continue
                    if re.search(r'no\s+ads|do\s+not\s+contact',line,re.I): continue
                    for handle in HANDLE.findall(line)[:4]:
                        new = route('https://t.me/'+handle,line,item['contact_url'])
                        if new and new['contact_url'].casefold() not in seen:
                            new['via'] = item['source_url']
                            new['notes'] = 'Source is the description of a site-linked public channel. Ownership is not independently verified.'
                            output.append(new)
                            if new['profile_type'] == 'unverified': queue.append((new,1))
        elif re.search(r'start bot',text,re.I) or extra_text.lower()=='bot': item['profile_type'] = 'bot'
        elif re.search(r'if you have telegram, you can contact|send message',text,re.I):
            item['profile_type'] = 'contact_preview'
            item['notes'] += ' Contact preview observed; account activity and authority unverified.'
        else: item['notes'] += ' Profile type could not be established.'
    return unique(output)


def grade(item: dict) -> str:
    if item['role'] in {'legal','seo_service'}: return 'EXCLUDE_PURPOSE'
    if item['profile_type'] in {'bot','community'}: return item['profile_type'].upper()
    if item['profile_type'] == 'short_link_unresolved': return 'REVIEW_SHORT_LINK'
    if item['role'] == 'business': return 'PUBLISHED_BUSINESS_ROUTE'
    if item['role'] in {'contact','support'}: return 'PUBLISHED_GENERAL_ROUTE'
    return 'REVIEW_ROLE'


async def scan_site(seed: str, fetcher: Fetcher) -> tuple[dict,list[dict],list[str]]:
    base = origin(seed) + '/'
    queue = [seed,base] if seed != base else [base]
    seen, all_contacts, all_links, texts, discovered = set(), [], [], [], []
    successes = 0
    async with asyncio.timeout(105):
        while queue and len(seen) < 8:
            url = queue.pop(0)
            if url in seen: continue
            seen.add(url)
            page = await fetcher.get(url,site=base)
            if page['state'] == 'cross_site_redirect':
                target = page['final_url']
                if not any(host(target)==h or host(target).endswith('.'+h) for h in SOCIAL): discovered.append(target)
            if page['state'] != 'ok': continue
            successes += 1
            found, links, text = parse(page['html'],page['final_url'])
            all_contacts.extend(found); all_links.extend(links); texts.append(text)
            preferred = [u for u,label in links if same_site(u,base) and CONTACT_PATH.search(urlsplit(u).path+' '+label) and u not in seen]
            queue = list(dict.fromkeys(preferred + queue))
            if len(seen)==1:
                queue += [urljoin(base,p) for p in COMMON]
            for u,label in links:
                if not same_site(u,base) and re.search(r'partner|sister\s+site|related\s+site|mirror|our\s+sites',label,re.I):
                    if not any(host(u)==h or host(u).endswith('.'+h) for h in SOCIAL): discovered.append(u)
        niche, fit = category(' '.join(texts),all_links)
        contacts = await telegram_hops(all_contacts,fetcher)
        for contact in contacts:
            contact.update(domain=host(base),niche=niche,site_fit=fit,quality=grade(contact))
        result = {'domain':host(base),'url':base,'niche':niche,'site_fit':fit,'html_pages_opened':successes,
                  'contact_records':len(contacts),'observed_at':stamp(),'state':'SCANNED' if successes else 'ACCESS_FAILED'}
        return result, contacts, list(dict.fromkeys(discovered))[:3]


def selected_seeds(seeds: list[str], batch: str='auto') -> list[str]:
    if batch=='all': return seeds[:36]
    if batch=='auto':
        local = datetime.now(ZoneInfo('Asia/Jerusalem'))
        batch = str((local.toordinal()*2+(0 if local.hour<15 else 1)) % max(1,(len(seeds)+11)//12))
    index = int(batch)
    if index < 0 or index*12 >= len(seeds): raise ValueError('Invalid seed batch')
    return seeds[index*12:index*12+12]


async def run(seeds: list[str]) -> tuple[list[dict],list[dict],list[dict]]:
    sites, contacts, tried = [], [], set()
    sem = asyncio.Semaphore(3)
    async with Fetcher() as fetcher:
        async def task(url):
            tried.add(host(url))
            async with sem:
                try: return await scan_site(url,fetcher)
                except (Exception,asyncio.TimeoutError) as error:
                    return ({'domain':host(url),'url':url,'site_fit':'REVIEW','niche':'Unclassified','state':'INTERRUPTED_'+type(error).__name__,'html_pages_opened':0,'observed_at':stamp()},[],[])
        first = await asyncio.gather(*(task(s) for s in seeds))
        extra = []
        for site, found, candidates in first:
            sites.append(site); contacts.extend(found)
            for candidate in candidates:
                if host(candidate) not in tried and len(extra)<6:
                    tried.add(host(candidate)); extra.append(candidate)
        if extra:
            for site,found,_ in await asyncio.gather(*(task(s) for s in extra)):
                sites.append(site); contacts.extend(found)
        return sites, contacts, fetcher.pages


def seal(payload: dict, public_bytes: bytes) -> dict:
    public = serialization.load_pem_public_key(public_bytes)
    if not isinstance(public,rsa.RSAPublicKey) or public.key_size < 3072: raise ValueError('RSA-3072 public key required')
    key, nonce = AESGCM.generate_key(bit_length=256), os.urandom(12)
    ciphertext = AESGCM(key).encrypt(nonce,json.dumps(payload,ensure_ascii=False).encode(),AAD)
    wrapped = public.encrypt(key,padding.OAEP(mgf=padding.MGF1(hashes.SHA256()),algorithm=hashes.SHA256(),label=None))
    der = public.public_bytes(serialization.Encoding.DER,serialization.PublicFormat.SubjectPublicKeyInfo)
    b64 = lambda value:base64.b64encode(value).decode('ascii')
    return {'format':FORMAT,'key_id':hashlib.sha256(der).hexdigest(),'wrapped_key':b64(wrapped),'nonce':b64(nonce),'ciphertext':b64(ciphertext)}


def csv_content(rows: list[dict], fields: list[str]) -> str:
    buf = io.StringIO(newline=''); writer = csv.DictWriter(buf,fieldnames=fields,extrasaction='ignore'); writer.writeheader()
    for row in rows:
        safe = {}
        for field in fields:
            value = row.get(field,'')
            if isinstance(value,str):
                value = value.replace('\x00','')
                if value.lstrip().startswith(('=','+','-','@')) or value.startswith(('\t','\n','\r')): value = "'"+value
            safe[field] = value
        writer.writerow(safe)
    return '\ufeff'+buf.getvalue()


def gh(method: str, endpoint: str, payload=None):
    repo = os.environ['GITHUB_REPOSITORY']
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+',repo): raise ValueError('Invalid repository')
    data = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request('https://api.github.com/repos/'+repo+'/'+endpoint,data=data,method=method,
        headers={'Authorization':'Bearer '+os.environ['GITHUB_TOKEN'],'Accept':'application/vnd.github+json','User-Agent':UA,'Content-Type':'application/json','X-GitHub-Api-Version':'2022-11-28'})
    try:
        with urllib.request.urlopen(request,timeout=30) as response: return json.load(response)
    except urllib.error.HTTPError as error:
        if error.code==404 and method=='GET': return None
        raise RuntimeError('GitHub write/read failed with HTTP '+str(error.code)) from None


def publish(envelope: dict, summary: dict) -> None:
    branch = os.environ.get('GITHUB_REF_NAME','lead-engine-activation')
    if branch not in {'main','lead-engine-activation'}: raise ValueError('Unexpected output branch')
    rid = os.environ['GITHUB_RUN_ID']+'-'+os.environ.get('GITHUB_RUN_ATTEMPT','1')
    if not re.fullmatch(r'[0-9-]+',rid): raise ValueError('Invalid run identifier')
    path = 'publisher-results/runs/'+rid+'.json'
    old = gh('GET','contents/'+path+'?ref='+quote(branch,safe=''))
    body = {'message':'Store encrypted publisher snapshot '+rid,'branch':branch,'content':base64.b64encode(json.dumps(envelope).encode()).decode()}
    if old: body['sha'] = old['sha']
    gh('PUT','contents/'+path,body)
    index_path = 'publisher-results/index.json'
    old = gh('GET','contents/'+index_path+'?ref='+quote(branch,safe=''))
    index = json.loads(base64.b64decode(old['content'])) if old else {'format':1,'runs':[]}
    index['runs'] = [r for r in index['runs'] if r['path']!=path]
    index['runs'].insert(0,{'path':path,'summary':summary})
    index['runs'] = index['runs'][:60]
    index['updated_at'] = stamp()
    index['note'] = 'Encrypted snapshots; private viewer required. Deleting an index entry does not erase Git history.'
    body = {'message':'Update encrypted publisher results index','branch':branch,'content':base64.b64encode(json.dumps(index,indent=2).encode()).decode()}
    if old: body['sha'] = old['sha']
    gh('PUT','contents/'+index_path,body)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--batch',default=os.getenv('SEED_BATCH','auto'))
    parser.add_argument('--publish',action='store_true')
    args = parser.parse_args()
    pool = [safe_url(s.strip()) for s in (ROOT/'seeds.txt').read_text().splitlines() if s.strip() and not s.lstrip().startswith('#')]
    seeds = selected_seeds(list(dict.fromkeys(pool)),args.batch)
    sites, contacts, pages = asyncio.run(run(seeds))
    messages = {(c['channel'],c['contact'].casefold()) for c in contacts if c['channel'] in {'telegram','whatsapp'} and c['quality'] in {'PUBLISHED_BUSINESS_ROUTE','PUBLISHED_GENERAL_ROUTE'}}
    opened = sum(p['state']=='ok' for p in pages)
    summary = {'created_at':stamp(),'run_id':os.getenv('GITHUB_RUN_ID','local'),'seed_pool':len(pool),'seeds_scanned':len(seeds),
        'sites_checked':len(sites),'pages_opened':opened,'contact_evidence_records':len(contacts),'published_messaging_routes':len(messages),
        'relevant_sites':sum(s['site_fit']=='PASS' for s in sites),'access_states':dict(Counter(p['state'] for p in pages)),
        'status':'LIVE_SCAN_COMPLETE' if opened else 'NO_PAGES_ACCESSIBLE','mode':'keyless_bounded_snapshot',
        'notice':'Published routes are not verified accounts, authority, consent or AdMaven approval. No outreach was sent.'}
    fields = ['domain','niche','site_fit','channel','contact','contact_url','role','quality','profile_type','source_url','via','evidence','observed_at','notes']
    payload = {'summary':summary,'sites':sites,'contacts':contacts,'page_diagnostics':pages,
               'files':{'contacts.csv':csv_content(contacts,fields),'sites.csv':csv_content(sites,['domain','url','niche','site_fit','state','html_pages_opened','contact_records','observed_at'])}}
    envelope = seal(payload,(ROOT/'recipient.pem').read_bytes())
    out = ROOT/'sealed'; out.mkdir(exist_ok=True)
    (out/'results.encrypted.json').write_text(json.dumps(envelope),encoding='utf-8')
    (out/'summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
    if args.publish: publish(envelope,summary)
    print(json.dumps(summary,indent=2))
    if os.getenv('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'],'a',encoding='utf-8') as f:
            f.write('# Publisher scan\n\n'+summary['status']+'\n\n')
            f.write(f'Sites checked: {len(sites)} | HTML pages opened: {opened} | Published messaging routes: {len(messages)}\n\n')
            f.write('Results are encrypted in publisher-results. Open your private Results Viewer. Account activity and authority have not been verified.\n')
    return 0 if opened else 1


if __name__=='__main__':
    raise SystemExit(main())
