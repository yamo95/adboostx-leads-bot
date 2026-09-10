"""Novelty-first adapter for B219; same crawler, encryption and publication.

Only public candidate URLs go into a frozen plan. The browser supplies compact
host fingerprints and still counts new, source-backed messaging contacts.
"""
from __future__ import annotations
import asyncio
import base64
import hashlib
import json
import os
import re
from collections import Counter
from pathlib import Path
from urllib.parse import urlsplit, parse_qs, unquote, quote
from urllib.request import Request, urlopen
from bs4 import BeautifulSoup
import scan
import deep_profile as deep
import messaging_enrichment as messaging
import search_round as legacy
import contact_context

ROOT = Path(__file__).parent
BASE = 'https://raw.githubusercontent.com/yamo95/adboostx-leads-bot/main/'
REVISION = 'fresh-discovery-v2-20260910'
QUERIES = [
    '"mod apk" "contact" "whatsapp"',
    '"apk" "contact us" "telegram"',
    '"movie streaming" "advertising" "telegram"',
    '"sports streaming" "contact" "telegram"',
    '"url shortener" "telegram support"',
    '"shortlink" "contact" "whatsapp"',
    '"video hosting" "contact" "telegram"',
    '"game mods" "contact" "telegram"',
    '"apk" "contato" "telegram"',
    '"filmes" "contato" "telegram"',
    '"streaming" "contacto" "telegram"',
    '"mod apk" "hubungi" "whatsapp"',
]
NOT_PUBLISHER = {'duckduckgo.com','bing.com','google.com','facebook.com','instagram.com',
 'youtube.com','linkedin.com','x.com','twitter.com','pinterest.com','telegram.org',
 'core.telegram.org','t.me','telegra.ph','whatsapp.com','wa.me','linktr.ee',
 'reddit.com','github.com','play.google.com','apps.apple.com'}


def host_key(domain):
    return hashlib.sha256(str(domain).lower().removeprefix('www.').encode()).hexdigest()[:16]


