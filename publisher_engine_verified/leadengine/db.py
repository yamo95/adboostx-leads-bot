from __future__ import annotations
import json,sqlite3,hashlib
from pathlib import Path
from datetime import datetime,timezone,timedelta
from contextlib import contextmanager
from .models import now
from .urls import normalize_url,hostname,root_url,within_site

SCHEMA='''
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS sites (
 domain TEXT PRIMARY KEY,url TEXT NOT NULL,discovered_at TEXT NOT NULL,discovery_source TEXT,
 last_scan TEXT,final_url TEXT,classification TEXT NOT NULL DEFAULT 'PENDING',category TEXT,
 relevance INTEGER DEFAULT 0,reasons TEXT DEFAULT '[]',access_state TEXT DEFAULT 'pending',
 contact_state TEXT DEFAULT 'NOT_SCANNED',best_contact TEXT,priority INTEGER DEFAULT 0,
 manual_decision TEXT,manual_reason TEXT,notes TEXT DEFAULT '',suppressed INTEGER DEFAULT 0,
 alias_of TEXT,compliance_review TEXT DEFAULT 'REQUIRED');
CREATE TABLE IF NOT EXISTS contacts (
 id TEXT PRIMARY KEY,domain TEXT NOT NULL,kind TEXT,value TEXT,source_url TEXT,evidence TEXT,
 method TEXT,purpose TEXT,association TEXT,verification TEXT,score INTEGER,tier TEXT,
 observed_at TEXT,last_seen TEXT,active INTEGER DEFAULT 1,contact_url TEXT,notes TEXT,
 UNIQUE(domain,kind,value,source_url));
CREATE INDEX IF NOT EXISTS contacts_domain ON contacts(domain);
CREATE INDEX IF NOT EXISTS contacts_value ON contacts(kind,value);
CREATE TABLE IF NOT EXISTS pages (
 id INTEGER PRIMARY KEY,domain TEXT,url TEXT,final_url TEXT,status INTEGER,state TEXT,error TEXT,
 fetched_at TEXT,content_hash TEXT,title TEXT);
CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY,at TEXT,level TEXT,message TEXT);
CREATE TABLE IF NOT EXISTS runs (id INTEGER PRIMARY KEY,started_at TEXT,ended_at TEXT,state TEXT,summary TEXT);
CREATE TABLE IF NOT EXISTS usage (provider TEXT,period TEXT,units INTEGER NOT NULL,PRIMARY KEY(provider,period));
CREATE TABLE IF NOT EXISTS search_cache (provider TEXT,query TEXT,at TEXT,results TEXT,PRIMARY KEY(provider,query));
CREATE TABLE IF NOT EXISTS aliases (alias TEXT PRIMARY KEY,canonical TEXT,proof_url TEXT,observed_at TEXT);
CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY,value TEXT);
'''

