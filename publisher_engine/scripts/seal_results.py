"""Public-key encryption: the runner never receives a decryption key."""
from __future__ import annotations
import base64
import hashlib
import json
import os
from pathlib import Path
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

AAD = b'PublisherLeadEngineEncrypted/v1'
FORMAT = 'publisher-leads-rsa-oaep-aesgcm-v1'

def seal(payload: dict, public_pem: bytes) -> dict:
    public = serialization.load_pem_public_key(public_pem)
    if not isinstance(public, rsa.RSAPublicKey) or public.key_size < 3072:
        raise ValueError('An RSA public key of at least 3072 bits is required')
    key, nonce = AESGCM.generate_key(bit_length=256), os.urandom(12)
    plaintext = json.dumps(payload, ensure_ascii=False, separators=(',', ':')).encode()
    ciphertext = AESGCM(key).encrypt(nonce, plaintext, AAD)
    wrapped = public.encrypt(key, padding.OAEP(mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(), label=None))
    der = public.public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
    b64 = lambda value: base64.b64encode(value).decode('ascii')
    return {'format': FORMAT, 'key_id': hashlib.sha256(der).hexdigest(),
            'wrapped_key': b64(wrapped), 'nonce': b64(nonce), 'ciphertext': b64(ciphertext)}

def write_sealed(payload: dict, public_key: Path, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    envelope = seal(payload, public_key.read_bytes())
    temporary = output.with_suffix('.tmp')
    temporary.write_text(json.dumps(envelope), encoding='utf-8')
    temporary.replace(output)