class BootstrapHistory:
    """Conservative acceptance-only Bloom filter; live UI sends exact hashes.
    False positives can only skip a candidate, never call an old site new.
    """
    def __init__(self, obj):
        self.bits = base64.b64decode(obj['bits'], validate=True)
        if len(self.bits) != 4096 or obj['format'] != 1: raise ValueError('BOOTSTRAP')
        self.count = int(obj['count'])
    def __len__(self): return self.count
    def __contains__(self, value):
        raw = hashlib.sha256(value.encode()).digest()
        return all(self.bits[(n := int.from_bytes(raw[i:i+4], 'big') % 32768)//8] & (1 << (n%8)) for i in range(0,20,4))


def decode_seen(text):
    if len(text)>60000: raise ValueError('Too many site fingerprints')
    if not text: return set()
    values=text.split(',')
    if len(values)>3500 or any(not re.fullmatch(r'[a-f0-9]{16}',v) for v in values):
        raise ValueError('Invalid site fingerprints')
    return set(values)


def candidate(value):
    u=deep.eligible(value)
    if not u: return None
    h=scan.host(u)
    if any(h==x or h.endswith('.'+x) for x in NOT_PUBLISHER): return None
    return u


def results(html, source):
    """Search snippets are discovery only; never treated as contact evidence."""
    soup=BeautifulSoup(html,'html.parser'); rows=[]; seen=set()
    for a in soup.select('a.result__a[href]'):
        u=a['href']; p=urlsplit(u)
        if p.hostname and p.hostname.endswith('duckduckgo.com') or u.startswith('//duckduckgo.com'):
            u=parse_qs(p.query).get('uddg',[''])[0]
        u=candidate(u)
        if u and scan.host(u) not in seen:
            seen.add(scan.host(u));rows.append(u)
        if len(rows)>=20: break
    return rows


async def discover():
    urls=[]; checks=[]
    # Original safe resolver, robots rules, maximum sizes and pace are retained.
    async with scan.Fetcher() as fetcher:
        for q in QUERIES:
            u='https://html.duckduckgo.com/html/?q='+quote(q+' -iptv -casino -site:t.me -site:facebook.com -site:youtube.com')
            try:
                reply=await fetcher.get(u)
                found=results(reply.get('html',''),u) if reply.get('state')=='ok' else []
                urls.extend(found)
                checks.append({'query':q,'state':reply.get('state'),'candidates':len(found)})
                if reply.get('state') in {'http_403','http_429','robots_denied_or_unavailable'}: break
            except Exception as e:
                checks.append({'query':q,'state':type(e).__name__,'candidates':0})
    return urls,checks


def build_plan(rid, seeds, seen, preferred=(), diagnostics=()):
    candidates=[]; hosts=set(); skipped=set()
    for raw in list(preferred)+list(seeds):
        u=candidate(raw)
        if not u: continue
        h=scan.host(u)
        if host_key(h) in seen:
            skipped.add(h); continue
        if h not in hosts:
            hosts.add(h);candidates.append(u)
    candidates=candidates[:legacy.PAGE_SIZE*legacy.MAX_PAGES]
    return {'format':2,'id':rid,'revision':REVISION,'urls':candidates,
      'pool_hash':hashlib.sha256('\n'.join(candidates).encode()).hexdigest(),
      'known_sites_skipped':len(skipped),'history_fingerprints':len(seen),
      'discovery_checks':list(diagnostics),'created_at':scan.stamp()}


def validate_plan(plan, rid, expected=''):
    if not isinstance(plan,dict) or plan.get('format')!=2 or plan.get('id')!=rid:
        raise ValueError('PLAN_FORMAT')
    urls=plan.get('urls')
    if not isinstance(urls,list) or len(urls)>legacy.PAGE_SIZE*legacy.MAX_PAGES:
        raise ValueError('PLAN_SIZE')
    if any(not isinstance(u,str) or candidate(u)!=u for u in urls): raise ValueError('PLAN_URL')
    if len({scan.host(u) for u in urls})!=len(urls): raise ValueError('PLAN_DUPLICATE')
    digest=hashlib.sha256('\n'.join(urls).encode()).hexdigest()
    if plan.get('pool_hash')!=digest or expected and digest!=expected: raise ValueError('PLAN_CHANGED')
    return plan


def load_plan(rid,expected):
    path='private-b219-results/plans/'+rid+'.json'
    request=Request(BASE+path,headers={'User-Agent':scan.UA,'Accept':'application/json'})
    with urlopen(request,timeout=25) as response:
        if response.geturl()!=BASE+path: raise ValueError('PLAN_REDIRECT')
        data=response.read(750001)
    if len(data)>750000: raise ValueError('PLAN_SIZE')
    return validate_plan(json.loads(data),rid,expected)


def metadata(plan,page):
    end=(page+1)*legacy.PAGE_SIZE
    return {'format':2,'id':plan['id'],'strategy':'fresh','page':page,
      'page_size':legacy.PAGE_SIZE,'pool_size':len(plan['urls']),
      'pool_hash':plan['pool_hash'],'target':30,'has_more':end<len(plan['urls']),
      'max_pages':legacy.MAX_PAGES,'completion':'PAGE_ONLY','novelty_counting':'private_browser',
      'known_sites_skipped':plan['known_sites_skipped'],
      'history_fingerprints':plan['history_fingerprints'],'discovery_checks':plan['discovery_checks']}


def empty_report(meta):
    summary={'created_at':scan.stamp(),'run_id':os.environ.get('GITHUB_RUN_ID','local'),
      'seed_pool':0,'seeds_scanned':0,'sites_checked':0,'pages_opened':0,
      'contact_evidence_records':0,'published_messaging_routes':0,'relevant_sites':0,
      'access_states':{},'status':'FRESH_CANDIDATES_EXHAUSTED','mode':'keyless_bounded_snapshot',
      'notice':'No unseen candidates available; target not reached. No outreach was sent.'}
    payload={'summary':summary,'sites':[],'contacts':[],'search_round':meta}
    scan.main.__globals__['_save_operator_copy'](payload)
    out=ROOT/'sealed';out.mkdir(exist_ok=True)
    (out/'results.encrypted.json').write_text(json.dumps(scan.seal(payload,(ROOT/'recipient.pem').read_bytes())))
    (out/'summary.json').write_text(json.dumps(summary,indent=2))
    return 0


def main():
    mode=os.environ.get('SEED_BATCH','auto')
    if mode!='fresh': return legacy.main()
    # The acceptance push is bounded and cannot claim a private browser quota.
    if os.environ.get('GITHUB_EVENT_NAME')=='push':
        rid=hashlib.sha256(('acceptance|'+os.environ['GITHUB_RUN_ID']).encode()).hexdigest()[:32]
        page=0;expected='';seen=BootstrapHistory(json.loads((ROOT/'fresh_seen_bootstrap.json').read_text()))
    else:
        rid,page,expected=legacy.request(os.environ)
        if os.environ.get('GITHUB_EVENT_NAME')!='workflow_dispatch': raise ValueError('EXPLICIT_REQUEST_REQUIRED')
        seen=decode_seen(os.environ.get('SEARCH_SEEN_HOSTS',''))
        if page==0 and not seen: raise ValueError('COMPLETE_SITE_HISTORY_REQUIRED')
    plan=load_plan(rid,expected) if page else None
    preferred=[];checks=[]
    if not plan:
        config=json.loads((ROOT/'fresh_candidates.json').read_text())
        if not isinstance(config,list) or len(config)>500: raise ValueError('CANDIDATE_CONFIGURATION')
        preferred=[r['url'] for r in config if isinstance(r,dict) and candidate(r.get('url',''))]
        fetched,checks=asyncio.run(discover());preferred+=fetched
    namespace=scan.main.__globals__;old_copy=namespace['_save_operator_copy'];old_select=deep.select
    old_order=deep.growth.ordered_candidates;old_parse=scan.parse;old_mode=os.environ.get('SEED_BATCH')
    plan_holder={}; meta_holder={}
    def order(rows):
        # Insert freshly discovered URLs BEFORE the inherited 1500-candidate cap.
        extra=[{'url':u,'kind':'fresh-discovery','source':u,
           'basis':'Public candidate URL only; contact extracted independently from website'} for u in preferred]
        full=old_order(extra+rows)
        chosen_plan=plan or build_plan(rid,[r['url'] for r in full],seen,preferred,checks)
        plan_holder.update(chosen_plan)
        lookup={scan.host(r['url']):r for r in full}
        return [lookup.get(scan.host(u),{'url':u,'kind':'frozen-fresh-plan','source':u,
            'basis':'Unseen candidate at round start, not verified publisher'}) | {'url':u} for u in chosen_plan['urls']]
    def select(seeds,batch='auto',now=None,deep_urls=()):
        meta_holder.update(metadata(plan_holder,page))
        start=page*legacy.PAGE_SIZE;chosen=plan_holder['urls'][start:start+legacy.PAGE_SIZE]
        if not chosen: raise RuntimeError('FRESH_EXHAUSTED')
        return chosen
    def copy(payload):
        payload['search_round']=dict(meta_holder)
        payload['search_round']['page_messaging_records']=sum(c.get('channel') in {'telegram','whatsapp'} for c in payload['contacts'])
        return old_copy(payload)
    try:
        deep.growth.ordered_candidates=order;deep.select=select
        scan.parse=contact_context.parse;namespace['_save_operator_copy']=copy
        os.environ['SEED_BATCH']='search'
        try: result=messaging.main()
        except RuntimeError as e:
            if str(e)!='FRESH_EXHAUSTED': raise
            namespace['_save_operator_copy']=old_copy
            result=empty_report(meta_holder)
        if not plan_holder: raise RuntimeError('NO_FRESH_PLAN')
        (ROOT/'sealed'/'fresh-plan.json').write_text(json.dumps(plan_holder,indent=2))
        return result
    finally:
        deep.growth.ordered_candidates=old_order;deep.select=old_select;scan.parse=old_parse
        namespace['_save_operator_copy']=old_copy
        if old_mode is None:os.environ.pop('SEED_BATCH',None)
        else:os.environ['SEED_BATCH']=old_mode


def publish(envelope,summary):
    file=ROOT/'sealed'/'fresh-plan.json'
    if os.environ.get('SEED_BATCH')=='fresh':
        plan=json.loads(file.read_text());rid=plan['id'];legacy.request({'SEARCH_ROUND_ID':rid,'SEARCH_PAGE':'0'})
        validate_plan(plan,rid)
        path='private-b219-results/plans/'+rid+'.json'
        existing=scan.gh('GET','contents/'+path+'?ref=main')
        if existing:
            prior=json.loads(base64.b64decode(existing['content']))
            if prior['pool_hash']!=plan['pool_hash']: raise ValueError('IMMUTABLE_PLAN_CONFLICT')
        else:
            scan.gh('PUT','contents/'+path,{'branch':'main','message':'Freeze unseen candidate plan; no contact data',
              'content':base64.b64encode(json.dumps(plan,indent=2).encode()).decode()})
    legacy.publish(envelope,summary)

if __name__=='__main__':raise SystemExit(main())
