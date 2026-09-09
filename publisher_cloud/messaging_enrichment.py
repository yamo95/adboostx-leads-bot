"""Public-preview messaging enrichment for the existing B219 scanner.
No joins, messages, authenticated access, hidden data or private keys.
"""
from __future__ import annotations
import asyncio
import json
import os
import re
from pathlib import Path
from urllib.parse import urljoin, urlsplit
from bs4 import BeautifulSoup, NavigableString
import scan
import deep_profile as deep

BASE_ROLE = scan.role
BASE_HOPS = scan.telegram_hops
CALL_LIMIT = 8
INQUIRY = re.compile(r'\bcontact|reach\s+us|\u043a\u043e\u043d\u0442\u0430\u043a\u0442|\u0441\u0432\u044f\u0437|hubungi|contatt|contacter',re.I)
SUPPORT = re.compile(r'\u043f\u043e\u0434\u0434\u0435\u0440\u0436\u043a|bantuan|soporte|suporte',re.I)
DECLINE = re.compile(r'no\s+ads|do\s+not\s+contact|not\s+accepting\s+ads|\u0431\u0435\u0437\s+\u0440\u0435\u043a\u043b\u0430\u043c',re.I)


def extended_role(context,source):
    found=BASE_ROLE(context,source)
    if found!='unknown':return found
    if SUPPORT.search(context):return 'support'
    if INQUIRY.search(context):return 'contact'
    return found


def description_lines(desc,source):
    """Keep the text and links of each visual line together, not the whole bio."""
    lines=[{'parts':[],'links':[]}]
    def newline():
        if lines[-1]['parts'] or lines[-1]['links']:lines.append({'parts':[],'links':[]})
    def walk(node):
        if isinstance(node,NavigableString):
            pieces=str(node).split('\n')
            for i,piece in enumerate(pieces):
                if i:newline()
                lines[-1]['parts'].append(piece)
            return
        if node.name in {'script','style','form','template'}:return
        if node.name=='br':newline();return
        if node.name in {'p','li','div'}:newline()
        if node.name=='a':
            lines[-1]['parts'].append(node.get_text(' ',strip=True))
            if node.get('href'):lines[-1]['links'].append(urljoin(source,node['href']))
        else:
            for child in node.children:walk(child)
        if node.name in {'p','li','div'}:newline()
    for child in desc.children:walk(child)
    return [(scan.clean(''.join(r['parts'])),r['links']) for r in lines if scan.clean(''.join(r['parts']))]


def from_description(desc,source,via):
    result=[]
    for text,links in description_lines(desc,source):
        if DECLINE.search(text):continue
        purpose=extended_role(text,source)
        if purpose not in {'business','contact','support'}:continue
        candidates=list(links)
        candidates += ['https://t.me/'+h for h in scan.HANDLE.findall(text)[:4]]
        candidates += ['mailto:'+m for m in scan.MAIL.findall(text)[:3]]
        if re.search(r'whats\s*app',text,re.I):
            for value in re.findall(r'\+[1-9][0-9\s().-]{7,22}[0-9]',text):
                phone=scan.phone(value)
                if phone:candidates.append('https://wa.me/'+phone[1:])
        for raw in candidates:
            row=scan.route(raw,text,source)
            if not row:continue
            row['role']=purpose
            row['via']=via
            row['notes']='Explicit contact label in a public, site-linked Telegram description; site ownership and account activity are not independently verified.'
            result.append(row)
            if len(result)>=16:return scan.unique(result)
    return scan.unique(result)


def preview_key(url):
    p=urlsplit(url)
    path=p.path.lower() if p.hostname in scan.TG_HOSTS and not p.path.startswith(('/+','/joinchat/')) else p.path
    return p.hostname.lower()+path+('?' + p.query if p.query else '')


async def get_preview(fetcher,url):
    if not hasattr(fetcher,'_contact_preview_cache'):
        fetcher._contact_preview_cache={};fetcher._contact_preview_locks={}
    key=preview_key(url)
    lock=fetcher._contact_preview_locks.setdefault(key,asyncio.Lock())
    async with lock:
        if key not in fetcher._contact_preview_cache:
            fetcher._contact_preview_cache[key]=await fetcher.get(url,site=scan.origin(url)+'/')
        return fetcher._contact_preview_cache[key]


