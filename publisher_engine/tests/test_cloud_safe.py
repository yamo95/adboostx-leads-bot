import base64
import json
from datetime import datetime, timezone
from pathlib import Path
import pytest
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from scripts.seal_results import seal, write_sealed, AAD
from scripts.cloud_run import select_seeds, public_config, EXPORT_NAMES

@pytest.fixture(scope='module')
def keys():
    k = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    return k, k.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)

def decrypt(envelope, private):
    key = private.decrypt(base64.b64decode(envelope['wrapped_key']), padding.OAEP(mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(), label=None))
    return json.loads(AESGCM(key).decrypt(base64.b64decode(envelope['nonce']), base64.b64decode(envelope['ciphertext']), AAD))

def test_round_trip(keys):
    private, public = keys
    payload = {'files': {'contacts.csv': '@samplebusiness,+12345678999'}, 'summary': {'sites': 2}}
    env = seal(payload, public)
    assert decrypt(env, private) == payload
    assert 'samplebusiness' not in json.dumps(env)

def test_nonce_is_random(keys):
    a, b = seal({'a': 1}, keys[1]), seal({'a': 1}, keys[1])
    assert a['nonce'] != b['nonce'] and a['ciphertext'] != b['ciphertext']

def test_tampering_is_rejected(keys):
    env = seal({'x': 1}, keys[1])
    cipher = bytearray(base64.b64decode(env['ciphertext'])); cipher[0] ^= 1
    env['ciphertext'] = base64.b64encode(cipher).decode()
    with pytest.raises(InvalidTag): decrypt(env, keys[0])

def test_no_private_key_in_output(tmp_path, keys):
    p = tmp_path / 'public.pem'; p.write_bytes(keys[1])
    out = tmp_path / 'out.json'; write_sealed({'ok': True}, p, out)
    assert 'PRIVATE KEY' not in out.read_text()
    assert decrypt(json.loads(out.read_text()), keys[0]) == {'ok': True}

def test_reject_private_pem(keys):
    private_pem = keys[0].private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    with pytest.raises(ValueError): seal({}, private_pem)

def test_keyless_config(tmp_path, monkeypatch):
    monkeypatch.setenv('TAVILY_API_KEY', 'test-not-real')
    cfg = public_config(tmp_path, tmp_path / 'data')
    assert cfg['search']['providers'] == []
    assert not cfg['search']['enabled'] and not cfg['hunter']['enabled']
    assert not cfg['sheets']['enabled'] and not cfg['crawl']['commoncrawl']

def test_disjoint_seed_batches():
    seeds = list(map(str, range(24)))
    assert not set(select_seeds(seeds, '0')) & set(select_seeds(seeds, '1'))
    assert len(select_seeds(seeds, '1')) == 12

@pytest.mark.parametrize('batch', ['-1', '2', 'wrong'])
def test_bad_batch(batch):
    with pytest.raises(ValueError): select_seeds(list(map(str, range(24))), batch)

def test_timezone_morning_evening():
    seeds = list(map(str, range(24)))
    a = select_seeds(seeds, at=datetime(2026, 9, 8, 6, tzinfo=timezone.utc))
    b = select_seeds(seeds, at=datetime(2026, 9, 8, 15, tzinfo=timezone.utc))
    assert not set(a) & set(b)

def test_exports_allowlist():
    assert not any('key' in name or '.env' in name or 'sqlite' in name for name in EXPORT_NAMES)
