# Publisher Contacts - Delivered System

Operator workflow: `.github/workflows/publisher-delivered.yml`.
Results index: `publisher-delivered-results/index.json`.

This deployment is paired with the private HTML Results Viewer and recovery key delivered separately. Do not upload that viewer or key to this public repository. The public fingerprint is `eb9eb4640058a447025460219c89d7f417f7bf9c148d4c56d669eaf92ade4d5b`.

## Use

Open `Publisher_Contacts_Private_Viewer.html` locally. It can display the delivered initial report and refresh encrypted reports from the index. No API key, Python installation, or messaging login is needed for keyless mode. Export filtered rows to CSV before sharing them with your authorized team.

For a manual scan, open Actions > Publisher Contacts - Delivered System > Run workflow > main > all. Scheduled scans are configured for 09:00 and 18:00, Asia/Jerusalem. The browser and laptop do not need to remain running. GitHub schedules are not exact-time guarantees.

## Scope

This mode rotates 24 public seed websites in 12-site scheduled batches, plus at most 6 related or redirected candidate URLs. Each run is a new snapshot. It does not implement unlimited whole-web discovery, a persistent CRM, Google Sheets synchronization, or automated outreach. Website contact routes are not proof of account activity, ownership, authority, consent, or AdMaven approval.

The scanner respects robots and access restrictions. It does not install APKs, open video players, access private groups, solve CAPTCHAs, or send messages. Public-channel descriptions may expose a public business/support route; groups and bots are kept separate.

## Stability

The runner checks out the live-tested source commit `7cec53c93e8af76aa1077a28b88190f3a59cafda`. Editing staging files or other workflow keys does not silently change this scanner. To upgrade source, test the replacement and deliberately change that pinned commit. The workflow installs the matching public key and verifies its fingerprint before scanning and publishing.

The website-scanning step does not receive repository credentials. Publishing is a separate step that accepts only the encrypted envelope and aggregate counts. The private decryption key never enters the workflow.

The results index lists at most 60 snapshots. Older encrypted files may remain in Git history; this is not secure erasure. Notes entered in the viewer are browser-local and are not sent to GitHub.

## Pause

Disable **Publisher Contacts - Delivered System** in GitHub Actions to stop this deployment. Other workflows, if present, have independent controls. Do not use similarly named staging workflows as proof of this deployment's status.

## Platform limits

Standard GitHub-hosted runner time is free for public repositories under current GitHub terms; larger/private runners and other resources have separate rules. This workflow uses a standard Ubuntu runner and does not call paid search APIs. Acceptance artifacts are encrypted and retained for 3 days. GitHub may delay/drop scheduled jobs, and public schedules can be disabled after 60 days without repository activity.

Official references:
- https://docs.github.com/en/actions/reference/runners/github-hosted-runners
- https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule
