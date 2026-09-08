import pytest
from scripts.publish_snapshot import validate
from scripts.seal_results import seal
from pathlib import Path

@pytest.fixture
def pair():
    env = seal({'contacts': ['private-example']}, (Path(__file__).parents[1] / 'recipient.pem').read_bytes())
    return env, {'created_at': '2026-09-08T18:00:00+00:00', 'sites_checked': 12, 'status': 'LIVE_SCAN_COMPLETE'}

def test_valid(pair):
    assert validate(*pair)['sites_checked'] == 12

def test_no_arbitrary_public_fields(pair):
    env, summary = pair
    summary['contact'] = '@not-to-publish'
    assert 'contact' not in validate(env, summary)

def test_reject_extra_envelope_field(pair):
    env, summary = pair
    env['contact'] = '@not-to-publish'
    with pytest.raises(ValueError): validate(env, summary)

def test_reject_wrong_key(pair):
    env, summary = pair
    env['key_id'] = 'a' * 64
    with pytest.raises(ValueError): validate(env, summary)

@pytest.mark.parametrize('field,value', [('nonce', 'bad'), ('wrapped_key',''), ('ciphertext','')])
def test_invalid_binary(pair, field, value):
    env, summary = pair
    env[field] = value
    with pytest.raises((ValueError, __import__('binascii').Error)): validate(env, summary)

def test_reject_contact_in_count(pair):
    env, summary = pair
    summary['sites_checked'] = '@somebody'
    with pytest.raises(ValueError): validate(env, summary)

def test_reject_contact_in_time(pair):
    env, summary = pair
    summary['created_at'] = '@somebody'
    with pytest.raises(ValueError): validate(env, summary)
