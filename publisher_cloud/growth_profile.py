"""Broader discovery for the existing B219 scanner. No new service or keys.
Catalog entries supply candidate websites only, never contact records.
"""
from __future__ import annotations
from collections import Counter
from datetime import datetime
import json
import re
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo
import scan

SCHEDULED_LIMIT = 240
ACCEPTANCE_LIMIT = 500
POOL_LIMIT = 1500
RELATED_LIMIT = 12
EXTRA_SOURCES = {
    'regional': 'https://raw.githubusercontent.com/fmhy/edit/main/docs/non-english.md',
    'mods': 'https://raw.githubusercontent.com/fmhy/edit/main/docs/gaming-tools.md',
    'storage': 'https://raw.githubusercontent.com/fmhy/edit/main/docs/file-tools.md',
    'video-hosts': 'https://raw.githubusercontent.com/fmhy/edit/main/docs/video-tools.md',
    'more-streaming': 'https://raw.githubusercontent.com/fmhy/edit/main/docs/video.md',
}
# Public page URLs observed during discovery; no contact values are imported.
TARGETS = '''https://softurl.in/blog
https://linkshort.in/
https://linksflys.com/
https://earnshorts.com/
https://www.kinglinky.com/
https://inshorturl.com/
https://monelink.top/
https://sportdb.pro/app.php
https://tigoals.live/
https://shizukuapk.com/contact-us/
https://thespikesapk.com/contact-us/
https://myboyapks.com/contact-us/
https://apkcarparking.com/contact-us/
https://support.cinebeta.com/app/
https://filesplay.com/
https://dotflix.lol/contact
https://tempfile.org/help
https://interplanetary.tv/advertise/
https://alightappspro.com/contact-us/
https://specimenzeromodapk.com/contact-us/
'''
LINK = re.compile(r'\[[^\]]*\]\((https?://[^\s)]+)\)')
SKIP = re.compile(r'\b(?:password|malware|unsafe|porn|adult|casino|gambling)\b|requires?\s+sign.?up|signup\s+required|\bPW:|search\s+engines?', re.I)
EXCLUDED = set(scan.SOCIAL) | {'discord.gg','discord.com','rentry.co','rentry.org','fmhy.net','codeberg.org','gitlab.com','wikipedia.org','patreon.com','ko-fi.com','archive.org','greasyfork.org','addons.mozilla.org','chromewebstore.google.com','tiktok.com','vk.com','pinterest.com'}
INDEX_BASE = 'https://raw.githubusercontent.com/yamo95/adboostx-leads-bot/main/'
KEY_ID = 'b219c932768c4a5e52dda6bec834872f899811fe5142b0cd34f4f113afadf29b'


def candidate_url(value):
    try:
        value = scan.safe_url(value)
        h = scan.host(value)
        if any(h == x or h.endswith('.' + x) for x in EXCLUDED):
            return None
        return value
    except (TypeError, ValueError):
        return None


def title_of(line):
    return ' '.join(re.sub(r'[^a-z0-9 ]', ' ', line.lower()).split())


def approved_section(title, kind):
    if kind == 'regional':
        return title == 'streaming' or title.startswith('streaming ') or title == 'downloading' or title.startswith('downloading ')
    return title in {
        'mods': {'game mods', 'gta tools', 'mod resource packs', 'minecraft mods'},
        'storage': {'file hosts', 'premium file hosts'},
        'video-hosts': {'video file hosts'},
        'more-streaming': {'anime streaming', 'drama streaming', 'live tv streaming', 'live tv', 'cartoon streaming'},
    }.get(kind, set())


def parse_extra(text, kind, source):
    rows, active_level = [], None
    for number, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        heading = re.match(r'^(#{1,6})\s+', line)
        if heading:
            level = len(heading.group(1))
            if active_level is not None and level <= active_level:
                active_level = None
            if approved_section(title_of(line), kind):
                active_level = level
            continue
        if active_level is None or not line.startswith(('* ', '- ')) or SKIP.search(line):
            continue
        if kind == 'regional' and not re.search(r'movies?|\btv\b|anime|cartoons?|football|soccer|sports?|games?|\bapk', line, re.I):
            continue
        if kind == 'mods' and re.search(r'guides?|wiki|mod\s+(?:manager|loader)|databases?|walkthroughs', line, re.I) and not re.search(r'GTA.*Mods|Mods.*GTA', line, re.I):
            continue
        if kind in {'storage','video-hosts'} and re.search(r'\bindexes?\b|\bstatus\b', line, re.I):
            continue
        match = LINK.search(line)
        if not match:
            continue
        value = candidate_url(match.group(1))
        if value:
            rows.append({'url': scan.origin(value) + '/', 'kind': kind,
                         'source': source + '#L' + str(number),
                         'chat_hint': bool(re.search(r'\btelegram\b|whatsapp|t\.me/', line, re.I)),
                         'basis': 'Public directory candidate only; contact and site fit require direct source checks'})
    return rows


