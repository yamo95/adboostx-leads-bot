# Stable private operator output

`scan.py` wraps the unchanged tested implementation in `scanner_core.py`. Normal workflow outputs and existing primary-key checks remain intact. In addition, each scan emits an AES-GCM/RSA-OAEP encrypted operator copy using public key `recipient-b219c932.pem`, whose private counterpart was delivered in the private access archive. No private key enters the repository or runner.

After publication, the private viewer reads `private-b219-results/index.json` and the encrypted files it references. A primary workflow key rotation does not by itself change this operator key. The operator key must be changed deliberately with a corresponding private access delivery.

The one-time `operator-acceptance-b219.yml` workflow has no schedule. Normal scheduled scanner workflows continue to call the preserved `scan.main` and `scan.publish` interfaces. No messages are sent. Source collection has no repository credentials; publication happens in a separate step.

The index keeps up to 60 snapshots, but older ciphertext can remain in Git history. All source-published contacts require human review; they are not verified identities or consent records. Keyless discovery remains bounded to the configured seeds and related-site links.
