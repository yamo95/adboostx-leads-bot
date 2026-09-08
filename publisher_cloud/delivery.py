"""Production adapter: audited parsing, bounded keyless discovery, encrypted output.
The crawl has no repository credentials. Publishing is a separate workflow step.
"""
from __future__ import annotations
import asyncio
from collections import Counter
from datetime import datetime
import json
from pathlib import Path
import re
import time
from urllib.parse import urlencode, urlsplit
import urllib.request
from zoneinfo import ZoneInfo
import scan
from leadengine.parse import parse_page
from leadengine.classify import classify

ROOT = Path(__file__).resolve().parent
PAGES = {}
DISCOVERY = {'attempts': 0, 'successes': 0, 'candidates': [], 'errors': []}
BASE_RUN, BASE_SEAL = scan.run, scan.seal
QUERIES = ['apk download', 'live sports streaming', 'game mods download',
           'movies streaming website', 'file hosting', 'url shortener earn',
           'android mod apk', 'football live stream']


def audited_parse(html, source):
    page = parse_page(html, source)
    PAGES.setdefault(scan.host(source), []).append(page)
    contacts = []
    for c in page.contacts:
        if c.kind not in {'telegram', 'whatsapp', 'email'}:
            continue
        profile = 'unverified'
        if c.purpose in {'community', 'community_invite'}:
            profile = 'community'
        elif c.purpose == 'bot':
            profile = 'bot'
        elif c.verification in {'published_short_link_unresolved', 'display_link_mismatch'}:
            profile = 'short_link_unresolved'
        value = c.value
        if c.kind == 'telegram' and re.fullmatch(r'https://t\.me/[A-Za-z][A-Za-z0-9_]{2,31}', value):
            value = '@' + value.rsplit('/', 1)[1]
        contacts.append({'channel': c.kind, 'contact': value,
            'contact_url': c.contact_url or c.value,
            'role': 'legal' if c.purpose == 'legal_only' else c.purpose,
            'profile_type': profile, 'source_url': c.source_url, 'via': '',
            'evidence': c.evidence[:350], 'observed_at': c.observed_at,
            'notes': ' '.join(c.notes)})
    links = [] if page.nofollow else [(x['url'], x['label']) for x in page.links if not x['nofollow']]
    return contacts, links, page.text


async def telegram_hops(contacts, fetcher):
    output = scan.unique(contacts)
    queue = [(c, 0) for c in output if c['channel'] == 'telegram'
             and c['profile_type'] in {'unverified', 'community'}
             and re.fullmatch(r'https://t\.me/[A-Za-z][A-Za-z0-9_]{2,31}', c['contact_url'])]
    seen = set()
    for _ in range(6):
        if not queue:
            break
        item, depth = queue.pop(0)
        key = item['contact_url'].casefold()
        if key in seen:
            continue
        seen.add(key)
        page = await fetcher.get(item['contact_url'], site='https://t.me/')
        if page['state'] != 'ok':
            item['notes'] += ' Public profile was unavailable.'
            continue
        soup = scan.BeautifulSoup(page['html'], 'html.parser')
        extra = soup.select_one('.tgme_page_extra')
        extra_text = extra.get_text(' ', strip=True) if extra else ''
        text = soup.get_text(' ', strip=True)
        if re.search(r'subscribers|members|abonn|membres|\u043f\u043e\u0434\u043f\u0438\u0441\u0447\u0438\u043a', extra_text, re.I):
            item['profile_type'] = 'community'
            desc = soup.select_one('.tgme_page_description')
            if depth != 0 or not desc:
                continue
            for br in desc.find_all('br'):
                br.replace_with('\n')
            # Keep line boundaries to avoid assigning an ads role to unrelated handles.
            for line in re.split(r'[\n|;]+', desc.get_text(' ', strip=False)):
                if not (scan.BUSINESS.search(line) or re.search(r'contact|support|help', line, re.I)):
                    continue
                if re.search(r'no\s+ads|do\s+not\s+contact', line, re.I):
                    continue
                for handle in scan.HANDLE.findall(line)[:4]:
                    new = scan.route('https://t.me/' + handle, line, item['contact_url'])
                    if new and new['contact_url'].casefold() not in seen:
                        new['via'] = item['source_url']
                        new['notes'] = 'Published in a site-linked channel bio; ownership and commercial authority remain unverified.'
                        output.append(new)
                        if new['profile_type'] == 'unverified':
                            queue.append((new, 1))
        elif re.search(r'start bot', text, re.I) or extra_text.lower() == 'bot':
            item['profile_type'] = 'bot'
        elif re.search(r'if you have telegram, you can contact|send message', text, re.I):
            item['profile_type'] = 'contact_preview'
            item['notes'] += ' Contact preview observed, not proof of activity or authority.'
    return scan.unique(output)


