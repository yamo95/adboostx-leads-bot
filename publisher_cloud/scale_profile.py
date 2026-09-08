"""Capacity profile for the existing B219 engine; no new service or key.

Keeps the current extraction rules, directory allowlist, URL guards, per-host
pacing and encrypted output. Scheduled runs scan <=120 seed sites. An explicit
'all' acceptance run scans <=240 seed sites. Both may add <=12 related sites.
"""
from datetime import datetime
from zoneinfo import ZoneInfo
import quantity_expansion as q

SCHEDULED_LIMIT = 120
ACCEPTANCE_LIMIT = 240
RELATED_LIMIT = 12


def select_candidates(seeds, batch='auto', now=None):
    if not seeds:
        return []
    if batch == 'all':
        return list(seeds[:ACCEPTANCE_LIMIT])
    if batch == 'auto':
        local = now or datetime.now(ZoneInfo('Asia/Jerusalem'))
        slot = (local.toordinal() - datetime(2026, 9, 8).toordinal()) * 2 + int(local.hour >= 15)
    else:
        slot = int(batch)
        if slot < 0:
            raise ValueError('Batch must be non-negative')
    count = min(SCHEDULED_LIMIT, len(seeds))
    start = slot * SCHEDULED_LIMIT % len(seeds)
    return [seeds[(start + offset) % len(seeds)] for offset in range(count)]


def main():
    old = q.choose, q.BATCH_SIZE, q.MAX_RELATED
    q.choose = select_candidates
    q.BATCH_SIZE = SCHEDULED_LIMIT
    q.MAX_RELATED = RELATED_LIMIT
    try:
        return q.main()
    finally:
        q.choose, q.BATCH_SIZE, q.MAX_RELATED = old


if __name__ == '__main__':
    raise SystemExit(main())