def select_candidates(seeds, batch='auto', now=None):
    if not seeds:
        return []
    if batch == 'all':
        return list(seeds[:ACCEPTANCE_LIMIT])
    if batch == 'auto':
        local = now or datetime.now(ZoneInfo('Asia/Jerusalem'))
        slot = (local.toordinal() - datetime(2026, 9, 8).toordinal()) * 2 + int(local.hour >= 15)
    else:
        slot = int(batch)
        if slot < 0:
            raise ValueError('Invalid batch')
    start = (slot * SCHEDULED_LIMIT) % len(seeds)
    return [seeds[(start + i) % len(seeds)] for i in range(min(SCHEDULED_LIMIT, len(seeds)))]


def ordered_candidates(rows):
    # Keep different source families interleaved (the prior adapter balances them).
    # Give newly added feeds and explicit chat hints priority over old sources.
    seen, result = set(), []
    for row in rows:
        u = candidate_url(row.get('url'))
        if u is None or scan.host(u) in seen:
            continue
        seen.add(scan.host(u)); result.append(dict(row, url=u))
    def rank(row):
        if row.get('kind') == 'targeted': return 0
        if row.get('kind') in EXTRA_SOURCES: return 1 if row.get('chat_hint') else 2
        return 3
    return sorted(result, key=rank)[:POOL_LIMIT]


def get_public(url, limit):
    req = Request(url, headers={'User-Agent':scan.UA, 'Accept':'text/plain,application/json'})
    with urlopen(req, timeout=15) as response:
        if response.geturl() != url:
            raise ValueError('Unexpected redirect')
        raw = response.read(limit + 1)
    if len(raw) > limit:
        raise ValueError('Response too large')
    return raw


def preserve_baseline():
    """Save existing public ciphertext for exact later comparison, never decrypt."""
    out = scan.ROOT / 'sealed'; out.mkdir(exist_ok=True)
    result = {'baseline_saved':0, 'baseline_errors':0}
    if __import__('os').getenv('GITHUB_EVENT_NAME') == 'schedule':
        return result
    try:
        idx = json.loads(get_public(INDEX_BASE + 'private-b219-results/index.json', 1000000))
        if idx.get('key_id') != KEY_ID or not isinstance(idx.get('runs'), list):
            raise ValueError('Unexpected index')
        for entry in idx['runs'][:10]:
            path = entry.get('path', '')
            if not re.fullmatch(r'private-b219-results/runs/[0-9]+-[0-9]+\.json', path):
                result['baseline_errors'] += 1; continue
            try:
                raw = get_public(INDEX_BASE + path, 8000000)
                e = json.loads(raw)
                if set(e) != {'format','key_id','wrapped_key','nonce','ciphertext'} or e['key_id'] != KEY_ID or e['format'] != scan.FORMAT:
                    raise ValueError('Not matching ciphertext')
                (out / ('baseline-' + path.rsplit('/',1)[1])).write_bytes(raw)
                result['baseline_saved'] += 1
            except Exception:
                result['baseline_errors'] += 1
    except Exception:
        result['baseline_errors'] += 1
    return result


def main():
    import quantity_expansion as q
    baseline = preserve_baseline()
    originals = (q.SOURCES, q.parse_catalog, q.unique_candidates, q.choose, q.MAX_CANDIDATES,
                 q.BATCH_SIZE, q.CONCURRENT_SITES, q.MAX_RELATED, q.read_catalog)
    base_parser = q.parse_catalog
    stats = {'revision':'growth-2026-09-09', 'scheduled_limit':SCHEDULED_LIMIT,
             'acceptance_limit':ACCEPTANCE_LIMIT, 'related_limit':RELATED_LIMIT,
             'directory_contacts_imported':0, **baseline}
    cache = {}
    def catalog(source):
        if source not in q.SOURCES.values():
            raise ValueError('Unapproved catalog')
        if source not in cache:
            cache[source] = get_public(source, 800000).decode('utf-8')
        return cache[source]
    def parse(text, kind, source):
        rows = parse_extra(text, kind, source) if kind in EXTRA_SOURCES else base_parser(text, kind, source)
        stats.setdefault('candidates_by_feed', {})[kind] = len(rows)
        return rows
    def collect(rows):
        target = [{'url':s, 'source':s, 'kind':'targeted', 'basis':'Public contact-page discovery; contacts require fresh direct extraction'}
                  for s in TARGETS.splitlines() if s]
        result = ordered_candidates(target + rows)
        stats['candidate_pool'] = len(result)
        stats['pool_by_feed'] = dict(Counter(r['kind'] for r in result))
        return result
    try:
        q.SOURCES = dict(q.SOURCES, **EXTRA_SOURCES)
        q.read_catalog, q.parse_catalog, q.unique_candidates = catalog, parse, collect
        q.choose, q.MAX_CANDIDATES = select_candidates, POOL_LIMIT
        q.BATCH_SIZE, q.CONCURRENT_SITES, q.MAX_RELATED = SCHEDULED_LIMIT, 8, RELATED_LIMIT
        return q.main()
    finally:
        (q.SOURCES, q.parse_catalog, q.unique_candidates, q.choose, q.MAX_CANDIDATES,
         q.BATCH_SIZE, q.CONCURRENT_SITES, q.MAX_RELATED, q.read_catalog) = originals
        out = scan.ROOT / 'sealed'; out.mkdir(exist_ok=True)
        (out / 'growth-metrics.json').write_text(json.dumps(stats, indent=2))
        print(json.dumps(stats))


if __name__ == '__main__':
    raise SystemExit(main())
