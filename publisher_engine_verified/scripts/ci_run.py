"""Bounded run leaves time for state persistence and output upload."""
from __future__ import annotations
import asyncio,json,os,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from leadengine.config import load_config
from leadengine.engine import Engine
from leadengine.export import write_exports
async def main():
    cfg=load_config();cfg['schedule']['enabled']=False;cfg['crawl']['site_timeout_seconds']=100
    engine=Engine(cfg);code=0
    try:
        result=await asyncio.wait_for(engine.run(discover=True,limit=20),timeout=14*60)
    except asyncio.TimeoutError:
        result={'state':'TIME_BUDGET_EXHAUSTED','detail':'Partial database retained for next run.'};code=2
    finally:write_exports(engine.db,cfg)
    print(json.dumps(result,indent=2))
    Path(cfg['data_dir'],'ci_result.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    if os.getenv('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'],'a',encoding='utf-8') as f:
            f.write('## Publisher research run\n\n```json\n'+json.dumps(result,indent=2)+'\n```\n')
            f.write('\nContact evidence is not mailbox verification or outreach consent.\n')
    return code
if __name__=='__main__':raise SystemExit(asyncio.run(main()))
