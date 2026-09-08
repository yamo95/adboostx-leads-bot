from __future__ import annotations
import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo

async def scheduler_loop(app):
    """In-process scheduler. No catch-up flood; 5-minute start window and persistent slot deduplication."""
    while True:
        cfg=app.state.engine.cfg;db=app.state.engine.db;schedule=cfg['schedule']
        if schedule['enabled']:
            local=datetime.now(ZoneInfo(schedule['timezone']))
            for slot in schedule['times']:
                hour,minute=map(int,slot.split(':')[:2])
                offset=local.hour*60+local.minute-(hour*60+minute)
                key='schedule:'+local.strftime('%Y-%m-%d')+':'+slot
                if 0<=offset<5 and not db.get(key):
                    job=app.state.job
                    if job is None or job.done():
                        db.put(key,'started');app.state.job=asyncio.create_task(app.state.do_run())
        await asyncio.sleep(20)
