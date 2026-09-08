"""Compatibility delivery for the explicitly registered private user viewer.

No new crawling, plaintext publication, or private keys. The primary recipient
and its output are left unchanged. Adding another recipient requires a reviewed
code change; arbitrary repository keys are never enrolled automatically.
"""
from __future__ import annotations
import base64
import hashlib
import json
import os
from pathlib import Path
import re
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

KEY_ID = '0d32ffa20b873f7bff683a7193da8da42a65ba0d2fba4f604c5c880dc351aa85'
KEY_FILE = 'recipient-0d32ffa2.pem'
PREFIX = 'publisher-viewer-results/0d32ffa2'
FORMAT = 'publisher-leads-rsa-oaep-aesgcm-v1'
ROOT = Path(__file__).resolve().parent


def validate_envelope(envelope):
    if set(envelope) != {'format','key_id','wrapped_key','nonce','ciphertext'}:
        raise ValueError('Unexpected encrypted envelope fields')
    if envelope['format'] != FORMAT or envelope['key_id'] != KEY_ID:
        raise ValueError('Viewer recipient mismatch')
    if len(base64.b64decode(envelope['nonce'], validate=True)) != 12:
        raise ValueError('Invalid nonce')
    if len(base64.b64decode(envelope['wrapped_key'], validate=True)) != 384:
        raise ValueError('Invalid wrapped key')
    if len(base64.b64decode(envelope['ciphertext'], validate=True)) < 16:
        raise ValueError('Missing authenticated ciphertext')
    return envelope


def seal_for_viewer(payload, encrypt):
    public_bytes = ROOT.joinpath(KEY_FILE).read_bytes()
    public = serialization.load_pem_public_key(public_bytes)
    if not isinstance(public, rsa.RSAPublicKey) or public.key_size != 3072:
        raise ValueError('Registered RSA-3072 recipient required')
    der = public.public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
    if hashlib.sha256(der).hexdigest() != KEY_ID:
        raise ValueError('Registered public key fingerprint changed')
    envelope = validate_envelope(encrypt(payload, public_bytes))
    target = ROOT / 'sealed' / 'viewer-0d32ffa2.encrypted.json'
    target.parent.mkdir(exist_ok=True)
    target.write_text(json.dumps(envelope), encoding='utf-8')


def publish_for_viewer(summary):
    import scan
    if os.environ.get('GITHUB_REPOSITORY') != 'yamo95/adboostx-leads-bot':
        raise ValueError('Unexpected repository')
    if os.environ.get('GITHUB_REF_NAME') != 'main':
        raise ValueError('Unexpected publishing branch')
    rid = os.environ['GITHUB_RUN_ID'] + '-' + os.environ['GITHUB_RUN_ATTEMPT']
    if not re.fullmatch(r'[0-9]+-[0-9]+', rid):
        raise ValueError('Invalid run identifier')
    allowed = {'created_at','run_id','seed_pool','seeds_scanned','sites_checked','pages_opened','contact_evidence_records','published_messaging_routes','relevant_sites','access_states','status','mode','notice','messaging_routes_on_relevant_sites','messaging_by_channel','discovery_api_attempts','discovery_api_successes','discovery_candidates','parsing'}
    if set(summary) - allowed or summary['run_id'] != os.environ['GITHUB_RUN_ID']:
        raise ValueError('Invalid public aggregate summary')
    envelope = validate_envelope(json.loads(ROOT.joinpath('sealed/viewer-0d32ffa2.encrypted.json').read_text()))
    def write(path, value):
        old = scan.gh('GET', 'contents/' + path + '?ref=main')
        body = {'branch':'main','message':'Update encrypted registered viewer '+rid,
                'content':base64.b64encode(json.dumps(value).encode()).decode()}
        if old:
            body['sha'] = old['sha']
        scan.gh('PUT', 'contents/' + path, body)
    path = PREFIX + '/runs/' + rid + '.json'
    write(path, envelope)
    index_path = PREFIX + '/index.json'
    old = scan.gh('GET', 'contents/' + index_path + '?ref=main')
    index = json.loads(base64.b64decode(old['content'])) if old else {'format':1,'runs':[]}
    index['runs'] = [{'path':path,'key_id':KEY_ID,'summary':summary}] + [r for r in index['runs'] if r.get('path') != path][:59]
    index['updated_at'] = scan.stamp()
    index['note'] = 'Registered private viewer compatibility. Encrypted snapshots only; Git history is retained.'
    write(index_path, index)
    print('Registered private viewer snapshot published; primary recipient unchanged.')
