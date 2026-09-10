"""Opt-in deeper public-contact scan within the existing B219 runtime.
Existing Fetcher policy/DNS/pace, envelope keys, publication and scheduled modes
remain unchanged. No messages, joins, forms, credentials or binary downloads.
"""
from __future__ import annotations
import asyncio
import json
import os
import re
from pathlib import Path
from urllib.parse import urlsplit, urljoin
from bs4 import BeautifulSoup
import scan
import messaging_enrichment as messaging
import contact_context
import quantity_expansion as quantity
import fresh_discovery

REVISION = 'intent-depth-v2-20260910'
MAX_SITES, MAX_PAGES, MAX_PREVIEWS, MAX_DOCUMENTS = 120, 18, 20, 4
PAGE_SECONDS, PREVIEW_SECONDS = 165, 75
INTENT = re.compile(r'contact|advertis|partnership|business|sponsor|media.?kit|about.?us|reklam|kontakt|hubungi|kerjasama|lien.?he|\bads\b', re.I)
DENY_PATH = re.compile(r'login|sign.?up|register|logout|download|\bdl\b|checkout|cart|privacy|dmca|terms|copyright|reset|unsubscribe',re.I)
BASE_ROLE = messaging.extended_role

def intent_role(text, source):
    # A Telegram/article URL containing 'contact' is not a role label.
    # Only the visible line may attribute an external profile's purpose.
    if urlsplit(source).hostname in set(scan.TG_HOSTS)|{'telegra.ph'}:
        source=scan.origin(source)+'/'
    role=BASE_ROLE(text,source)
    if role in {'legal','seo_service'}:return role
    if re.search(r'(?<!\w)(?:ads|sponsorship|collaboration)\s*(?:contact|inquir\w*)?\s*[:=-]',text,re.I):return 'business'
    return role

def document_url(raw):
    try:
        raw=scan.safe_url(raw);p=urlsplit(raw)
        if p.query:return None
        if p.hostname in scan.TG_HOSTS and re.fullmatch(r'/[A-Za-z][A-Za-z0-9_]{2,31}/[0-9]{1,10}/?',p.path):
            return raw.rstrip('/')+'?embed=1&mode=tme'
        if p.hostname=='telegra.ph' and p.path not in {'','/'}:return raw
    except (TypeError,ValueError):pass
    return None

def linked_documents(html, source):
    soup=BeautifulSoup(html,'html.parser')
    root=soup.select_one('.tgme_page_description') or soup
    result=[]
    for a in root.select('a[href]'):
        if a.find_parent(class_=re.compile('comment|user-post|review-body',re.I)):continue
        context=contact_context.local_context(a)
        url=document_url(urljoin(source,a['href']))
        if url and re.search(r'contact|advertis|media.?kit|inquir|kontakt|hubungi|reklam|\bads?\s*[:=-]',context,re.I) and not contact_context.EXCLUDED_CONTEXT.search(context):result.append(url)
    return list(dict.fromkeys(result))[:MAX_DOCUMENTS]

async def deeper_hops(contacts, fetcher, documents):
    output=await messaging.enriched_hops(contacts,fetcher)
    queue=list(documents)
    for c in output:
        if c.get('channel')!='telegram' or c.get('profile_type')!='community':continue
        cached=getattr(fetcher,'_contact_preview_cache',{}).get(messaging.preview_key(c['contact_url']))
        if cached and cached.get('state')=='ok':
            queue += [(u,c['source_url'],c['contact_url']) for u in linked_documents(cached['html'],c['contact_url'])]
    seen=set();extra=[]
    for url,site_source,parent in queue:
        if url in seen:continue
        if len(seen)>=MAX_DOCUMENTS:break
        seen.add(url)
        page=await messaging.get_preview(fetcher,url)
        if page.get('state')!='ok':continue
        soup=BeautifulSoup(page['html'],'html.parser')
        root=soup.select_one('.tgme_widget_message_text') or soup.select_one('.tl_article_content')
        if root is None:continue
        found=messaging.from_description(root,url,site_source)
        for c in found:
            c['source_chain']=list(dict.fromkeys([site_source,parent,url,c['contact_url']]))
            c['notes']='Explicit contact-labelled public document linked by the website or its Telegram bio. Authority and account activity are unverified.'
        extra.extend(found)
    if extra:output+=await messaging.enriched_hops(extra,fetcher)
    return scan.unique(output)

