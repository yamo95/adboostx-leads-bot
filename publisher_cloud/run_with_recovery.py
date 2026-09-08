"""Add a recovery envelope without changing the active recipient or exposing plaintext.

Only public keys are used on the runner. The operator recovery private key is
provided in the private local viewer, never in this repository. The primary
format remains backward compatible; older viewers ignore recovery_envelopes.
"""
from pathlib import Path
import hashlib
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
import scan

RECOVERY_KEY_ID = 'cd45f07300c0eecd1908e6c5af8a3b58d53e809596e2483f348d72c25ead3863'

def install_recovery():
    public_bytes = (Path(__file__).resolve().parent / 'recovery-recipient-cd45.pem').read_bytes()
    key = serialization.load_pem_public_key(public_bytes)
    if not isinstance(key, rsa.RSAPublicKey) or key.key_size < 3072:
        raise ValueError('Invalid recovery public key')
    der = key.public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
    if hashlib.sha256(der).hexdigest() != RECOVERY_KEY_ID:
        raise ValueError('Recovery public-key fingerprint mismatch')
    primary_seal = scan.seal
    def seal_with_recovery(payload, primary_public):
        envelope = primary_seal(payload, primary_public)
        if envelope.get('key_id') != RECOVERY_KEY_ID:
            envelope['recovery_envelopes'] = [primary_seal(payload, public_bytes)]
        return envelope
    scan.seal = seal_with_recovery

if __name__ == '__main__':
    install_recovery()
    raise SystemExit(scan.main())
