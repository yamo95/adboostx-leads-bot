"""Bounded rotating discovery. Sources supply URLs, never contact evidence."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import os
import re
from urllib.parse import urlsplit, urljoin, parse_qs, quote
from xml.etree import ElementTree as ET
from bs4 import BeautifulSoup
import scan

FAMILIES = {
    'apk': ['mod apk', 'android apk download', 'minecraft apk', 'capcut mod apk', 'honista apk', 'gta apk', 'android game mods', 'apk modded apps'],
    'movies': ['watch movies online', 'film streaming', 'anime streaming', 'series streaming', 'filmes assistir online', 'peliculas online', 'film izle', 'regarder films'],
    'sports': ['live sports streaming', 'football live streams', 'cricket live streaming', 'soccer streaming', 'futebol ao vivo', 'calcio streaming', 'nba live streams', 'deportes en vivo'],
    'mods': ['download game mods', 'minecraft mods download', 'gta mods download', 'beamng mods download', 'sims mods download', 'android mods download', 'game repacks download', 'skyrim mods download'],
    'shorteners': ['url shortener earn money', 'short links earn money', 'shortlink publisher', 'paid url shortener', 'encurtador links', 'pemendek link', 'shortener payout', 'shortlink support'],
    'hosts': ['video hosting earn money', 'file hosting earn money', 'video upload publisher', 'file upload rewards', 'free video hosting', 'file hosting support', 'upload files publisher', 'video sharing monetization'],
}
INTENTS = ['telegram contact', 'whatsapp contact', 'telegram support', 'telegram advertising']
STOP = {'challenge', 'http_403', 'http_429', 'robots_denied_or_unavailable'}
SEARCH_ONLY = {'bing.com', 'duckduckgo.com', 'google.com', 'search.yahoo.com', 'youtube.com', 'facebook.com', 'instagram.com', 't.me', 'telegram.me', 'nicegram.app', 'telemetr.io', 'telegramchannels.me', 'telegramcatalog.com', 'telegram.im', 'appbrain.com', 'download.cnet.com'}
CHALLENGE = re.compile(r'anomaly-modal|challenge-form|bots use DuckDuckGo|select all (?:squares|images)|verify (?:that )?you are human|captcha', re.I)
OFF_SCOPE_HOST = re.compile(r'casino|bet|1win|rummy|poker|slot|lottery|teenpatti|hitclub|go88|sunwin|bong88|918kiss|pinup|porn|xxx|sex|incest|hentai|chatur|nsfw|flixbus|flixster|studyflix|napkin|sapkowski|slaapkamer|fleamapket|packaging|carepackage|\.(?:gov|mil)(?:\.|$)|\.mod\.uk$', re.I)
CONTACT_PATH = re.compile(r'contact|support|advertis|partner|reklam|kontak|contato|about', re.I)


def query_plan(slot=None):
    slot = int(os.environ.get('GITHUB_RUN_NUMBER', '0')) if slot is None else int(slot)
    out = []
    for family, topics in FAMILIES.items():
        for offset in (0, 3):
            topic = topics[(slot + offset) % len(topics)]
            intent = INTENTS[(slot // len(topics) + offset) % len(INTENTS)]
            out.append({'family': family, 'query': topic + ' ' + intent + ' -iptv -casino -site:youtube.com -site:facebook.com'})
    return out


def clean_candidate(raw):
    from fresh_discovery import candidate
    try:
        value = candidate(raw)
        if not value: return None
        h = scan.host(value)
        if OFF_SCOPE_HOST.search(h): return None
        if any(h == x or h.endswith('.' + x) for x in SEARCH_ONLY): return None
        if re.search(r'(?:best|top)[^/]*telegram[^/]*(?:channel|group)', urlsplit(value).path, re.I): return None
        if h.endswith('uptodown.com') and h.startswith('telegram.'): return None
        if re.search(r'(?:^|[./_-])(?:iptv|casino|betting)(?:[./_-]|$)', h, re.I): return None
        return value
    except (ValueError, TypeError): return None


def parse_search(html, provider):
    if CHALLENGE.search(html): return [], 'challenge'
    urls = []
    if provider == 'bing-rss':
        if re.search(r'<!DOCTYPE|<!ENTITY', html, re.I): return [], 'invalid_xml'
        try: root = ET.fromstring(html)
        except ET.ParseError: return [], 'unexpected_markup'
        if root.tag not in {'rss', 'feed'}: return [], 'unexpected_markup'
        urls = [node.text or '' for node in root.findall('.//item/link')]
        state = 'results' if urls else 'no_results'
    else:
        soup = BeautifulSoup(html, 'html.parser')
        anchors = soup.select('a.result__a[href], a.result-link[href], .result__title a[href]')
        for a in anchors:
            raw = a.get('href', '')
            p = urlsplit(raw)
            if (p.hostname or '').endswith('duckduckgo.com') or raw.startswith('/l/?'):
                raw = parse_qs(p.query).get('uddg', [''])[0]
            urls.append(raw)
        state = 'results' if anchors else 'no_results' if soup.select('.no-results, .no-results__message') or 'No results found' in soup.get_text(' ', strip=True) else 'unexpected_markup'
    seen = set(); result = []
    for raw in urls:
        u = clean_candidate(raw)
        if u and scan.host(u) not in seen:
            seen.add(scan.host(u)); result.append(u)
        if len(result) >= 20: break
    return result, state


async def fetch_rss(fetcher, url):
    if urlsplit(url).hostname != 'www.bing.com' or urlsplit(url).path != '/search':
        raise ValueError('RSS_ENDPOINT')
    result = {'state': 'error', 'status': 0, 'html': ''}
    try:
        allowed, parser, delay = await fetcher.policy(url)
        if not allowed or parser and not parser.can_fetch(scan.UA, url):
            return dict(result, state='robots_denied_or_unavailable')
        await fetcher.pace(url, max(delay, 2.0))
        async with fetcher.session.get(url, allow_redirects=False, headers={'Accept': 'application/rss+xml,application/xml,text/xml,text/plain;q=0.5'}) as response:
            result['status'] = response.status
            if response.status != 200: return dict(result, state='http_' + str(response.status))
            content_type = response.headers.get('Content-Type', '').lower()
            if 'attachment' in response.headers.get('Content-Disposition', '').lower() or not any(t in content_type for t in ('xml', 'text/plain', 'text/html')):
                return dict(result, state='non_xml')
            chunks = bytearray()
            async for chunk in response.content.iter_chunked(16384):
                chunks.extend(chunk)
                if len(chunks) > 750000: return dict(result, state='too_large')
            return dict(result, state='ok', html=chunks.decode('utf-8', errors='replace'))
    except Exception as error:
        return dict(result, state=type(error).__name__)


async def discover():
    urls = []; checks = []; blocked = set()
    async with scan.Fetcher() as fetcher:
        for spec in query_plan():
            for provider in ('duckduckgo-html', 'bing-rss'):
                if provider in blocked: continue
                query = spec['query']
                url = ('https://html.duckduckgo.com/html/?q=' + quote(query)) if provider == 'duckduckgo-html' else 'https://www.bing.com/search?format=rss&q=' + quote(query)
                try:
                    reply = await fetcher.get(url) if provider == 'duckduckgo-html' else await fetch_rss(fetcher, url)
                    found, state = parse_search(reply.get('html', ''), provider) if reply.get('state') == 'ok' else ([], reply.get('state', 'unknown'))
                except Exception as error:
                    found, state, reply = [], type(error).__name__, {}
                checks.append({'provider': provider, 'family': spec['family'], 'query': query, 'state': state, 'http_status': reply.get('status', 0), 'candidates': len(found)})
                urls.extend(found)
                if state in STOP: blocked.add(provider)
            if len(blocked) == 2: break
    cache_path=Path(__file__).with_name('catalog-candidates.json')
    if cache_path.exists():
        cached=json.loads(cache_path.read_text())
        raw=cached.get('urls',[])
        if not isinstance(raw,list) or len(raw)>2200:raise ValueError('CATALOG_CACHE_SIZE')
        candidates=[u for u in raw if isinstance(u,str) and clean_candidate(u)==u]
        checks.append({'provider':'majestic-million','source':cached.get('source'),
            'attribution':cached.get('attribution'),'license':cached.get('license'),
            'state':cached.get('state','unknown'),'candidates':len(candidates),
            'downloaded_at':cached.get('downloaded_at'),'daily_cache':True})
        urls.extend(candidates)
    preferred = sorted(dict.fromkeys(urls), key=lambda u: (not bool(CONTACT_PATH.search(urlsplit(u).path)), u))
    return preferred, checks


def health(checks):
    valid = [c for c in checks if c.get('state') in {'results', 'no_results', 'ok'}]
    productive = [c for c in checks if c.get('candidates', 0) > 0]
    failed = [c for c in checks if c not in valid]
    return {'requests': len(checks), 'productive': len(productive), 'failed': len(failed),
            'state': 'unavailable' if checks and not valid else 'degraded' if failed else 'available'}
