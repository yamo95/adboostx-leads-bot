# Publisher Lead Engine - encrypted cloud mode

The cloud runner uses the existing 1.1 parsing, qualification and source-evidence engine.
It scans public example publisher sites and up to six related candidates per run.
Only an RSA PUBLIC key is stored here. The recovery key and private results viewer
are delivered separately to the operator and MUST NOT be committed to this repository.

## Active cloud mode

- Keyless scans: no search-provider keys, no Google credentials, and no messaging-account login.
- The public seed pool rotates in batches of 12. A bounded second pass may inspect six
  publicly linked or redirected candidates. This is not unlimited web discovery.
- Every run starts a new database. Results are dated snapshots, not a persistent CRM.
  Loading multiple runs in the private viewer can deduplicate contact routes locally.
- Artifacts contain aggregate counts and an encrypted results JSON. Source evidence,
  contact values, page diagnostics, and CSV exports are inside the encrypted envelope.
- No messages, forms, Telegram invitations, bot starts, downloads or CAPTCHA bypass.
- Standard GitHub-hosted Ubuntu runner. Do not switch to paid larger runners.
- Scheduled jobs can be delayed or disabled by GitHub. Public-repository schedules
  may be disabled after 60 days without repository activity. Artifact retention is 14 days.

## Read the results

Download the artifact from a completed `Encrypted Publisher Scan` Actions run,
unzip it and open `results.encrypted.json` in the private standalone Results Viewer.
The viewer operates locally. Never upload the recovery key or private viewer here.
A lost recovery key means existing encrypted reports cannot be decrypted.

## Local mode

`bash start.sh` starts the local dashboard. Local mode and cloud snapshots are distinct.
The full engine supports persistent SQLite and optional search providers / Google Sheets,
but these integrations are not activated in the keyless cloud runner.

## Tests

`python -m pip install -r requirements-dev.txt`
`python -m pytest -q`

The legacy private-state workflow under this subdirectory is retained for regression
fixtures only: GitHub does not execute nested `.github/workflows` folders.

Published contact routes do not establish activity, authority, site rights, or consent.
This is not an official AdMaven product or a guarantee of publisher approval.
