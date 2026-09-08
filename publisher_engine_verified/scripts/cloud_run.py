"""Bounded, keyless live scans with encrypted artifacts and no plaintext public state.

Every run is a fresh snapshot. This mode never uses billable search APIs, even if
someone configured API keys elsewhere. Local/full private deployment is separate.
"""
from __future__ import annotations
import asyncio
from collections import Counter
from datetime import datetime, timezone
import io
import json
import os
from pathlib import Path
import sys
import tempfile
from contextlib import redirect_stdout, redirect_stderr
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from leadengine.config import load_config
from leadengine.engine import Engine
from leadengine.export import effective_contacts, lead_rows, write_exports
from scripts.seal_results import write_sealed

EXPORT_NAMES = {'leads.csv', 'contacts.csv', 'ready.csv', 'contact_clusters.csv', 'results.json'}

def select_seeds(seeds: list[str], batch: str = 'auto', at: datetime | None = None, size: int = 12) -> list[str]:
    if not seeds:
        raise ValueError('No public seed websites configured')
    batches = max(1, (len(seeds) + size - 1) // size)
    if batch == 'auto':
        local = (at or datetime.now(timezone.utc)).astimezone(ZoneInfo('Asia/Jerusalem'))
        slot = 0 if local.hour < 15 else 1
        index = (local.toordinal() * 2 + slot) % batches
    else:
        index = int(batch)
        if not 0 <= index < batches:
            raise ValueError('Seed batch outside the configured range')
    return seeds[index * size:(index + 1) * size]

def public_config(base: Path, data: Path) -> dict:
    cfg = load_config(str(ROOT / 'config.yaml'))
    cfg['base_dir'], cfg['data_dir'] = str(base), str(data)
    data.mkdir(parents=True, exist_ok=True)
    cfg['crawl'].update(concurrency=3, max_sites_per_run=12, max_pages_per_site=8,
        max_public_profiles_per_site=6, site_timeout_seconds=100,
        request_timeout_seconds=15, delay_seconds=1.5, commoncrawl=False,
        external_candidates_per_site=3)
    cfg['search'].update(enabled=False, providers=[], contact_queries_per_run=0)
    cfg['hunter']['enabled'] = False
    cfg['sheets'].update(enabled=False, auto_sync_after_run=False)
    cfg['schedule']['enabled'] = False
    return cfg

async def scan(engine: Engine) -> list[dict]:
    summaries = [await engine.run(discover=False, limit=12)]
    # Only a bounded follow-up of public related links / redirects, not general web search.
    pending = engine.db.candidates(6, revisit_days=7)
    if pending:
        summaries.append(await engine.run(discover=False, limit=6))
    return summaries

def main() -> int:
    seeds = [s.strip() for s in (ROOT / 'seeds.txt').read_text().splitlines()
             if s.strip() and not s.lstrip().startswith('#')]
    selected = select_seeds(seeds, os.getenv('SEED_BATCH', 'auto'))
    artifact_dir = ROOT / 'sealed'
    artifact_dir.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='publisher-snapshot-') as folder:
        work = Path(folder)
        (work / 'seeds.txt').write_text('\n'.join(selected) + '\n', encoding='utf-8')
        cfg = public_config(work, work / 'data')
        engine = Engine(cfg)
        log = io.StringIO()
        summaries, failure = [], ''
        with redirect_stdout(log), redirect_stderr(log):
            try:
                summaries = asyncio.run(scan(engine))
            except BaseException as error:
                failure = type(error).__name__
        write_exports(engine.db, cfg)
        contacts, leads = effective_contacts(engine.db, cfg), lead_rows(engine.db, cfg)
        pages = engine.db.rows('SELECT domain,url,final_url,status,state,error,fetched_at,content_hash FROM pages')
        checked = [lead for lead in leads if lead.get('last_scan')]
        opened = sum(page['state'] == 'ok' for page in pages)
        unique_routes = {(c['kind'], c['value'].casefold()) for c in contacts
                         if c['kind'] in {'telegram', 'whatsapp', 'email'} and c['tier'] in {'READY', 'REVIEW'}}
        messenger_routes = {(c['kind'], c['value'].casefold()) for c in contacts
                            if c['kind'] in {'telegram', 'whatsapp'} and c['tier'] in {'READY', 'REVIEW'}}
        summary = {'mode': 'keyless_encrypted_snapshot', 'run_id': os.getenv('GITHUB_RUN_ID', 'local'),
            'created_at': datetime.now(timezone.utc).isoformat(), 'seed_pool': len(seeds),
            'selected_seeds': len(selected), 'sites_checked': len(checked), 'html_pages_opened': opened,
            'relevant_sites': sum(l['effective_classification'] == 'PASS' for l in checked),
            'contact_evidence_records': len(contacts), 'unique_contact_routes_for_review': len(unique_routes),
            'unique_messaging_routes_for_review': len(messenger_routes),
            'ready_sites': sum(l['effective_classification'] == 'PASS' and l['contact_state'] == 'READY' for l in checked),
            'access_states': dict(Counter(l.get('access_state', 'unknown') for l in checked)),
            'failure_type': failure,
            'status': 'LIVE_SCAN_COMPLETE' if not failure and opened else 'NEEDS_ATTENTION',
            'notice': 'Published routes are not verified accounts or consent. This is a fresh snapshot; no automatic outreach.'}
        files = {name: (Path(cfg['data_dir']) / 'exports' / name).read_text(encoding='utf-8')
                 for name in sorted(EXPORT_NAMES) if (Path(cfg['data_dir']) / 'exports' / name).exists()}
        files['page_diagnostics.json'] = json.dumps(pages, ensure_ascii=False, indent=2)
        files['events.json'] = json.dumps(engine.db.rows('SELECT at,level,message FROM events'), ensure_ascii=False, indent=2)
        payload = {'summary': summary, 'files': files, 'runs': summaries}
        write_sealed(payload, ROOT / 'recipient.pem', artifact_dir / 'results.encrypted.json')
        # Only aggregate counts are public. No URLs, handles, phone numbers, or secret-bearing logs.
        (artifact_dir / 'summary.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
        print(json.dumps(summary, indent=2))
        step_summary = os.getenv('GITHUB_STEP_SUMMARY')
        if step_summary:
            with open(step_summary, 'a', encoding='utf-8') as out:
                out.write('# Encrypted publisher scan\n\n')
                out.write(f"**{summary['status']}** | Sites checked: {len(checked)} | HTML pages opened: {opened}\n\n")
                out.write(f"Messaging routes requiring review: {len(messenger_routes)}. Account activity and ownership are not verified.\n\n")
                out.write('Download the encrypted artifact and open it with your private Results Viewer. No contact values appear in these logs.\n')
        return 0 if summary['status'] == 'LIVE_SCAN_COMPLETE' else 1

if __name__ == '__main__':
    raise SystemExit(main())
