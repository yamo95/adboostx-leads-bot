# Active publisher contact desk

The single scheduled workflow is `.github/workflows/publisher-private-viewer.yml`.
It uses `publisher_cloud/recipient-b219c932.pem`, paired with the private access archive delivered to the operator in ChatGPT. The private key is not in this repository.

Live acceptance run: https://github.com/yamo95/adboostx-leads-bot/actions/runs/34266814176
This run scanned 27 sites, opened 92 pages, and recorded 11 unique published messaging routes. Published routes are not verified accounts, identity, authority, consent or AdMaven approval.

Schedule: 09:00 and 18:00 Asia/Jerusalem, subject to GitHub delays and account/workflow availability. No automatic outreach is performed. Keyless discovery is limited to the configured seed websites plus bounded related-site/redirect candidates. Broad search API accounts and Google Sheets are not connected.

Open the private HTML viewer to read `publisher-results/index.json`, decrypt matching snapshots and export CSV. Keep the HTML and recovery key private. Encrypted historical snapshots remain in Git history.

Earlier setup workflows are preserved in Git history, and a snapshot is archived in `.github/retired-workflows-20260908`, outside the active workflow directory. This prevents duplicate future scheduled scans and conflicting encryption keys. Existing result files and the original user bot were not removed.
