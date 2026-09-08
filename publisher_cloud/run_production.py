"""Production corrections verified against actual live output.

Keep each Telegram role local to its handle. Do not promote a whole channel's
roster to advertising just because one line mentions advertising.
"""
from __future__ import annotations
import re
from bs4 import BeautifulSoup
import scan

LOCAL_BUSINESS = re.compile(r'advertis|\bads?\b|partnership|business|cooperat|paid\s+promo|marketing|monetiz|publicit|reklam|\u0440\u0435\u043a\u043b\u0430\u043c|\u0441\u043e\u0442\u0440\u0443\u0434\u043d\u0438\u0447', re.I)
LOCAL_SUPPORT = re.compile(r'support|help|questions?|\u0432\u043e\u043f\u0440\u043e\u0441|\u043f\u043e\u0434\u0434\u0435\u0440\u0436',re.I)
LOCAL_CONTACT = re.compile(r'contact|owner|admin|webmaster|reach|contato|contacto|\u0441\u0432\u044f\u0437|\u043a\u043e\u043d\u0442\u0430\u043a\u0442',re.I)
NO_PROMOTION = re.compile(r'no\s+(?:ads|advertising)|do\s+not\s+contact|no\s+business|\u043f\u0440\u043e\u043c\u0438\u043a|promo\s*code|coupon',re.I)

def local_role(text):
    if NO_PROMOTION.search(text): return None
    if scan.LEGAL.search(text) or scan.SEO.search(text): return None
    if LOCAL_BUSINESS.search(text): return 'business'
    if LOCAL_SUPPORT.search(text): return 'support'
    if LOCAL_CONTACT.search(text): return 'contact'
    return None

def description_routes(description, source, via):
    for br in description.find_all('br'): br.replace_with('\n')
    text = description.get_text('', strip=False)
    out=[];carry=''
    for line in re.split(r'[\n|;]+', text):
        line=scan.clean(line)
        if not line:continue
        matches=list(scan.HANDLE.finditer(line))
        if not matches:
            carry=line if len(line)<100 and local_role(line) else ''
            continue
        previous_end=0
        for index, match in enumerate(matches[:6]):
            prefix=line[previous_end:match.start()][-140:]
            role=local_role(prefix)
            if not prefix.strip(' :-\u2013\u2014') and index==0 and carry:
                prefix=carry;role=local_role(prefix)
            if role is None and len(matches)==1 and len(line[match.end():])<70:
                suffix=line[match.end():]
                if local_role(suffix):prefix=suffix;role=local_role(suffix)
            previous_end=match.end()
            if not role:continue
            evidence=scan.clean(prefix+' '+match.group())
            item=scan.route('https://t.me/'+match.group(1), evidence, source)
            if item:
                item['role']=role
                item['via']=via
                item['notes']='Role comes from the local label next to this handle in a site-linked public channel. Ownership is not independently verified.'
                out.append(item)
        carry=''
    return scan.unique(out)

async def telegram_hops(contacts,fetcher):
    output=scan.unique(contacts)
    queue=[(c,0) for c in output if c['channel']=='telegram' and c['profile_type']=='unverified']
    seen=set();calls=0
    while queue and calls<6:
        item,depth=queue.pop(0)
        address=item['contact_url'].casefold()
        if address in seen:continue
        seen.add(address);calls+=1
        page=await fetcher.get(item['contact_url'],site='https://t.me/')
        if page['state']!='ok':
            item['notes']+=' Telegram preview unavailable.';continue
        soup=BeautifulSoup(page['html'],'html.parser')
        extra=soup.select_one('.tgme_page_extra')
        extra_text=scan.clean(extra.get_text(' ',strip=True)) if extra else ''
        text=scan.clean(soup.get_text(' ',strip=True))
        if re.search(r'subscribers|members|abonn|membres|\u043f\u043e\u0434\u043f\u0438\u0441\u0447\u0438\u043a',extra_text,re.I):
            item['profile_type']='community';desc=soup.select_one('.tgme_page_description')
            if depth==0 and desc:
                for new in description_routes(desc,item['contact_url'],item['source_url']):
                    if new['contact_url'].casefold() not in seen:
                        output.append(new)
                        if new['profile_type']=='unverified':queue.append((new,1))
        elif re.search(r'start bot',text,re.I) or extra_text.lower()=='bot':item['profile_type']='bot'
        elif re.search(r'if you have telegram, you can contact|send message',text,re.I):
            item['profile_type']='contact_preview'
            item['notes']+=' Contact preview observed; account activity and authority unverified.'
        else:item['notes']+=' Profile type could not be established.'
    return scan.unique(output)

if __name__=='__main__':
    scan.telegram_hops=telegram_hops
    raise SystemExit(scan.main())
