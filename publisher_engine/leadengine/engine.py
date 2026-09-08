from __future__ import annotations
import asyncio,json
from pathlib import Path
from urllib.parse import urljoin,urlsplit
from datetime import datetime,timezone,timedelta
from xml.etree import ElementTree
from filelock import FileLock,Timeout as LockTimeout
from .config import load_config
from .db import Database
from .fetch import Fetcher
from .providers import Providers
from .parse import parse_page,contact_page_links,external_candidates,COMMON_PATHS,CONTACT_TERMS,messaging_key
from .classify import classify
from .quality import score_contacts,MailDNS
from .models import now
from .urls import hostname,root_url,within_site,normalize_url,excluded

class Engine:
    def __init__(self,cfg=None,db=None):
        self.cfg=cfg or load_config();self.db=db or Database(Path(self.cfg['data_dir'])/'leads.sqlite3')
        self.busy=False
        self.run_lock=FileLock(str(Path(self.cfg['data_dir'])/'run.lock'))
        self.dns=MailDNS();self.contact_queries=0;self.hunter_domains=0
    def seeds(self):
        path=Path(self.cfg['base_dir'])/'seeds.txt';count=0
        if path.exists():
            for line in path.read_text(encoding='utf-8').splitlines():
                line=line.strip()
                if line and not line.startswith('#'):
                    try:count+=self.db.add_site(line,'seed')
                    except ValueError:self.db.event('Invalid seed skipped','warning')
        return count
    async def discover(self,providers):
        if not self.cfg['search']['enabled']:return 0
        if not providers.available():
            self.db.event('No search keys configured: seed / partner-link mode only. Add a free provider key for broad discovery.','warning');return 0
        path=Path(self.cfg['base_dir'])/'queries.txt'
        queries=[x.strip() for x in path.read_text(encoding='utf-8').splitlines() if x.strip() and not x.startswith('#')] if path.exists() else []
        if not queries:return 0
        cursor=int(self.db.get('query_cursor','0'));added=0
        for i in range(min(self.cfg['search']['queries_per_run'],len(queries))):
            q=queries[(cursor+i)%len(queries)]
            known=self.db.rows('SELECT domain FROM sites WHERE last_scan IS NOT NULL ORDER BY last_scan DESC LIMIT 10')
            for item in known:
                term=' -site:'+item['domain']
                if len(q)+len(term)<=450:q+=term
            results=await providers.search(q)
            for result in results:
                if excluded(result['url']):continue
                try:added+=self.db.add_site(result['url'],f"{result['provider']}: {q} | {result['url']}")
                except ValueError:pass
        self.db.put('query_cursor',(cursor+min(self.cfg['search']['queries_per_run'],len(queries)))%len(queries))
        return added
    async def sitemap_paths(self,fetcher,base):
        policy=await fetcher.policy(base)
        if not policy.allowed:return []
        # Fetch at most one sitemap (or its first same-site child). Never enumerate the whole catalog.
        urls=[u for u in policy.sitemaps if within_site(u,base)][:1] or [urljoin(base,'sitemap.xml')]
        out=[]
        for _ in range(2):
            if not urls:break
            url=urls.pop(0);page=await fetcher.fetch(url,text_mode=True,allowed_root=base)
            if page.state!='ok':break
            try:root=ElementTree.fromstring(page.html)
            except (ElementTree.ParseError,ValueError):break
            locs=[(el.text or '').strip() for el in root.iter() if el.tag.rsplit('}',1)[-1]=='loc'][:1000]
            if root.tag.rsplit('}',1)[-1]=='sitemapindex':
                # A small post/page sitemap is useful; large media maps are intentionally skipped.
                candidates=[x for x in locs if within_site(x,base) and ('page' in x or 'post' in x)]
                urls=candidates[:1];continue
            for val in locs:
                if within_site(val,base) and CONTACT_TERMS.search(urlsplit(val).path):
                    try:out.append(normalize_url(val))
                    except ValueError:pass
            break
        return out[:12]
    async def scan_site(self,site,fetcher,providers):
        domain=site['domain'];base=site['url'];pages=[];parsed=[];contacts=[]
        self.db.event(f'Scanning {domain}')
        home=await fetcher.fetch(base);pages.append(home)
        if home.state!='ok':
            result={'final_url':home.final_url,'classification':'REVIEW','category':'unknown','relevance':0,
                    'reasons':['Access failed: '+home.state+'; not classified as irrelevant.'],
                    'access_state':home.state,'contact_state':'NOT_CHECKED','best_contact':None,'priority':0}
            self.db.save_result(domain,result,[],pages);return result
        if not within_site(home.final_url,base):
            try:self.db.add_site(home.final_url,'cross-domain redirect from '+base)
            except ValueError:pass
            result={'final_url':home.final_url,'classification':'REVIEW','category':'redirect','relevance':0,
                    'reasons':['Cross-domain redirect; target queued separately, ownership NOT assumed.'],
                    'access_state':'external_redirect','contact_state':'REVIEW_TARGET','best_contact':None,'priority':0}
            self.db.save_result(domain,result,[],pages);return result
        parsed.append(parse_page(home.html,home.final_url));contacts+=parsed[0].contacts
        queue=contact_page_links(parsed[0],base)
        # One evidence page can rescue a single-app homepage without requiring a catalog.
        for link in parsed[0].links:
            if within_site(link['url'],base) and ('download' in link['label'].lower() or '/download' in link['url']):
                try:ev=normalize_url(link['url'])
                except ValueError:continue
                if ev not in queue:queue.append(ev)
                break
        for url in external_candidates(parsed[0],base,self.cfg['crawl']['external_candidates_per_site']):
            self.db.add_site(url,'editorial link from '+home.final_url)
        if self.cfg['crawl']['sitemap']:
            queue+=await self.sitemap_paths(fetcher,home.final_url)
        if self.cfg['crawl']['probe_common_paths']:
            # Probing common HTML pages is bounded; no brute-force directory or username search.
            queue+=[urljoin(home.final_url,p) for p in COMMON_PATHS]
        seen={base,home.final_url};maximum=self.cfg['crawl']['max_pages_per_site']
        async def walk(cap=None):
            cap=maximum if cap is None else cap
            while queue and len(pages)<cap:
                url=queue.pop(0)
                if url in seen:continue
                seen.add(url)
                p=await fetcher.fetch(url,allowed_root=base);pages.append(p)
                if p.state!='ok':continue
                parsed_page=parse_page(p.html,p.final_url);parsed.append(parsed_page);contacts.extend(parsed_page.contacts)
                for v in contact_page_links(parsed_page,base):
                    if v not in seen and v not in queue:queue.insert(0,v)
        await walk(max(1,maximum-2))
        result=classify(parsed)
        effective=site.get('manual_decision') or result['classification']
        # Leave space for targeted recovery by avoiding additional content downloads, not by overriding robots.
        needs_contact=not any(c.purpose in {'business','contact','support'} for c in contacts)
        needs_messaging=self.cfg['search'].get('prefer_messaging_recovery',True) and not any(c.kind in {'telegram','whatsapp'} and c.purpose in {'business','contact','support'} for c in contacts)
        if effective=='PASS' and (needs_contact or needs_messaging):
            if self.contact_queries<self.cfg['search']['contact_queries_per_run'] and providers.available():
                self.contact_queries+=1
                query=(f'site:{domain} (telegram OR whatsapp OR \"t.me\" OR \"wa.me\") (contact OR business OR support)' if needs_messaging else f'site:{domain} (contact OR advertise OR partnership)')
                results=await providers.search(query)
                for r in results:
                    if within_site(r['url'],base) and r['url'] not in seen:queue.insert(0,r['url'])
                # Search snippets themselves never become contact evidence.
            queue[:0]=await providers.commoncrawl_paths(domain)
            # Keep the same overall cap: recovery does not authorize an unbounded second crawl.
            await walk()
            if needs_contact and self.hunter_domains<self.cfg['hunter']['max_domains_per_run']:
                self.hunter_domains+=1
                hunter_contacts=await providers.hunter(domain)
                for c in hunter_contacts:
                    # Re-fetch exact public source only when in budget and on this site.
                    if within_site(c.source_url,base) and c.source_url not in seen and len(pages)<maximum:
                        seen.add(c.source_url);p=await fetcher.fetch(c.source_url,allowed_root=base);pages.append(p)
                        if p.state=='ok':
                            pp=parse_page(p.html,p.final_url);parsed.append(pp);contacts+=pp.contacts
                    contacts.append(c)
        await walk()
        # Deduplicate identical evidence. Prefer live extraction over third-party suggestions.
        unique={}
        for c in contacts:
            key=messaging_key(c)
            if key not in unique or (unique[key].method=='hunter_domain_search' and c.method!='hunter_domain_search'):unique[key]=c
        from .telegram import inspect_public_telegram
        with_profiles=await inspect_public_telegram(list(unique.values()),fetcher,max_profiles=self.cfg['crawl'].get('max_public_profiles_per_site',6))
        contacts=await score_contacts(with_profiles,base,self.cfg,self.dns)
        result=classify(parsed);effective=site.get('manual_decision') or result['classification']
        best=next((c for c in contacts if c.tier=='READY'),None)
        all_unknown=not any(c.tier in {'READY','REVIEW'} for c in contacts)
        state='READY' if best and effective=='PASS' else 'REVIEW' if contacts and not all_unknown else 'COMMUNITY_ONLY' if any(c.tier=='COMMUNITY' for c in contacts) else 'LEGAL_ONLY' if contacts else 'NO_PUBLIC_CONTACT_FOUND'
        best=best or next((c for c in contacts if c.tier=='REVIEW'),None)
        result.update(final_url=home.final_url,access_state='ok',contact_state=state,
                      best_contact=best.dict() if best else None,
                      priority=round((result['relevance']*.45+(best.score if best else 0)*.55)) if effective=='PASS' else 0)
        self.db.save_result(domain,result,contacts,pages)
        self.db.event(f"{domain}: {effective} / {result['category']} / {state}; {len(contacts)} evidence records")
        return result
    async def run(self,*,discover=True,force=False,only=None,limit=None):
        if self.busy:raise RuntimeError('A run is already active in this engine')
        try:self.run_lock.acquire(timeout=0)
        except LockTimeout:raise RuntimeError('A run is already active in this data directory')
        self.busy=True
        self.contact_queries=0;self.hunter_domains=0
        started=now();run_id=None
        try:
            with self.db.connect() as c:
                c.execute("UPDATE runs SET state='interrupted',ended_at=? WHERE state='running'",(started,))
                run_id=c.execute("INSERT INTO runs(started_at,state,summary) VALUES(?,'running','{}')",(started,)).lastrowid
            added=self.seeds();results=[]
            async with Providers(self.cfg,self.db) as providers,Fetcher(self.cfg) as fetcher:
                if discover:added+=await self.discover(providers)
                sites=self.db.candidates(limit or self.cfg['crawl']['max_sites_per_run'],self.cfg['crawl']['revisit_days'],force,only)
                sem=asyncio.Semaphore(self.cfg['crawl']['concurrency'])
                async def guarded(site):
                    async with sem:
                        try:
                            async with asyncio.timeout(self.cfg['crawl']['site_timeout_seconds']):
                                return await self.scan_site(site,fetcher,providers)
                        except Exception as e:
                            self.db.event(f"{site['domain']}: scan interrupted ({type(e).__name__}); marked REVIEW",'warning')
                            result={'classification':'REVIEW','access_state':'scan_error','reasons':['Interrupted: '+type(e).__name__],
                                    'contact_state':'NOT_CHECKED','best_contact':None,'priority':0}
                            self.db.save_result(site['domain'],result,[],[]);return result
                results=await asyncio.gather(*(guarded(s) for s in sites))
            summary={'added':added,'scanned':len(results),'pass':sum(r.get('classification')=='PASS' for r in results),
                     'ready':sum(r.get('contact_state')=='READY' for r in results),'finished_at':now()}
            self.db.retention(self.cfg['retention_days'])
            from .export import write_exports
            write_exports(self.db,self.cfg)
            if self.cfg['sheets']['enabled'] and self.cfg['sheets']['auto_sync_after_run']:
                try:
                    from .sheets import sync_sheets
                    await asyncio.to_thread(sync_sheets,self.db,self.cfg)
                except Exception as e:self.db.event('Google Sheets sync failed: '+type(e).__name__,'warning')
            with self.db.connect() as c:c.execute("UPDATE runs SET ended_at=?,state='complete',summary=? WHERE id=?",(now(),json.dumps(summary),run_id))
            return summary
        except BaseException:
            if run_id:
                with self.db.connect() as c:c.execute("UPDATE runs SET ended_at=?,state='failed' WHERE id=?",(now(),run_id))
            raise
        finally:
            self.busy=False
            self.run_lock.release()
