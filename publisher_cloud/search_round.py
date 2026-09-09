"""Page-based search rounds for the existing B219 workflow.

The private browser counts NEW, eligible messaging routes across pages. A page
completion is never a claim that the 30-route round target has been reached.
No private key or GitHub token is passed to the crawler.
"""
from __future__ import annotations
import hashlib
import os
import re
import messaging_enrichment as messaging
import deep_profile as deep
import scan

PAGE_SIZE = 120
MAX_PAGES = 13
TARGET = 30


def request(environ):
    rid = environ.get('SEARCH_ROUND_ID', '')
    value = environ.get('SEARCH_PAGE', '0')
    expected = environ.get('SEARCH_POOL_HASH', '')
    if not re.fullmatch(r'[a-f0-9]{32}', rid):
        raise ValueError('Invalid search round ID')
    if not re.fullmatch(r'\d{1,2}', value) or not 0 <= int(value) < MAX_PAGES:
        raise ValueError('Invalid search page')
    if expected and not re.fullmatch(r'[a-f0-9]{64}', expected):
        raise ValueError('Invalid candidate pool fingerprint')
    return rid, int(value), expected


def page_plan(seeds, rid, page, expected=''):
    """Stable, non-wrapping pages. Refuse drift instead of skipping candidates."""
    request({'SEARCH_ROUND_ID': rid, 'SEARCH_PAGE': str(page), 'SEARCH_POOL_HASH': expected})
    by_host = {}
    for seed in seeds:
        value = deep.eligible(seed)
        if value:
            by_host.setdefault(scan.host(value), value)
    pool = sorted(by_host.values(), key=lambda u: hashlib.sha256(
        (rid + '|' + scan.host(u)).encode()).hexdigest())
    digest = hashlib.sha256('\n'.join(pool).encode()).hexdigest()
    if expected and expected != digest:
        raise RuntimeError('CANDIDATE_POOL_CHANGED: resume with a new round; do not skip pages')
    start = page * PAGE_SIZE
    selected = pool[start:start + PAGE_SIZE]
    metadata = {'format': 1, 'id': rid, 'page': page, 'page_size': PAGE_SIZE,
                'pool_size': len(pool), 'pool_hash': digest, 'target': TARGET,
                'has_more': start + len(selected) < len(pool) and page + 1 < MAX_PAGES,
                'max_pages': MAX_PAGES, 'completion': 'PAGE_ONLY',
                'novelty_counting': 'private_browser'}
    return selected, metadata


def annotate_payload(payload, metadata):
    """Only inside the existing encrypted envelope; no plaintext lead output."""
    payload['search_round'] = dict(metadata)
    return payload


def main():
    if os.environ.get('SEED_BATCH') != 'search':
        return messaging.main()
    rid, page, expected = request(os.environ)
    if os.environ.get('GITHUB_EVENT_NAME') != 'workflow_dispatch':
        raise RuntimeError('Interactive search must be explicitly dispatched')
    # scan.py deliberately exposes scanner_core; the accepted wrapper's globals
    # own the operator-envelope hook. Annotate BEFORE either envelope is sealed.
    namespace = scan.main.__globals__
    original_copy = namespace['_save_operator_copy']
    original_select = deep.select
    metadata = {}
    def select(seeds, batch='auto', now=None, deep_urls=()):
        if batch != 'search':
            return original_select(seeds, batch, now, deep_urls)
        selected, plan = page_plan(seeds, rid, page, expected)
        if not selected:
            raise RuntimeError('CANDIDATE_POOL_EXHAUSTED: no empty scan is published')
        metadata.update(plan)
        return selected
    def save_operator(payload):
        if not metadata:
            raise RuntimeError('Missing validated search plan')
        return original_copy(annotate_payload(payload, metadata))
    try:
        deep.select = select
        namespace['_save_operator_copy'] = save_operator
        return messaging.main()
    finally:
        deep.select = original_select
        namespace['_save_operator_copy'] = original_copy


def history_entries(previous, current, summary, run_id, attempt):
    """Keep report locations indefinitely, without publishing contact identifiers."""
    entries = {}
    for item in list(previous.get('runs', [])) + list(current.get('runs', [])):
        path = item.get('path', '')
        if not re.fullmatch(r'private-b219-results/runs/\d+-\d+\.json', path):
            raise ValueError('Invalid history report path')
        created = item.get('created_at') or item.get('summary', {}).get('created_at')
        if not isinstance(created, str):
            raise ValueError('Missing history report date')
        entries[path] = {'path': path, 'created_at': created}
    rid = str(run_id) + '-' + str(attempt)
    if not re.fullmatch(r'\d+-\d+', rid):
        raise ValueError('Invalid history run ID')
    path = 'private-b219-results/runs/' + rid + '.json'
    entries[path] = {'path': path, 'created_at': summary['created_at']}
    return {'format': 1, 'key_id': messaging.deep.growth.KEY_ID,
            'runs': sorted(entries.values(), key=lambda row: row['created_at']),
            'note': 'Report locations only, retained for first-added dates and duplicate checks. No contact values.'}


def publish(envelope, summary):
    """Original encrypted publication plus a non-pruning history of report paths."""
    import base64
    import json
    branch = os.environ.get('GITHUB_REF_NAME', 'main')
    if branch != 'main':
        raise ValueError('Interactive history is bound to main')
    path = 'private-b219-results/history.json'
    old = scan.gh('GET', 'contents/' + path + '?ref=main')
    current = scan.gh('GET', 'contents/private-b219-results/index.json?ref=main')
    decode = lambda obj: json.loads(base64.b64decode(obj['content'])) if obj else {'runs': []}
    history = history_entries(decode(old), decode(current), summary,
                              os.environ['GITHUB_RUN_ID'], os.environ.get('GITHUB_RUN_ATTEMPT', '1'))
    scan.publish(envelope, summary)
    body = {'message': 'Retain encrypted report history for lead dates and deduplication',
            'branch': 'main', 'content': base64.b64encode(json.dumps(history, indent=2).encode()).decode()}
    if old:
        body['sha'] = old['sha']
    scan.gh('PUT', 'contents/' + path, body)


if __name__ == '__main__':
    raise SystemExit(main())
