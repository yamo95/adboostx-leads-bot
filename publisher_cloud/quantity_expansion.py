"""Bounded candidate expansion for the existing B219 scanner, not a new service.
Directory links are discovery hints only. Contacts must be read from the website.
"""
from __future__ import annotations
import asyncio
from collections import deque
from datetime import datetime
import json
import os
from pathlib import Path
import re
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo
import scan

BATCH_SIZE = 60
MAX_CANDIDATES = 600
CONCURRENT_SITES = 6
MAX_RELATED = 6
SOURCES = {
    'apk': 'https://raw.githubusercontent.com/fmhy/edit/main/docs/mobile.md',
    'streaming': 'https://raw.githubusercontent.com/fmhy/edit/main/docs/video.md',
}
EXTRA_SEEDS = '''https://diskwala.com/
https://shrtfly.com/
https://linkpearl.com/
https://urlking.site/
https://tinyearn.com/
https://www.earnpaste.com/
https://earnurls.com/
https://yilnks.com/
https://zap2link.com/
https://apk-store.org/contacts
https://carparkingmultiapk.com/contact-us/
https://mod-apk-u.com/contact
https://apk-honista.com/contact-us/
https://hexapk.com/contact
https://yacinetv.show/contactus.php
https://honistaapk.in.net/
'''
EXCLUDED = set(scan.SOCIAL) | {
    'discord.com','discord.gg','rentry.co','rentry.org','fmhy.net','codeberg.org',
    'gitlab.com','wikipedia.org','archive.org','patreon.com','ko-fi.com',
    'cse.google.com','virgil.samidy.com','virgil-search.pages.dev',
}
LINK = re.compile(r'\[[^\]]*\]\((https?://[^\s)]+)\)')
SENSITIVE = re.compile(r'requires?\s+sign.?up|signup\s+required|\bpassword\b|\bPW:|search\s+engines?|\bforums?\b|\bmalware\b|\bunsafe\b', re.I)


def eligible_url(raw):
    try:
        value = scan.safe_url(raw)
        host = scan.host(value)
        if any(host == h or host.endswith('.' + h) for h in EXCLUDED):
            return None
        return value
    except (ValueError, TypeError):
        return None


def parse_catalog(text, kind, source):
    """Read only approved sections and one primary website per directory entry."""
    active = False
    rows = []
    allowed = {
        'apk': {'modded apks', 'untouched apks'},
        'streaming': {'stream aggregators', 'dedicated servers', 'dedicated server',
                      'dedicated server sites', 'sports streaming', 'live sports'},
    }
    for number, line in enumerate(text.splitlines(), 1):
        if line.startswith('#'):
            title = re.sub(r'[^a-z0-9 ]', ' ', line.lower())
            title = ' '.join(title.split())
            active = title in allowed[kind]
            continue
        if not active or not line.startswith('* ') or SENSITIVE.search(line):
            continue
        match = LINK.search(line)
        if not match:
            continue
        value = eligible_url(match.group(1))
        if not value:
            continue
        hint = 'sports' if 'sport' in title else kind
        rows.append({'url': scan.origin(value) + '/', 'source': source + '#L' + str(number),
                     'kind': hint, 'basis': 'Directory candidate; independent site check required'})
    return rows


def read_catalog(source):
    # Fixed public text endpoints only. Never forward repository credentials.
    if source not in SOURCES.values():
        raise ValueError('Unapproved discovery source')
    request = Request(source, headers={'User-Agent': scan.UA, 'Accept': 'text/plain'})
    with urlopen(request, timeout=15) as response:
        if response.geturl() != source:
            raise ValueError('Unexpected catalog redirect')
        data = response.read(500001)
    if len(data) > 500000:
        raise ValueError('Oversized discovery source')
    return data.decode('utf-8')


def unique_candidates(rows):
    seen, result = set(), []
    for row in rows:
        value = eligible_url(row.get('url'))
        if value is None or scan.host(value) in seen:
            continue
        seen.add(scan.host(value))
        result.append(dict(row, url=value))
        if len(result) == MAX_CANDIDATES:
            break
    return result