async def enriched_hops(contacts,fetcher):
    output=scan.unique(contacts)
    queue=[(c,0) for c in output if c['channel']=='telegram' and c['profile_type'] in {'unverified','community'}]
    seen=set();calls=0
    while queue and calls<CALL_LIMIT:
        item,depth=queue.pop(0)
        if urlsplit(item['contact_url']).hostname not in scan.TG_HOSTS:continue
        address=preview_key(item['contact_url'])
        if address in seen:continue
        seen.add(address);calls+=1
        page=await get_preview(fetcher,item['contact_url'])
        if page['state']!='ok':
            item['notes']+=' Telegram public preview unavailable.';continue
        soup=BeautifulSoup(page['html'],'html.parser')
        extra=soup.select_one('.tgme_page_extra')
        extra_text=scan.clean(extra.get_text(' ',strip=True)) if extra else ''
        text=scan.clean(soup.get_text(' ',strip=True))
        community=item['profile_type']=='community' or re.search(r'subscribers|members|abonn|membres|\u043f\u043e\u0434\u043f\u0438\u0441\u0447\u0438\u043a',extra_text,re.I)
        if community:
            item['profile_type']='community'
            desc=soup.select_one('.tgme_page_description')
            if depth==0 and desc:
                for row in from_description(desc,item['contact_url'],item['source_url']):
                    output.append(row)
                    if row['channel']=='telegram' and row['profile_type']=='unverified':queue.append((row,1))
        elif re.search(r'start bot',text,re.I) or extra_text.lower()=='bot':item['profile_type']='bot'
        elif re.search(r'if you have telegram, you can contact|send message',text,re.I):
            item['profile_type']='contact_preview'
            item['notes']+=' Contact preview observed; account activity and business authority unverified.'
        else:item['notes']+=' Public preview type not established.'
    short=[c for c in output if c['channel']=='whatsapp' and c['profile_type']=='short_link_unresolved'][:2]
    for item in short:
        u=item['contact_url']
        if urlsplit(u).hostname not in {'wa.link','wa.me'}:continue
        page=await get_preview(fetcher,u)
        destinations=[]
        if page.get('state')=='cross_site_redirect':destinations=[page.get('final_url','')]
        elif page.get('state')=='ok':
            soup=BeautifulSoup(page.get('html',''),'html.parser')
            destinations=[a['href'] for a in soup.select('a[href]') if re.search(r'whatsapp|chat',a.get_text(' ',strip=True),re.I)]
        resolved=[]
        for dest in destinations:
            if urlsplit(dest).hostname not in {'wa.me','api.whatsapp.com','web.whatsapp.com'}:continue
            row=scan.route(dest,item['evidence'],item['source_url'])
            if row and row['channel']=='whatsapp' and row['contact'].startswith('+'):
                row['role']=item['role'];row['via']=u
                row['notes']='Number resolved from a website-published WhatsApp short route. No message or account-registration check was performed.'
                resolved.append(row)
        resolved=scan.unique(resolved)
        if len(resolved)==1:output.extend(resolved)
    return scan.unique(output)


def main():
    old_role,old_hops=scan.role,scan.telegram_hops
    old_file,old_sources=deep.CANDIDATES_FILE,deep.NEW_SOURCES
    mode=os.environ.get('SEED_BATCH')
    scan.role,scan.telegram_hops=extended_role,enriched_hops
    try:
        if mode=='enrich':
            deep.CANDIDATES_FILE=Path(__file__).with_name('enrichment_candidates.json')
            deep.NEW_SOURCES={}
            os.environ['SEED_BATCH']='deep'
        return deep.main()
    finally:
        scan.role,scan.telegram_hops=old_role,old_hops
        deep.CANDIDATES_FILE,deep.NEW_SOURCES=old_file,old_sources
        if mode is None:os.environ.pop('SEED_BATCH',None)
        else:os.environ['SEED_BATCH']=mode

if __name__=='__main__':raise SystemExit(main())