class Database:
    def __init__(self,path: str | Path):
        self.path=str(path)
        Path(self.path).parent.mkdir(parents=True,exist_ok=True)
        with self.connect() as c: c.executescript(SCHEMA)
    @contextmanager
    def connect(self):
        c=sqlite3.connect(self.path,timeout=20)
        c.row_factory=sqlite3.Row
        try:
            yield c
            c.commit()
        except Exception:
            c.rollback();raise
        finally: c.close()
    def rows(self,sql,args=()):
        with self.connect() as c: return [dict(r) for r in c.execute(sql,args)]
    def event(self,message,level='info'):
        with self.connect() as c: c.execute('INSERT INTO events(at,level,message) VALUES(?,?,?)',(now(),level,str(message)[:2000]))
    def add_site(self,url,source='manual'):
        clean=normalize_url(url);domain=hostname(clean)
        with self.connect() as c:
            exists=c.execute('SELECT domain FROM sites WHERE domain=?',(domain,)).fetchone() or c.execute('SELECT canonical FROM aliases WHERE alias=?',(domain,)).fetchone()
            if exists:return False
            c.execute('INSERT INTO sites(domain,url,discovered_at,discovery_source) VALUES(?,?,?,?)',(domain,root_url(clean),now(),str(source)[:1000]))
        return True
    def candidates(self,limit,revisit_days=7,force=False,only=None):
        args=[];where='suppressed=0 AND alias_of IS NULL'
        if only:
            domains=[hostname(x) for x in only];where+=' AND domain IN ('+','.join('?'*len(domains))+')';args+=domains
        if not force:
            where+=" AND (manual_decision IS NULL OR manual_decision!='REJECT') AND (last_scan IS NULL OR last_scan<?)"
            args.append((datetime.now(timezone.utc)-timedelta(days=revisit_days)).isoformat())
        # Unseen first, then least recently checked. No unreachable => irrelevant shortcut.
        return self.rows(f'SELECT * FROM sites WHERE {where} ORDER BY last_scan IS NOT NULL,last_scan,discovered_at LIMIT ?',(*args,limit))
    def save_result(self,domain,result,contacts,pages):
        with self.connect() as c:
            c.execute('UPDATE contacts SET active=0 WHERE domain=?',(domain,))
            for x in contacts:
                d=x.dict() if hasattr(x,'dict') else dict(x)
                cid=hashlib.sha256((domain+'|'+d['kind']+'|'+d['value']+'|'+d['source_url']).encode()).hexdigest()[:24]
                vals=(cid,domain,d['kind'],d['value'],d['source_url'],d['evidence'],d['method'],d['purpose'],d['association'],d['verification'],d['score'],d['tier'],d['observed_at'],d['observed_at'],1,d.get('contact_url',''),json.dumps(d.get('notes',[])))
                c.execute('''INSERT INTO contacts VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET
                  evidence=excluded.evidence,method=excluded.method,purpose=excluded.purpose,association=excluded.association,
                  verification=excluded.verification,score=excluded.score,tier=excluded.tier,last_seen=excluded.last_seen,
                  active=1,contact_url=excluded.contact_url,notes=excluded.notes''',vals)
            for p in pages:
                c.execute('INSERT INTO pages(domain,url,final_url,status,state,error,fetched_at,content_hash,title) VALUES(?,?,?,?,?,?,?,?,?)',
                  (domain,p.url,p.final_url,p.status,p.state,p.error[:500],p.fetched_at,p.content_hash,''))
            allowed={'final_url','classification','category','relevance','reasons','access_state','contact_state','best_contact','priority','alias_of'}
            updates={k:(json.dumps(v,ensure_ascii=False) if isinstance(v,(list,dict)) else v) for k,v in result.items() if k in allowed}
            updates['last_scan']=now()
            keys=','.join(k+'=?' for k in updates)
            c.execute(f'UPDATE sites SET {keys} WHERE domain=?',(*updates.values(),domain))
            final=result.get('final_url','')
            original=c.execute('SELECT url FROM sites WHERE domain=?',(domain,)).fetchone()
            if final and original and within_site(final,original['url']) and hostname(final)!=domain:
                alias=hostname(final)
                c.execute('INSERT INTO aliases VALUES(?,?,?,?) ON CONFLICT(alias) DO UPDATE SET canonical=excluded.canonical,proof_url=excluded.proof_url,observed_at=excluded.observed_at',(alias,domain,final,now()))
                c.execute('UPDATE sites SET alias_of=? WHERE domain=? AND manual_decision IS NULL',(domain,alias))
    def set_override(self,domain,decision,reason=''):
        if decision not in {'PASS','REJECT',None}:raise ValueError('Decision must be PASS, REJECT, or null')
        with self.connect() as c:
            n=c.execute('UPDATE sites SET manual_decision=?,manual_reason=? WHERE domain=?',(decision,reason[:500],domain)).rowcount
        return bool(n)
    def suppress(self,domain,on=True):
        with self.connect() as c: return bool(c.execute('UPDATE sites SET suppressed=? WHERE domain=?',(int(on),domain)).rowcount)
    def purge(self,domain):
        with self.connect() as c:
            for table in ['contacts','pages']:c.execute(f'DELETE FROM {table} WHERE domain=?',(domain,))
            # Keep a suppression tombstone so automatic discovery cannot re-create this record.
            c.execute("UPDATE sites SET suppressed=1,notes='Purged; do not rediscover',best_contact=NULL,contact_state='PURGED',discovery_source='',reasons='[]' WHERE domain=?",(domain,))
    def reserve(self,provider,units,limit,period):
        key='lifetime' if period=='lifetime' else datetime.now(timezone.utc).strftime('%Y-%m')
        with self.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            row=c.execute('SELECT units FROM usage WHERE provider=? AND period=?',(provider,key)).fetchone()
            used=row['units'] if row else 0
            if used+units>limit:return False
            c.execute('INSERT INTO usage VALUES(?,?,?) ON CONFLICT(provider,period) DO UPDATE SET units=excluded.units',(provider,key,used+units))
        return True
    def get_cache(self,provider,query,days):
        rows=self.rows('SELECT * FROM search_cache WHERE provider=? AND query=?',(provider,query))
        if rows and rows[0]['at']>(datetime.now(timezone.utc)-timedelta(days=days)).isoformat():return json.loads(rows[0]['results'])
        return None
    def cache(self,provider,query,results):
        with self.connect() as c:c.execute('INSERT INTO search_cache VALUES(?,?,?,?) ON CONFLICT(provider,query) DO UPDATE SET at=excluded.at,results=excluded.results',(provider,query,now(),json.dumps(results)))
    def get(self,key,default=''):
        rows=self.rows('SELECT value FROM kv WHERE key=?',(key,));return rows[0]['value'] if rows else default
    def put(self,key,value):
        with self.connect() as c:c.execute('INSERT INTO kv VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',(key,str(value)))
    def retention(self,days):
        cutoff=(datetime.now(timezone.utc)-timedelta(days=days)).isoformat()
        with self.connect() as c:
            c.execute('DELETE FROM contacts WHERE last_seen<?',(cutoff,))
            c.execute("UPDATE sites SET best_contact=NULL,priority=0,contact_state='STALE' WHERE last_scan<? AND best_contact IS NOT NULL",(cutoff,))
            c.execute('DELETE FROM pages WHERE fetched_at<?',(cutoff,))
            c.execute('DELETE FROM events WHERE at<?',(cutoff,))