def balanced(rows):
    groups = {}
    for row in rows:
        groups.setdefault(row['kind'], deque()).append(row)
    result = []
    while any(groups.values()):
        for group in groups.values():
            if group:
                result.append(group.popleft())
    return result


def choose(seeds, batch='auto', now=None):
    if not seeds:
        return []
    if batch == 'auto':
        local = now or datetime.now(ZoneInfo('Asia/Jerusalem'))
        slot = (local.toordinal() - datetime(2026, 9, 8).toordinal()) * 2 + (local.hour >= 15)
    elif batch == 'all':
        slot = 0  # A manual run is bounded, not an unbounded whole-pool crawl.
    else:
        slot = int(batch)
        if slot < 0:
            raise ValueError('Invalid batch')
    count = min(BATCH_SIZE, len(seeds))
    start = (slot * BATCH_SIZE) % len(seeds)
    return [seeds[(start + offset) % len(seeds)] for offset in range(count)]


async def expanded_run(seeds):
    """Use unchanged site extraction, robots rules, DNS guards and per-host pace."""
    sites, contacts, tried = [], [], set()
    sem = asyncio.Semaphore(CONCURRENT_SITES)
    async with scan.Fetcher() as fetcher:
        async def task(url):
            tried.add(scan.host(url))
            async with sem:
                try:
                    return await scan.scan_site(url, fetcher)
                except Exception as error:
                    return ({'domain': scan.host(url), 'url': url, 'site_fit': 'REVIEW',
                             'niche': 'Unclassified', 'state': 'INTERRUPTED_' + type(error).__name__,
                             'html_pages_opened': 0, 'observed_at': scan.stamp()}, [], [])
        first = await asyncio.gather(*(task(s) for s in seeds))
        extra = []
        for site, found, candidates in first:
            sites.append(site)
            contacts.extend(found)
            for candidate in candidates:
                value = eligible_url(candidate)
                if value and scan.host(value) not in tried and len(extra) < MAX_RELATED:
                    tried.add(scan.host(value))
                    extra.append(value)
        if extra:
            for site, found, _ in await asyncio.gather(*(task(s) for s in extra)):
                sites.append(site)
                contacts.extend(found)
        return sites, contacts, fetcher.pages


def main():
    seed_path = scan.ROOT / 'seeds.txt'
    base = [s.strip() for s in seed_path.read_text().splitlines()
            if s.strip() and not s.lstrip().startswith('#')]
    known = [{'url': s, 'kind': 'existing', 'source': 'Existing reviewed seed list',
              'basis': 'Seed candidate; independent site check required'} for s in base]
    known += [{'url': s, 'kind': 'expanded', 'source': s,
               'basis': 'Public-web discovery, September 8 2026; not a contact record'}
              for s in EXTRA_SEEDS.splitlines() if s]
    discovered, errors, successes = [], {}, 0
    for kind, source in SOURCES.items():
        try:
            rows = parse_catalog(read_catalog(source), kind, source)
            if not rows:
                raise ValueError('No candidate sections matched')
            discovered.extend(rows)
            successes += 1
        except Exception as error:
            errors[kind] = type(error).__name__
    pool = unique_candidates(known + balanced(discovered))
    metadata = {scan.host(r['url']): r for r in pool}
    original = seed_path.read_bytes()
    old_run, old_select = scan.run, scan.selected_seeds
    async def run_with_provenance(seeds):
        sites, contacts, pages = await expanded_run(seeds)
        for row in sites + contacts:
            source = metadata.get(row.get('domain', ''))
            if source:
                row['discovery_source'] = source['source']
                row['discovery_basis'] = source['basis']
        return sites, contacts, pages
    try:
        seed_path.write_text('\n'.join(r['url'] for r in pool) + '\n')
        scan.selected_seeds, scan.run = choose, run_with_provenance
        print(json.dumps({'candidate_pool': len(pool), 'batch_limit': BATCH_SIZE,
                          'related_limit': MAX_RELATED, 'catalog_successes': successes,
                          'catalog_errors': errors, 'contacts_imported_from_catalog': 0}))
        return scan.main()
    finally:
        scan.run, scan.selected_seeds = old_run, old_select
        seed_path.write_bytes(original)


if __name__ == '__main__':
    raise SystemExit(main())