async def scan_site(seed,fetcher):
    base=scan.origin(seed)+'/'
    queue=list(dict.fromkeys([seed,base]));seen=set();contacts=[];links=[];texts=[];related=[];documents=[]
    successes=0;partial=[]
    try:
        async with asyncio.timeout(PAGE_SECONDS):
            while queue and len(seen)<MAX_PAGES:
                url=queue.pop(0)
                if url in seen:continue
                seen.add(url)
                page=await fetcher.get(url,site=base)
                if page.get('state')=='cross_site_redirect':
                    dest=page.get('final_url','')
                    if quantity.eligible_url(dest):related.append(dest)
                if page.get('state')!='ok':continue
                successes+=1
                soup=BeautifulSoup(page['html'],'html.parser')
                for node in soup.select('[class*=comment],[id*=comment],[class*=user-post],[class*=review-body]'):node.decompose()
                html=str(soup)
                found,new_links,text=contact_context.parse(html,page['final_url'])
                contacts+=found;links+=new_links;texts.append(text)
                documents += [(u,page['final_url'],page['final_url']) for u in linked_documents(html,page['final_url'])]
                preferred=[u for u,label in new_links if scan.same_site(u,base) and u not in seen and
                           INTENT.search(urlsplit(u).path+' '+label) and not DENY_PATH.search(urlsplit(u).path)]
                preferred.sort(key=lambda u:(not bool(re.search('advertis|business|partner|reklam',u,re.I)),u))
                queue=list(dict.fromkeys(preferred+queue))
                if successes==1:queue+= [urljoin(base,p) for p in ['/advertise','/advertise-with-us','/contact','/contact-us','/contact-us/','/contacts','/contact.html','/about-us','/about','/pages/contact-us','/pages/contactus','/support','/faq']]
                for u,label in new_links:
                    if not scan.same_site(u,base) and re.search(r'partner|sister\s+site|related\s+site|mirror|our\s+sites',label,re.I) and quantity.eligible_url(u):related.append(u)
    except TimeoutError:partial.append('website_time_budget')
    try:
        async with asyncio.timeout(PREVIEW_SECONDS):contacts=await deeper_hops(contacts,fetcher,documents)
    except TimeoutError:partial.append('preview_time_budget')
    niche,fit=scan.category(' '.join(texts),links)
    contacts=scan.unique(contacts)
    for c in contacts:
        c.update(domain=scan.host(base),niche=niche,site_fit=fit,quality=scan.grade(c))
        c['depth_revision']=REVISION
        c['outreach_tier']='business_published' if c['role']=='business' else 'support_only' if c['role']=='support' else 'general_or_review'
    site={'domain':scan.host(base),'url':base,'niche':niche,'site_fit':fit,'state':'SCANNED' if successes else 'ACCESS_FAILED',
          'html_pages_opened':successes,'contact_records':len(contacts),'observed_at':scan.stamp(),
          'depth_revision':REVISION,'page_attempts':len(seen),'partial_reasons':partial}
    return site,contacts,list(dict.fromkeys(related))[:3]

def targets():
    config=json.loads(Path(__file__).with_name('intent_targets.json').read_text())
    if not isinstance(config,list) or not 0<len(config)<=MAX_SITES:raise ValueError('TARGET_LIMIT')
    urls=[quantity.eligible_url(u) for u in config]
    if any(u is None for u in urls) or len({scan.host(u) for u in urls})!=len(urls):raise ValueError('INVALID_TARGETS')
    return urls

def main():
    if os.environ.get('SEARCH_DEPTH')!='focused':return fresh_discovery.main()
    if os.environ.get('GITHUB_EVENT_NAME') not in {'push','workflow_dispatch'}:raise ValueError('EXPLICIT_DEEP_REQUEST_REQUIRED')
    urls=targets();seed_path=scan.ROOT/'seeds.txt';old_seeds=seed_path.read_bytes()
    saved=(scan.run,scan.scan_site,scan.selected_seeds,scan.role,scan.telegram_hops,messaging.CALL_LIMIT,quantity.CONCURRENT_SITES,quantity.MAX_RELATED,messaging.extended_role)
    namespace=scan.main.__globals__;old_copy=namespace['_save_operator_copy']
    def annotate(payload):
        payload['depth_scan']={'revision':REVISION,'max_pages_per_site':MAX_PAGES,'max_profile_previews_per_pass':MAX_PREVIEWS,'max_preview_passes':2,
          'max_contact_documents':MAX_DOCUMENTS,'selected_sites':len(urls),'target_new_direct_chats':30,
          'completion':'SCAN_ONLY_REQUIRES_PRIVATE_NOVELTY_REVIEW'}
        return old_copy(payload)
    try:
        seed_path.write_text('\n'.join(urls)+'\n')
        scan.run=quantity.expanded_run;scan.scan_site=scan_site;scan.selected_seeds=lambda seeds,batch='auto':seeds[:MAX_SITES]
        scan.role=intent_role;messaging.extended_role=intent_role;scan.telegram_hops=messaging.enriched_hops;messaging.CALL_LIMIT=MAX_PREVIEWS
        quantity.CONCURRENT_SITES=8;quantity.MAX_RELATED=12
        namespace['_save_operator_copy']=annotate
        return scan.main()
    finally:
        seed_path.write_bytes(old_seeds)
        (scan.run,scan.scan_site,scan.selected_seeds,scan.role,scan.telegram_hops,messaging.CALL_LIMIT,quantity.CONCURRENT_SITES,quantity.MAX_RELATED,messaging.extended_role)=saved
        namespace['_save_operator_copy']=old_copy

def publish(envelope,summary):
    if os.environ.get('SEARCH_DEPTH')=='focused':
        import search_round
        return search_round.publish(envelope,summary)
    return fresh_discovery.publish(envelope,summary)

if __name__=='__main__':raise SystemExit(main())
