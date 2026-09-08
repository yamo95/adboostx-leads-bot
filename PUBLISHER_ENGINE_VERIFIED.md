# Verified Publisher Engine

Runnable full local engine and bounded keyless cloud mode are in `publisher_engine_verified/`.

The workflow **Publisher Engine - Verified Encrypted Scan** runs on standard public Ubuntu runners. It has no paid search API keys and never sends outreach. Its own schedule is **09:15 and 18:15 Asia/Jerusalem**. GitHub can delay or drop scheduled executions. This is a scheduled job, not a continuously running web server.

This separate directory avoids overwriting other work in this repository. The original bot and other workflows were not modified by this installation.

Cloud mode rotates two batches across 24 configured public seed sites, with up to six bounded related-domain follow-ups per run. It does not discover the entire web. General search and Google Sheets are available in the local source, but are not connected in cloud keyless mode.

## Results

Only encrypted reports and aggregate counts are committed under `publisher-engine-results/`. Contact values, phone numbers, and email addresses are not published in plaintext. GitHub Actions artifacts also contain ciphertext only.

The private Results Viewer delivered in the chat imports and decrypts these reports on the operator's device. Its recovery key must never be uploaded to this public repository. Keep a private backup. The key ID for this verified workflow is `6e931aa19f4d1945946add3fc84ea0368ed0624f829eb70c5a29869a0b72e3a2`.

The output index references at most 60 recent snapshots. Older encrypted commits remain in Git history. Deleting the index does not erase Git history. Each run is a fresh scan; the viewer merges current site snapshots and contact evidence. Counts are not counts of unique people, active accounts, consent or approved publishers.

## Controls

GitHub Actions > Publisher Engine - Verified Encrypted Scan > Run workflow runs a bounded manual batch. The workflow's menu can disable this schedule. `publisher_engine_verified/seeds.txt` controls the seed list. Changing only this verified engine does not modify the other installed scanner.

## Verification

Initial live full-engine pilot opened 42 HTML pages across 12 seeded sites on 8 September 2026. The next release adds reconciliation so a known Telegram channel cannot reappear as a direct contact via an unchecked duplicate. 165 regression and privacy tests pass locally. Review workflow runs for cloud test and live scan results; a green run is not a guarantee of high-quality contacts on every site.

Some sites refuse requests, disallow crawling, require JavaScript, or publish no direct business contact. These limitations are recorded rather than bypassed. No CAPTCHA solving, logins, APK/media downloads, account enumeration or private group access is performed.
