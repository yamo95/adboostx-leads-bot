"""Persist quota ledger and crawl state in a PRIVATE GitHub state branch.
No search keys, Google credentials or keys.env files are uploaded.
Missing/corrupt state fails closed instead of resetting usage counters.
"""
from __future__ import annotations
import argparse,base64,gzip,io,json,os,re,sqlite3,sys,tempfile
from pathlib import Path
from urllib.error import HTTPError,URLError
from urllib.request import Request,urlopen
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from leadengine.config import load_config
from leadengine.db import Database
BRANCH='leadengine-state'
STATE_FILE='state/leads.sqlite3.gz'
MAX_COMPRESSED=5*1024*1024
MAX_DB=80*1024*1024
class ApiError(RuntimeError):
    def __init__(self,status):
        self.status=status
        super().__init__('GitHub API failed (HTTP %s); state not reset.' % status)
def api(method,path,payload=None,raw=False):
    token=os.environ.get('GITHUB_TOKEN','')
    if not token:raise RuntimeError('GITHUB_TOKEN is required inside the Actions runner.')
    body=None if payload is None else json.dumps(payload).encode()
    req=Request('https://api.github.com/'+path,data=body,method=method,headers={
        'Authorization':'Bearer '+token,'User-Agent':'PublisherLeadEngine-CI',
        'Accept':'application/vnd.github.raw+json' if raw else 'application/vnd.github+json',
        'Content-Type':'application/json','X-GitHub-Api-Version':'2022-11-28'})
    try:
        with urlopen(req,timeout=45) as r:
            content=r.read(MAX_COMPRESSED+2*1024*1024)
            if len(content)>=MAX_COMPRESSED+2*1024*1024:raise RuntimeError('GitHub response exceeded size limit.')
            return content if raw else json.loads(content)
    except HTTPError as e:raise ApiError(e.code) from None
    except URLError:raise RuntimeError('GitHub network failure; state not reset.') from None
def repo_prefix():
    repo=os.environ.get('GITHUB_REPOSITORY','')
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+',repo):raise RuntimeError('A valid owner/repository is required.')
    p='repos/'+repo
    if not api('GET',p).get('private'):raise RuntimeError('Refusing to store contacts in a non-private repository.')
    return p
def file_meta(prefix):
    try:return api('GET',prefix+'/contents/'+STATE_FILE+'?ref='+BRANCH)
    except ApiError as e:
        if e.status==404:return None
        raise
def unpack_database(blob,target):
    if len(blob)>MAX_COMPRESSED:raise RuntimeError('Compressed state exceeds safety limit.')
    with gzip.GzipFile(fileobj=io.BytesIO(blob)) as gz:raw=gz.read(MAX_DB+1)
    if len(raw)>MAX_DB or not raw.startswith(b'SQLite format 3\x00'):raise RuntimeError('Invalid or oversized SQLite state; state not reset.')
    target=Path(target);target.parent.mkdir(parents=True,exist_ok=True)
    temp=target.with_suffix('.restoring')
    try:
        temp.write_bytes(raw)
        with sqlite3.connect(temp) as db:
            if db.execute('PRAGMA quick_check').fetchone()[0]!='ok':raise RuntimeError('Corrupt SQLite state.')
            tables={x[0] for x in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if not {'usage','sites','contacts','kv'}.issubset(tables):raise RuntimeError('Wrong database schema; state not reset.')
        temp.replace(target)
    finally:temp.unlink(missing_ok=True)
def packed_database(path):
    with tempfile.TemporaryDirectory() as td:
        out=Path(td)/'snapshot.sqlite3'
        with sqlite3.connect(path) as source,sqlite3.connect(out) as dest:source.backup(dest)
        if out.stat().st_size>MAX_DB:raise RuntimeError('Database exceeds CI state limit.')
        blob=gzip.compress(out.read_bytes(),compresslevel=6,mtime=0)
    if len(blob)>MAX_COMPRESSED:raise RuntimeError('Compressed database exceeds CI state limit.')
    return blob
def save_state(prefix,path,marker):
    if not Path(marker).exists():raise RuntimeError('Restore was not successful; refusing to overwrite remote state.')
    if not Path(path).exists():raise RuntimeError('Database missing; remote state left untouched.')
    meta=file_meta(prefix)
    payload={'message':'Persist publisher research state [skip ci]','branch':BRANCH,
        'content':base64.b64encode(packed_database(path)).decode()}
    if meta:payload['sha']=meta['sha']
    api('PUT',prefix+'/contents/'+STATE_FILE,payload)
def restore_state(prefix,path,marker,allow_initialize=False):
    Path(marker).unlink(missing_ok=True)
    meta=file_meta(prefix)
    if not meta:
        try:
            api('GET',prefix+'/git/ref/heads/'+BRANCH);branch_exists=True
        except ApiError as e:
            if e.status!=404:raise
            branch_exists=False
        if branch_exists or not allow_initialize:
            raise RuntimeError('State missing. Only a first manual run may initialize a NEW state branch. No searches made.')
        sha=os.environ.get('GITHUB_SHA','')
        if not re.fullmatch(r'[a-fA-F0-9]{40}',sha):raise RuntimeError('Missing valid commit SHA.')
        api('POST',prefix+'/git/refs',{'ref':'refs/heads/'+BRANCH,'sha':sha})
        Database(path)
        Path(marker).write_text('initialized',encoding='utf-8')
        save_state(prefix,path,marker)
    else:
        raw=api('GET',prefix+'/contents/'+STATE_FILE+'?ref='+BRANCH,raw=True)
        unpack_database(raw,path)
        Path(marker).write_text('restored',encoding='utf-8')
def main():
    ap=argparse.ArgumentParser();ap.add_argument('operation',choices=['restore','save']);args=ap.parse_args()
    cfg=load_config();directory=Path(cfg['data_dir']);directory.mkdir(parents=True,exist_ok=True)
    path=directory/'leads.sqlite3';marker=directory/'.ci-state-restored';prefix=repo_prefix()
    if args.operation=='restore':
        allow=os.getenv('INITIALIZE_STATE')=='true' and os.getenv('GITHUB_EVENT_NAME')=='workflow_dispatch'
        restore_state(prefix,path,marker,allow_initialize=allow)
    else:save_state(prefix,path,marker)
    print('Private crawl state '+args.operation+' completed. No credentials uploaded.')
if __name__=='__main__':main()
