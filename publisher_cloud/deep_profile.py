"""Broaden B219 discovery without lowering contact filters or rotating keys.
New feed data supplies candidate URLs only. Existing crawler verifies each source.
"""
from __future__ import annotations
from collections import Counter
import json
import re
from pathlib import Path
import growth_profile as growth
import continuation_profile as continuation

DEEP_LIMIT = 500
NEW_SOURCES = {
    'deep-games': 'https://raw.githubusercontent.com/fmhy/edit/main/docs/gaming.md',
    'deep-regional-apk': 'https://raw.githubusercontent.com/fmhy/edit/main/docs/non-english.md',
    'deep-desktop-games': 'https://raw.githubusercontent.com/fmhy/edit/main/docs/linux-macos.md',
}
CANDIDATES_FILE = Path(__file__).with_name('deep_candidates.json')
GAMES_HEADINGS = {'download games','game repacks','rom sites','roms','abandonware','retro games',
                  'linux gaming','mac gaming','mac games','linux games'}
SKIP = re.compile(r'\b(?:password|malware|unsafe|porn|adult|casino|gambling|wiki|guides?|managers?|loaders?|emulators?|patchers?|installers?|tools?|indexes?)\b|requires?\s+sign.?up|signup\s+required|\bPW:|search\s+engines?|redirect\s+bypass', re.I)
EXTRA_EXCLUDED = {'cse.google.com','virgil.samidy.com','virgil-search.pages.dev','discord.gg',
                  'discord.com','t.me','rentry.co','rentry.org','github.com','reddit.com',
                  'fluxer.gg','store.steampowered.com','gog.com','amazon.com','microsoft.com'}


def eligible(value):
    u = growth.candidate_url(value)
    if not u:
        return None
    h = growth.scan.host(u)
    if any(h == x or h.endswith('.'+x) for x in EXTRA_EXCLUDED):
        return None
    return u


def parse_new(text, kind, source):
    if kind not in NEW_SOURCES or source != NEW_SOURCES[kind]:
        raise ValueError('Unexpected feed')
    rows, active_level = [], None
    for line_no, raw in enumerate(text.splitlines(),1):
        line = raw.strip()
        heading = re.match(r'^(#{1,6})\s+',line)
        if heading:
            level = len(heading.group(1))
            active_level = None
            title = growth.title_of(line)
            if title in GAMES_HEADINGS:
                active_level = level
            continue
        if not line.startswith(('* ','- ')) or SKIP.search(line):
            continue
        if kind == 'deep-regional-apk':
            if not re.search(r'\bapks?\b|android.*\b(?:apps|games|mods)\b',line,re.I):
                continue
        elif active_level is None:
            continue
        match = growth.LINK.search(line)
        u = eligible(match.group(1)) if match else None
        if u:
            rows.append({'url':growth.scan.origin(u)+'/', 'kind':kind,
                         'source':source+'#L'+str(line_no),'deep_candidate':True,
                         'basis':'Public catalog discovery only; contact and fit require source extraction'})
    return rows


def target_rows(values):
    if not isinstance(values,list) or len(values)>500:
        raise ValueError('Invalid candidate configuration')
    rows,seen=[],set()
    for value in values:
        u=eligible(value)
        if not u:
            continue
        h=growth.scan.host(u)
        if h in seen:
            continue
        seen.add(h)
        rows.append({'url':u,'source':u,'kind':'targeted','deep_candidate':True,
                     'basis':'Targeted candidate URL, not an approved lead; independent site extraction required'})
    return rows


def select(seeds,batch='auto',now=None,deep_urls=()):
    if batch != 'deep':
        return continuation.BASE_SELECT(seeds,batch,now)
    available={growth.scan.host(u):u for u in seeds}
    found,used=[],set()
    for u in deep_urls:
        h=growth.scan.host(u)
        if h in available and h not in used:
            found.append(available[h]);used.add(h)
        if len(found)>=DEEP_LIMIT:
            break
    return found


def main():
    old_sources,old_parse,old_order,old_select=(growth.EXTRA_SOURCES,growth.parse_extra,
                                               growth.ordered_candidates,growth.select_candidates)
    scan=growth.scan
    old_contact,old_business=scan.CONTACT_PATH,scan.BUSINESS
    targets=target_rows(json.loads(CANDIDATES_FILE.read_text()))
    deep_urls=[]; next_urls=[]
    stats={'revision':'deep-2026-09-09','directory_contacts_imported':0,
           'candidate_url_count':len(targets),'scheduled_limit':growth.SCHEDULED_LIMIT,
           'deep_limit':DEEP_LIMIT,'related_limit':growth.RELATED_LIMIT}
    def parser(text,kind,source):
        return parse_new(text,kind,source) if kind in NEW_SOURCES else old_parse(text,kind,source)
    def order(rows):
        _, prior_next = continuation.plan(rows)
        next_urls[:] = prior_next
        prior_targets=[{'url':u,'source':u,'kind':'targeted','basis':'Retained existing candidate'}
                       for u in continuation.TARGETS]
        pool=old_order(targets+rows+prior_targets)
        deep_urls[:]=[r['url'] for r in pool if r.get('deep_candidate')]
        stats.update(candidate_pool=len(pool),deep_candidates=len(deep_urls),
                     source_counts=dict(Counter(r['kind'] for r in pool)))
        return pool
    def choose(seeds,batch='auto',now=None):
        if batch=='next':
            selected=continuation.select(seeds,'next',now,next_urls)
        else:
            selected=select(seeds,batch,now,deep_urls)
        if not selected:
            raise RuntimeError('No candidates; refusing empty scan')
        stats.update(selected_count=len(selected),selected_mode=batch)
        return selected
    try:
        growth.EXTRA_SOURCES=dict(old_sources,**NEW_SOURCES)
        growth.parse_extra,growth.ordered_candidates,growth.select_candidates=parser,order,choose
        scan.CONTACT_PATH=re.compile(old_contact.pattern+r'|svyaz|obratn|kontakt|hubungi|kerjasama|lien-he|lienhe|\u043a\u043e\u043d\u0442\u0430\u043a\u0442|\u0441\u043e\u0442\u0440\u0443\u0434\u043d\u0438\u0447',re.I)
        scan.BUSINESS=re.compile(old_business.pattern+r'|kerjasama|\u0441\u043e\u0442\u0440\u0443\u0434\u043d\u0438\u0447\u0435\u0441\u0442\u0432',re.I)
        return growth.main()
    finally:
        growth.EXTRA_SOURCES,growth.parse_extra,growth.ordered_candidates,growth.select_candidates=old_sources,old_parse,old_order,old_select
        scan.CONTACT_PATH,scan.BUSINESS=old_contact,old_business
        output=scan.ROOT/'sealed';output.mkdir(exist_ok=True)
        (output/'deep-metrics.json').write_text(json.dumps(stats,indent=2))
        print(json.dumps(stats))

if __name__=='__main__':
    raise SystemExit(main())
