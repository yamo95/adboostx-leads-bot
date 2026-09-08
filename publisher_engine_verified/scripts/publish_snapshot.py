"""Publish only validated ciphertext and aggregate counts; never public contact values."""
from __future__ import annotations
import base64
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import time
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
REPO = 'yamo95/adboostx-leads-bot'
BRANCH = 'main'
KEY_ID = '6e931aa19f4d1945946add3fc84ea0368ed0624f829eb70c5a29869a0b72e3a2'
PREFIX = 'publisher-engine-results'
MAX_BYTES = 8_000_000


def validate(envelope: dict, summary: dict) -> dict:
    if set(envelope) != {'format', 'key_id', 'wrapped_key', 'nonce', 'ciphertext'}:
        raise ValueError('Unexpected encrypted envelope fields')
    if envelope['format'] != 'publisher-leads-rsa-oaep-aesgcm-v1' or envelope['key_id'] != KEY_ID:
        raise ValueError('Unexpected encryption format or recipient')
    for field, size in [('wrapped_key', 384), ('nonce', 12)]:
        if len(base64.b64decode(envelope[field], validate=True)) != size:
            raise ValueError('Invalid encryption field size')
    ciphertext = base64.b64decode(envelope['ciphertext'], validate=True)
    if not 16 <= len(ciphertext) <= MAX_BYTES:
        raise ValueError('Ciphertext size outside allowed limits')
    counts = ('seed_pool', 'selected_seeds', 'sites_checked', 'html_pages_opened',
              'relevant_sites', 'contact_evidence_records', 'unique_contact_routes_for_review',
              'unique_messaging_routes_for_review', 'ready_sites')
    public = {}
    for field in counts:
        value = summary.get(field, 0)
        if type(value) is not int or not 0 <= value <= 1_000_000:
            raise ValueError('Unexpected summary count')
        public[field] = value
    created = summary.get('created_at', '')
    if not re.fullmatch(r'[0-9T:.+Z-]{20,40}', created):
        raise ValueError('Invalid observation timestamp')
    public['created_at'] = created
    public['status'] = 'LIVE_SCAN_COMPLETE' if summary.get('status') == 'LIVE_SCAN_COMPLETE' else 'NEEDS_ATTENTION'
    public['mode'] = 'keyless_encrypted_snapshot'
    return public


def request(method: str, path: str, payload: dict | None = None):
    if os.getenv('GITHUB_REPOSITORY') != REPO or os.getenv('GITHUB_REF_NAME') != BRANCH:
        raise ValueError('Unexpected publication target')
    req = urllib.request.Request('https://api.github.com/repos/' + REPO + '/' + path,
        data=json.dumps(payload).encode() if payload is not None else None, method=method,
        headers={'Authorization': 'Bearer ' + os.environ['GITHUB_TOKEN'],
                 'Accept': 'application/vnd.github+json', 'Content-Type': 'application/json',
                 'X-GitHub-Api-Version': '2022-11-28', 'User-Agent': 'PublisherEngineSnapshot/1.2'})
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        if method == 'GET' and error.code == 404:
            return None
        raise RuntimeError('GitHub request failed, HTTP ' + str(error.code)) from None


def put(path: str, data: dict, previous: dict | None):
    body = {'message': 'Save encrypted publisher engine snapshot', 'branch': BRANCH,
            'content': base64.b64encode(json.dumps(data, ensure_ascii=True).encode()).decode()}
    if previous:
        body['sha'] = previous['sha']
    return request('PUT', 'contents/' + path, body)


def main() -> None:
    folder = ROOT / 'sealed'
    source = folder / 'results.encrypted.json'
    if source.stat().st_size > MAX_BYTES * 2:
        raise ValueError('Encrypted file too large')
    envelope = json.loads(source.read_text())
    summary = validate(envelope, json.loads((folder / 'summary.json').read_text()))
    run = os.environ['GITHUB_RUN_ID'] + '-' + os.getenv('GITHUB_RUN_ATTEMPT', '1')
    if not re.fullmatch(r'[0-9]+-[0-9]+', run):
        raise ValueError('Invalid run identifier')
    path = PREFIX + '/runs/' + run + '.json'
    previous = request('GET', 'contents/' + path + '?ref=' + BRANCH)
    put(path, envelope, previous)
    index_path = PREFIX + '/index.json'
    for attempt in range(3):
        old = request('GET', 'contents/' + index_path + '?ref=' + BRANCH)
        index = json.loads(base64.b64decode(old['content'])) if old else {'format': 1, 'runs': []}
        rows = [r for r in index.get('runs', []) if r.get('path') != path]
        index = {'format': 1, 'key_id': KEY_ID, 'runs': [{'path': path, 'summary': summary}] + rows[:59],
                 'updated_at': datetime.now(timezone.utc).isoformat(),
                 'notice': 'Ciphertext snapshots; no account verification or outreach. History is retained in Git.'}
        try:
            put(index_path, index, old)
            print('Published encrypted snapshot and aggregate-only index.')
            return
        except RuntimeError:
            if attempt == 2:
                raise
            time.sleep(2)


if __name__ == '__main__':
    main()
