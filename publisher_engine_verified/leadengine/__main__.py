from __future__ import annotations
import argparse,asyncio,json,os,sys
from pathlib import Path
from .config import load_config
from .engine import Engine
from .export import write_exports

def main():
    parser=argparse.ArgumentParser(description='Source-backed publisher contact discovery')
    parser.add_argument('--config',default=None)
    sub=parser.add_subparsers(dest='command',required=True)
    serve=sub.add_parser('serve');serve.add_argument('--host',default='127.0.0.1');serve.add_argument('--port',default=8000,type=int)
    run=sub.add_parser('run');run.add_argument('--no-discovery',action='store_true');run.add_argument('--force',action='store_true');run.add_argument('--limit',type=int);run.add_argument('--only',nargs='+')
    add=sub.add_parser('add');add.add_argument('urls',nargs='+')
    override=sub.add_parser('override');override.add_argument('domain');override.add_argument('decision',choices=['PASS','REJECT','CLEAR']);override.add_argument('--reason',default='')
    sub.add_parser('export');sub.add_parser('status');sub.add_parser('sync-sheets');sub.add_parser('doctor')
    args=parser.parse_args();cfg=load_config(args.config);engine=Engine(cfg)
    if args.command=='serve':
        if args.host not in {'127.0.0.1','localhost','::1'} and not os.getenv('DASHBOARD_TOKEN'):
            sys.exit('Remote binding requires DASHBOARD_TOKEN. Use localhost for a private dashboard.')
        import uvicorn
        from .api import create_app
        uvicorn.run(create_app(cfg),host=args.host,port=args.port,workers=1)
    elif args.command=='run':
        if args.limit is not None and not 1<=args.limit<=500:sys.exit('--limit must be 1..500')
        print(json.dumps(asyncio.run(engine.run(discover=not args.no_discovery,force=args.force,only=args.only,limit=args.limit)),indent=2))
    elif args.command=='add':
        for url in args.urls:print(url,'added' if engine.db.add_site(url,'cli') else 'already present')
    elif args.command=='override':engine.db.set_override(args.domain,None if args.decision=='CLEAR' else args.decision,args.reason)
    elif args.command=='export':print(write_exports(engine.db,cfg))
    elif args.command=='status':print(json.dumps(engine.db.rows('SELECT domain,classification,contact_state,last_scan FROM sites'),indent=2))
    elif args.command=='sync-sheets':
        from .sheets import sync_sheets
        print(sync_sheets(engine.db,cfg))
    elif args.command=='doctor':
        from .providers import KEYS
        print('Python:',sys.version.split()[0]);print('Data directory:',cfg['data_dir'])
        for provider,key in KEYS.items():print(provider+':','configured' if os.getenv(key) else 'not configured (optional)')
        print('Schedule:',cfg['schedule'])
        print('Network and API credentials are not validated by doctor. Run a small live scan to validate them.')
if __name__=='__main__':main()