def discover(known):
    """Two public REST requests; no token, no retries on provider errors."""
    local = datetime.now(ZoneInfo('Asia/Jerusalem'))
    day = local.toordinal()
    base = (day * 4 + (0 if local.hour < 15 else 2)) % len(QUERIES)
    found, seen = [], {scan.host(u) for u in known}
    for offset in range(2):
        if offset:
            time.sleep(7)
        query = QUERIES[(base + offset) % len(QUERIES)]
        url = 'https://api.github.com/search/repositories?' + urlencode({
            'q': query + ' fork:false archived:false', 'sort': 'updated',
            'per_page': 20, 'page': 1 + (day // len(QUERIES)) % 3})
        DISCOVERY['attempts'] += 1
        try:
            req = urllib.request.Request(url, headers={'User-Agent': scan.UA,
                'Accept': 'application/vnd.github+json'})
            with urllib.request.urlopen(req, timeout=15) as response:
                body = response.read(1500001)
            if len(body) > 1500000:
                raise ValueError('Response exceeds size limit')
            data = json.loads(body)
            DISCOVERY['successes'] += 1
        except Exception as error:
            DISCOVERY['errors'].append(type(error).__name__)
            break
        for item in data.get('items', []):
            try:
                homepage = scan.safe_url((item.get('homepage') or '').strip())
            except (ValueError, TypeError):
                continue
            h = scan.host(homepage)
            if h in seen or any(h == s or h.endswith('.' + s) for s in scan.SOCIAL):
                continue
            seen.add(h)
            if len(found) < 6:
                found.append(homepage)
                DISCOVERY['candidates'].append({'url': homepage, 'source': item.get('html_url', ''),
                    'query': query, 'basis': 'Public repository homepage; requires independent site qualification.'})
    return found


async def run(seeds):
    extra = await asyncio.to_thread(discover, seeds)
    return await BASE_RUN(seeds + extra)


def corrected_seal(payload, unused):
    sites = {}
    for site in payload['sites']:
        pages = [p for h, values in PAGES.items()
                 if h == site['domain'] or h.endswith('.' + site['domain']) for p in values]
        pages.sort(key=lambda p: urlsplit(p.url).path not in {'', '/'})
        d = classify(pages)
        site.update(site_fit=d['classification'], niche=d['category'], fit_reasons=d['reasons'])
        sites[site['domain']] = site
    for c in payload['contacts']:
        site = sites.get(c['domain'], {})
        c['site_fit'], c['niche'] = site.get('site_fit', 'REVIEW'), site.get('niche', 'unknown')
    summary = payload['summary']
    eligible = {(c['channel'], c['contact'].casefold()) for c in payload['contacts']
        if c['channel'] in {'telegram', 'whatsapp'} and c['site_fit'] == 'PASS'
        and c['quality'] in {'PUBLISHED_BUSINESS_ROUTE', 'PUBLISHED_GENERAL_ROUTE'}}
    summary.update(relevant_sites=sum(s['site_fit'] == 'PASS' for s in payload['sites']),
        messaging_routes_on_relevant_sites=len(eligible),
        messaging_by_channel=dict(Counter(k for k, v in eligible)),
        discovery_api_attempts=DISCOVERY['attempts'], discovery_api_successes=DISCOVERY['successes'],
        discovery_candidates=len(DISCOVERY['candidates']), parsing='audited_v11_core')
    payload['discovery'] = DISCOVERY
    fields = ['domain','niche','site_fit','channel','contact','contact_url','role','quality','profile_type','source_url','via','evidence','observed_at','notes']
    payload['files']['contacts.csv'] = scan.csv_content(payload['contacts'], fields)
    payload['files']['sites.csv'] = scan.csv_content(payload['sites'], ['domain','url','niche','site_fit','state','html_pages_opened','contact_records','observed_at'])
    return BASE_SEAL(payload, (ROOT / 'viewer-public.pem').read_bytes())


def main():
    scan.parse, scan.telegram_hops, scan.run, scan.seal = audited_parse, telegram_hops, run, corrected_seal
    return scan.main()


if __name__ == '__main__':
    raise SystemExit(main())
