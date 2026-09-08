"""Bounded public-preview inspection; no login, joins, posts, member lists or messages."""
from __future__ import annotations
import re
from collections import deque
from bs4 import BeautifulSoup
from .models import Contact
from .parse import clean,purpose,messaging_key

HANDLE=re.compile(r'(?<![\w@])@([A-Za-z][A-Za-z0-9_]{2,31})\b')
NEGATIVE=re.compile(r'no\s+(?:ads|advertising|promotions)|do\s+not\s+contact|not\s+accepting|\u043d\u0435\s+\u043f\u0438\u0441\u0430\u0442\u044c',re.I)


def bio_contacts(description,source):
    """Interpret each role clause independently; no cross-role proximity window."""
    desc=BeautifulSoup(str(description),'html.parser')
    for a in desc.select('a[href]'):
        match=re.fullmatch(r'https?://(?:t\.me|telegram\.me)/([A-Za-z][A-Za-z0-9_]{2,31})/?',a['href'])
        if match and not HANDLE.search(a.get_text()):a.append(' @'+match.group(1))
    for br in desc.find_all('br'):br.replace_with('\n')
    text=desc.get_text(' ',strip=True)
    result=[];previous=''
    for raw in re.split(r'[\n|;]+',text):
        line=clean(raw)
        if not line:continue
        prior_end=0;last_role_context=''
        for m in HANDLE.finditer(line):
            before=clean(line[prior_end:m.start()]);prior_end=m.end()
            context=before or (previous if len(previous)<90 and not HANDLE.search(previous) else '')
            if last_role_context and re.fullmatch(r'(?:[-\u2013\u2014&,]+|and|or)',context,re.I):
                context=last_role_context
            if not context or NEGATIVE.search(context):continue
            role=purpose(m.group(1),context,source)
            if role not in {'business','contact','support'}:last_role_context='';continue
            last_role_context=context
            value='https://t.me/'+m.group(1)
            bot=m.group(1).lower().endswith('bot')
            result.append(Contact('telegram',value,source,context+' @'+m.group(1),'linked_profile_bio',
                'bot' if bot else role,association='linked_profile_business_contact',contact_url=value,
                notes=['Published role: '+role+'. Source is a site-linked public profile bio; ownership remains unverified.']))
        previous=line
    return result


async def inspect_public_telegram(contacts,fetcher,max_profiles=6):
    """At most two hops: site -> public channel bio -> labelled contact preview."""
    max_profiles=max(0,min(8,int(max_profiles)))
    output=list(contacts);queue=deque((c,0) for c in output if c.kind=='telegram')
    seen=set();known={messaging_key(c) for c in output};calls=0
    while queue and calls<max_profiles:
        c,depth=queue.popleft();key=c.value.casefold()
        if key in seen or c.purpose=='bot' or c.verification=='published_short_link_unresolved':continue
        seen.add(key);calls+=1
        page=await fetcher.fetch(c.value,allowed_root='https://t.me/')
        if page.state!='ok':
            c.verification='telegram_preview_unavailable';continue
        soup=BeautifulSoup(page.html,'html.parser')
        extra=soup.select_one('.tgme_page_extra');description=soup.select_one('.tgme_page_description')
        extra_text=clean(extra.get_text(' ',strip=True)) if extra else ''
        alltext=clean(soup.get_text(' ',strip=True))
        iscommunity=bool(re.search(r'\b(?:subscribers|members|abonn[e\u00e9]s|membres|\u043f\u043e\u0434\u043f\u0438\u0441\u0447\u0438\u043a\u043e\u0432|\u0443\u0447\u0430\u0441\u0442\u043d\u0438\u043a\u043e\u0432)\b',extra_text,re.I))
        if re.search(r'\bstart bot\b',alltext,re.I) or re.fullmatch(r'bot',extra_text,re.I):
            c.purpose='bot';c.verification='public_bot_page_observed'
            c.notes.append('Public bot landing page; bot was not started.')
        elif iscommunity:
            c.purpose='community';c.verification='public_channel_or_group_page_observed'
            c.notes.append('Public preview is a channel/group, not a confirmed direct business contact.')
            if depth==0 and description:
                additions=bio_contacts(description,c.value)
                for new in additions[:4]:
                    if new.value.casefold()==c.value.casefold() or messaging_key(new) in known:continue
                    new.notes.append('Evidence chain: '+c.source_url+' -> '+c.value+' -> '+new.value)
                    new.verification='profile_not_checked_budget'
                    known.add(messaging_key(new));output.append(new)
                    if new.purpose=='business':queue.appendleft((new,1))
                    else:queue.append((new,1))
        elif re.search(r'if you have telegram, you can contact|send message',alltext,re.I):
            c.verification='public_contact_profile_observed'
            c.notes.append('Public contact preview observed; account ownership, activity and response are NOT verified.')
        else:c.verification='telegram_profile_type_unknown'
    return reconcile_previews(output)


def reconcile_previews(contacts):
    """A known channel/bot must not reappear as a person through duplicate evidence."""
    observed = {}
    for c in contacts:
        if c.kind != 'telegram':
            continue
        if c.verification in {'public_bot_page_observed', 'public_channel_or_group_page_observed'}:
            observed[c.value.casefold()] = (c.purpose, c.verification)
    for c in contacts:
        result = observed.get(c.value.casefold()) if c.kind == 'telegram' else None
        if result and c.verification != result[1]:
            if c.purpose not in {'legal_only', 'seo_service'}:
                c.purpose = result[0]
            c.verification = result[1]
            c.notes.append('Account type reconciled from another public-preview observation of this same endpoint.')
    return contacts
