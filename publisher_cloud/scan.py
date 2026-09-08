"""Stable private operator output layered over the tested scanner.

The normal workflow report is preserved. Each scan also produces a separately
public-key-encrypted copy for the access package delivered to the operator.
No private key, decrypted contact data, or repository token is added to scanning.
"""
from __future__ import annotations
import base64
import json
import os
from pathlib import Path
import re
import sys
from urllib.parse import quote
import scanner_core as core

BASE_MAIN = core.main
BASE_SEAL = core.seal
BASE_PUBLISH = core.publish
FINGERPRINT = 'b219c932768c4a5e52dda6bec834872f899811fe5142b0cd34f4f113afadf29b'
PREFIX = 'private-b219-results'
core._operator_key_path = core.ROOT / 'recipient-b219c932.pem'


def _save_operator_copy(payload):
    envelope = BASE_SEAL(payload, Path(core._operator_key_path).read_bytes())
    if envelope.get('key_id') != FINGERPRINT:
        raise ValueError('Operator public key does not match delivered access package')
    out = core.ROOT / 'sealed'
    out.mkdir(exist_ok=True)
    (out / 'operator-results.encrypted.json').write_text(json.dumps(envelope), encoding='utf-8')
    return envelope


def _publish_operator_copy(summary):
    branch = os.environ.get('GITHUB_REF_NAME', 'main')
    if branch not in {'main', 'lead-engine-activation'}:
        raise ValueError('Unexpected operator result branch')
    rid = os.environ['GITHUB_RUN_ID'] + '-' + os.environ.get('GITHUB_RUN_ATTEMPT', '1')
    if not re.fullmatch(r'[0-9-]+', rid):
        raise ValueError('Invalid run identifier')
    envelope = json.loads((core.ROOT / 'sealed/operator-results.encrypted.json').read_text())
    if set(envelope) != {'format','key_id','wrapped_key','nonce','ciphertext'} or envelope['key_id'] != FINGERPRINT:
        raise ValueError('Refusing non-envelope operator data')
    if envelope['format'] != core.FORMAT or summary['run_id'] != os.environ['GITHUB_RUN_ID']:
        raise ValueError('Operator report identity mismatch')
    summary_fields = {'created_at','run_id','seed_pool','seeds_scanned','sites_checked','pages_opened',
                      'contact_evidence_records','published_messaging_routes','relevant_sites',
                      'access_states','status','mode','notice'}
    if not set(summary) <= summary_fields:
        raise ValueError('Unexpected public summary fields')
    path = PREFIX + '/runs/' + rid + '.json'
    old = core.gh('GET', 'contents/' + path + '?ref=' + quote(branch, safe=''))
    body = {'message':'Store private operator ciphertext '+rid, 'branch':branch,
            'content':base64.b64encode(json.dumps(envelope).encode()).decode()}
    if old: body['sha'] = old['sha']
    core.gh('PUT', 'contents/' + path, body)
    index_path = PREFIX + '/index.json'
    old = core.gh('GET', 'contents/' + index_path + '?ref=' + quote(branch, safe=''))
    index = json.loads(base64.b64decode(old['content'])) if old else {'format':1,'runs':[]}
    index['runs'] = [{'path':path,'summary':summary}] + [r for r in index['runs'] if r['path'] != path]
    index['runs'] = index['runs'][:60]
    index['updated_at'] = core.stamp()
    index['key_id'] = FINGERPRINT
    index['note'] = 'Encrypted operator snapshots. Private access file required. Git history persists.'
    body = {'message':'Update private operator result index','branch':branch,
            'content':base64.b64encode(json.dumps(index,indent=2).encode()).decode()}
    if old: body['sha'] = old['sha']
    core.gh('PUT', 'contents/' + index_path, body)


def main():
    current_seal = core.seal
    def seal_with_operator_copy(payload, public_bytes):
        _save_operator_copy(payload)
        return current_seal(payload, public_bytes)
    core.seal = seal_with_operator_copy
    try:
        return BASE_MAIN()
    finally:
        core.seal = current_seal


def publish(envelope, summary):
    BASE_PUBLISH(envelope, summary)
    _publish_operator_copy(summary)


# Preserve the tested module globals and existing integration patch targets.
core.main = main
core.publish = publish
core._save_operator_copy = _save_operator_copy
core._publish_operator_copy = _publish_operator_copy
if __name__ == '__main__':
    raise SystemExit(main())
else:
    sys.modules[__name__] = core
