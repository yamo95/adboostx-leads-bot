"""Continue the accepted B219 discovery pool instead of rescanning its first page.
No contact data is imported. This adds a bounded next-page mode and public site
candidates to the existing engine, preserving keys, quality rules and schedule.
"""
from __future__ import annotations
import json
import os
from pathlib import Path
import growth_profile as growth

PREVIOUS_PAGE_SIZE = 500
NEXT_LIMIT = 500
TARGETS = (
    'https://shortnest.com/',
    'https://earn4link.in/',
    'https://safeshort.id/',
    'https://adsfinal.com/',
    'https://snacklink.id/pages/terms',
    'https://onylinks.com/pages/privacy',
    'https://www.terashortner.in/',
    'https://www.edgesports.online/',
    'https://wasapluz.com/contact-us/',
    'https://a2zapk.dev/contact-us/',
    'https://apkfilebox.com/contact-us/',
    'https://getmodsapk.com/',
    'https://spotifyapk.net/contact-us/',
)
BASE_ORDER = growth.ordered_candidates
BASE_SELECT = growth.select_candidates


def plan(rows):
    """Page boundary applies BEFORE adding targets; do not shift old coverage."""
    previous = BASE_ORDER(rows)
    tail = [r['url'] for r in previous[PREVIOUS_PAGE_SIZE:]
            if r.get('kind') in growth.EXTRA_SOURCES]
    added = [{'url':u, 'source':u, 'kind':'targeted', 'chat_hint':True,
              'basis':'Public web candidate discovered 2026-09-09; contacts require direct extraction'}
             for u in TARGETS]
    pool = BASE_ORDER(added + previous)
    valid = {growth.scan.host(r['url']):r['url'] for r in pool}
    seen, selected = set(), []
    for value in list(TARGETS) + tail:
        h = growth.scan.host(value)
        if h in valid and h not in seen:
            seen.add(h); selected.append(valid[h])
        if len(selected) == NEXT_LIMIT:
            break
    return pool, selected


def select(seeds, batch='auto', now=None, next_urls=()):
    if batch != 'next':
        return BASE_SELECT(seeds, batch, now)
    available = {growth.scan.host(u):u for u in seeds}
    seen, selected = set(), []
    for u in next_urls:
        h = growth.scan.host(u)
        if h in available and h not in seen:
            selected.append(available[h]); seen.add(h)
        if len(selected) == NEXT_LIMIT:
            break
    return selected


def main():
    old_order, old_select = growth.ordered_candidates, growth.select_candidates
    next_urls, diagnostics = [], {'revision':'continuation-2026-09-09',
                                  'directory_contact_imports':0}
    def order(rows):
        pool, selected = plan(rows)
        next_urls[:] = selected
        diagnostics.update(candidate_pool=len(pool), next_batch_candidates=len(selected),
                           targeted_sites=len(TARGETS), previous_page_size=PREVIOUS_PAGE_SIZE)
        return pool
    def choose(seeds, batch='auto', now=None):
        selected = select(seeds, batch, now, next_urls)
        if not selected:
            raise RuntimeError('No candidates selected; no empty report is published')
        diagnostics.update(selected_seed_count=len(selected), selected_mode=batch)
        return selected
    try:
        growth.ordered_candidates, growth.select_candidates = order, choose
        return growth.main()
    finally:
        growth.ordered_candidates, growth.select_candidates = old_order, old_select
        out = growth.scan.ROOT / 'sealed'
        out.mkdir(exist_ok=True)
        (out / 'continuation-metrics.json').write_text(json.dumps(diagnostics,indent=2))
        print(json.dumps(diagnostics))

if __name__ == '__main__':
    raise SystemExit(main())
