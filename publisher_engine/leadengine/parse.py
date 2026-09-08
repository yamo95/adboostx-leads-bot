from __future__ import annotations
import re,json,html as htmlmod
from dataclasses import dataclass,field
from urllib.parse import urljoin,urlsplit,unquote,parse_qs
from bs4 import BeautifulSoup
from email_validator import validate_email,EmailNotValidError
from .models import Contact
from .urls import hostname,within_site,normalize_url,excluded,BINARY

EMAIL_RE=re.compile(r'(?<![\w.+-])([A-Za-z0-9.!#$%&\'*+/=?^_`{|}~-]+@[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?\.[A-Za-z]{2,63})(?![\w.-])')
CONTACT_TERMS=re.compile(r'contact|advertis|partner|business|sponsor|support|about|webmaster|admin|contato|contacto|kontakt|nous.contacter|publicit|reklam|ileti[s\u015f]im|\u0627\u062a\u0635\u0644|\u062a\u0648\u0627\u0635\u0644',re.I)
LEGAL_TERMS=re.compile(r'dmca|copyright|abuse|privacy|legal|takedown|infring|dpo@|noreply|no-reply|sentry|wixpress',re.I)
BUSINESS_TERMS=re.compile(r'advertis|\bads\b|partnership|business|cooperat|paid.promo|sponsor|media.buy|monetiz|publicit|commercial|reklam|\u0440\u0435\u043a\u043b\u0430\u043c|\u0441\u043e\u0442\u0440\u0443\u0434\u043d\u0438\u0447|\u5e7f\u544a|\u5408\u4f5c|\u0625\u0639\u0644\u0627\u0646',re.I)
DIRECT_TERMS=re.compile(r'contact|admin|owner|webmaster|support|message.me|reach.us|contato|contacto|\u0441\u0432\u044f\u0437|\u043f\u043e\u0434\u0434\u0435\u0440\u0436|\u062a\u0648\u0627\u0635\u0644|\u0627\u062a\u0635\u0644',re.I)
COMMUNITY_TERMS=re.compile(r'channel|updates|community|join.our|join.the|subscribe|canal|news|discussion|group',re.I)
BAD_EMAIL_DOMAINS={'example.com','example.org','example.net','domain.com','yourdomain.com','email.com','test.com','sentry.io','wixpress.com'}
SEO_TERMS=re.compile(r'guest.posts?|niche.edits?|backlinks?|link.building|seo.services?',re.I)
COMMON_PATHS=['/contact','/contact-us','/advertise','/faq','/about-us']

@dataclass
class Parsed:
    url: str
    title: str
    headings: list[str]
    text: str
    links: list[dict]=field(default_factory=list)
    contacts: list[Contact]=field(default_factory=list)
    schema_types: list[str]=field(default_factory=list)
    schema_names: list[str]=field(default_factory=list)
    has_player: bool=False
    has_download: bool=False
    nofollow: bool=False

def clean(value):return re.sub(r'\s+',' ',htmlmod.unescape(str(value))).strip()

def local_context(tag):
    own=clean(tag.get_text(' ',strip=True))
    parent=tag.parent
    if parent and parent.name not in {'body','html','footer','nav'}:
        text=clean(parent.get_text(' ',strip=True))
        if len(text)<=250 and len(parent.find_all('a'))<=3:return text
    return own[:350]

def purpose(value,context,source_url):
    # Address role has precedence. A footer containing a DMCA navigation item must not poison every address.
    prefix=value.split('@')[0].lower() if '@' in value else ''
    if LEGAL_TERMS.search(prefix) or LEGAL_TERMS.search(urlsplit(source_url).path):return 'legal_only'
    if SEO_TERMS.search(context):return 'seo_service'
    if BUSINESS_TERMS.search(prefix+' '+context) or re.fullmatch(r'ads|biz|partners|partnerships|sales|marketing',prefix):return 'business'
    if LEGAL_TERMS.search(context):return 'legal_only'
    if re.search(r'support|help',prefix+' '+context,re.I):return 'support'
    if DIRECT_TERMS.search(prefix+' '+context) or CONTACT_TERMS.search(urlsplit(source_url).path):return 'contact'
    return 'unknown'

def normalized_email(value):
    value=htmlmod.unescape(unquote(value)).strip(' \t\r\n.,;:<>[]()')
    try:
        email=validate_email(value,check_deliverability=False,allow_smtputf8=False).normalized
    except EmailNotValidError:return None
    domain=email.split('@')[1].lower()
    if domain in BAD_EMAIL_DOMAINS or any(domain.endswith('.'+x) for x in BAD_EMAIL_DOMAINS):return None
    if re.search(r'\.(?:png|jpe?g|webp|gif|svg|css|js)$',email,re.I):return None
    if re.match(r'^[a-f0-9]{24,}@',email,re.I):return None
    # Preserve local-part case; do not invent address variants.
    return email


def messaging_key(c):
    """Telegram public handles are case-insensitive; phones already normalized."""
    return (c.kind,c.value.casefold() if c.kind=='telegram' else c.value,c.source_url)

def normalized_phone(raw):
    # Do not strip arbitrary letters to manufacture a plausible phone number.
    raw=unquote(str(raw)).strip()
    if not re.fullmatch(r'\+?[0-9][0-9 ()\-.]{6,24}',raw):return None
    digits=re.sub(r'[^0-9]','',raw)
    if not re.fullmatch(r'[1-9][0-9]{7,14}',digits):return None
    # Known template numbers and repeated digits. Never guess a replacement.
    if digits in {'1234567890','12345678901','18001234567','18001234568'} or len(set(digits))==1:return None
    return '+'+digits

def whatsapp_link(href,label,context,source_url):
    """Preserve unresolved business short links; never infer their phone number."""
    try:
        p=urlsplit(href);host=hostname(href);path=unquote(p.path).strip('/');port=p.port
    except ValueError:return []
    if p.username or p.password:return []
    if port not in (None,80,443):return []
    native=p.scheme.lower()=='whatsapp' and p.netloc.lower()=='send'
    if not native and (p.scheme not in {'https','http'} or host not in {
        'wa.me','wa.link','api.whatsapp.com','web.whatsapp.com','chat.whatsapp.com','whatsapp.com'}):return []
    if host=='chat.whatsapp.com' or host=='whatsapp.com' and path.startswith('channel/'):
        if not re.fullmatch(r'(?:channel/)?[A-Za-z0-9_-]{6,100}',path):return []
        value='https://'+host+'/'+path
        return [Contact('whatsapp',value,source_url,context,'explicit_whatsapp','community_invite',contact_url=value)]
    unresolved=(host=='wa.link' and re.fullmatch(r'[A-Za-z0-9_-]{3,80}',path)) or (
        host=='wa.me' and re.fullmatch(r'message/[A-Za-z0-9_-]{5,100}',path))
    if unresolved:
        value='https://'+host+'/'+path
        return [Contact('whatsapp',value,source_url,context or label,'whatsapp_short_link',
            purpose(value,context,source_url),verification='published_short_link_unresolved',contact_url=value,
            notes=['Published WhatsApp business link. Phone/account not inferred or verified; manual opening required.'])]
    if host=='wa.link' or host=='whatsapp.com':return []
    params=parse_qs(p.query)
    raw=path if host=='wa.me' else params.get('phone',[''])[0]
    if host!='wa.me' and not native and path not in {'send','send/'}:return []
    if len(params.get('phone',[]))>1:return []
    phone=normalized_phone(raw)
    if not phone:return []
    display=re.search(r'\+[0-9][0-9 ()\-.]{6,24}[0-9]',label or '')
    out=Contact('whatsapp',phone,source_url,context or label,'explicit_whatsapp',purpose(phone,context,source_url),contact_url='https://wa.me/'+phone[1:])
    if display and normalized_phone(display.group()) not in {None,phone}:
        out.verification='display_link_mismatch'
        out.notes.append('Displayed number differs from link destination: '+display.group()+'. Review both; no automatic correction.')
    out.notes.append('Public click-to-chat route; WhatsApp registration, identity and delivery are unverified.')
    return [out]

def printed_messaging_contacts(soup,url):
    """Only explicit labelled messaging data in small visible blocks, not forms/scripts."""
    found=[];seen=set()
    for node in soup.find_all(['p','li','div','td','address']):
        if node.find_parent(['form','script','style']) or node.find(['input','textarea','select']):continue
        block=clean(node.get_text(' ',strip=True))
        if not block or len(block)>320 or block in seen:continue
        seen.add(block)
        for m in re.finditer(r'whats\s*app\s*(?:support|business|contact|number)?\s*[:\-\u2013\u2014]?\s*(\+[0-9][0-9 ()\-.]{6,24}[0-9])',block,re.I):
            phone=normalized_phone(m.group(1))
            if phone:
                cs=whatsapp_link('https://wa.me/'+phone[1:],phone,block,url)
                for c in cs:c.method='labelled_messaging_text'
                found+=cs
        # A bare @name is ambiguous unless explicitly labelled Telegram/TG.
        for m in re.finditer(r'\b(?:telegram|tg)\s*(?:support|business|contact|admin)?\s*[:\-\u2013\u2014]?\s*@([A-Za-z][A-Za-z0-9_]{2,31})\b',block,re.I):
            cs=contact_from_link('https://t.me/'+m.group(1),'Telegram',block,url)
            for c in cs:c.method='labelled_messaging_text'
            found+=cs
    return found

def contact_from_link(href,label,context,source_url):
    href=htmlmod.unescape(href.strip())
    if href.lower().startswith('whatsapp://'):return whatsapp_link(href,label,context,source_url)
    if href.lower().startswith('mailto:'):
        out=[]
        for val in unquote(href[7:].split('?',1)[0]).split(','):
            email=normalized_email(val)
            if email:out.append(Contact('email',email,source_url,context or label or email,'mailto',purpose(email,context,source_url),contact_url='mailto:'+email))
        return out
    if href.lower().startswith('skype:'):
        value=href[6:].split('?',1)[0]
        return [Contact('skype',value,source_url,context,'explicit_skype',purpose(value,context,source_url),contact_url=href)] if value else []
    if href.lower().startswith('tel:'):
        val=re.sub(r'[^+0-9]','',href[4:])
        if re.fullmatch(r'\+[1-9][0-9]{7,14}',val):return [Contact('phone',val,source_url,context,'explicit_tel',purpose(val,context,source_url),contact_url='tel:'+val)]
        return []
    if href.lower().startswith('tg://resolve'):
        username=parse_qs(urlsplit(href).query).get('domain',[''])[0]
        href='https://t.me/'+username
    try:
        full=urljoin(source_url,href);p=urlsplit(full);host=hostname(full);path=unquote(p.path).strip('/');port=p.port
    except ValueError:return []
    if p.scheme not in {'http','https'} or p.username or p.password or port not in (None,80,443):return []
    if host in {'t.me','telegram.me','telegram.dog'}:
        if not path:return []
        command=path.split('/')[0].lower()
        if command in {'share','addstickers','proxy','socks','login','iv','boost','addemoji','addlist','c'}:return []
        if command=='m':
            if not re.fullmatch(r'm/[A-Za-z0-9_-]{4,100}',path):return []
            value='https://t.me/'+path
            return [Contact('telegram',value,source_url,context,'telegram_business_link',purpose(value,context,source_url),verification='published_short_link_unresolved',contact_url=value)]
        bits=path.split('/');invite=path.startswith(('+','joinchat/'))
        user=bits[1] if bits[0]=='s' and len(bits)>1 else bits[0]
        if not invite and not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{2,31}',user):return []
        ispost=(bits[0]=='s' or len(bits)>1)
        value='https://t.me/'+(path if invite else user)
        use=purpose(user,context,source_url)
        if invite:use='community_invite'
        elif user.lower().endswith('bot'):use='bot'
        elif ispost or COMMUNITY_TERMS.search(label+' '+context):use='community'
        out=Contact('telegram',value,source_url,context or label or value,'explicit_telegram',use,contact_url=value)
        out.notes.append('Published by site; Telegram identity / ability to receive private messages is not verified.')
        return [out]
    if host in {'wa.me','wa.link','api.whatsapp.com','web.whatsapp.com','chat.whatsapp.com','whatsapp.com'}:
        return whatsapp_link(full,label,context,source_url)
    if host in {'facebook.com','instagram.com','linkedin.com','x.com','twitter.com','discord.gg','discord.com'}:
        if any(x in path.lower() for x in ['sharer','share','intent/']):return []
        return [Contact('social',full,source_url,context or label,'explicit_social','social_profile',contact_url=full)]
    return []

def parse_page(raw,url):
    soup=BeautifulSoup(raw,'html.parser')
    for node in soup.select('#comments,.comments,.comment-list,.comment-body,.review-list,template,[hidden],[aria-hidden="true"]'):
        node.decompose()
    title=clean(soup.title.get_text()) if soup.title else ''
    headings=[clean(t.get_text(' ',strip=True)) for t in soup.select('h1,h2,h3')][:60]
    contacts=[];links=[];types=[];names=[]
    for script in soup.select('script[type="application/ld+json"]'):
        try:data=json.loads(script.string or script.get_text())
        except (ValueError,TypeError):continue
        def walk(obj,depth=0):
            if depth>12:return
            if isinstance(obj,list):
                for x in obj[:200]:walk(x,depth+1)
            elif isinstance(obj,dict):
                ts=obj.get('@type',[]);ts=[ts] if isinstance(ts,str) else ts
                types.extend(str(x) for x in ts)
                if any(x in {'SoftwareApplication','MobileApplication'} for x in ts) and obj.get('name'):names.append(clean(obj['name']))
                # Only organization contact objects, not authors, reviewers or arbitrary embedded person profiles.
                if any(x in {'Organization','ContactPoint','Corporation'} for x in ts):
                    if isinstance(obj.get('email'),str):
                        em=normalized_email(obj['email'].replace('mailto:',''))
                        if em:contacts.append(Contact('email',em,url,clean(json.dumps(obj,ensure_ascii=False))[:350],'json_ld',purpose(em,str(obj.get('contactType','')),url),contact_url='mailto:'+em))
                    for key in ['sameAs','url']:
                        vals=obj.get(key,[]);vals=[vals] if isinstance(vals,str) else vals
                        if isinstance(vals,list):
                            for val in vals:
                                if isinstance(val,str):contacts.extend(contact_from_link(val,'Organization',str(obj.get('contactType','')),url))
                for v in obj.values():
                    if isinstance(v,(dict,list)):walk(v,depth+1)
        walk(data)
    for node in soup.select('[data-cfemail]'):
        try:
            b=bytes.fromhex(node['data-cfemail']);em=normalized_email(bytes(x^b[0] for x in b[1:]).decode('utf-8'))
            if em:contacts.append(Contact('email',em,url,local_context(node),'cf_email_decode',purpose(em,local_context(node),url),contact_url='mailto:'+em))
        except (ValueError,UnicodeDecodeError,IndexError):pass
    for a in soup.select('a[href]'):
        if a.find_parent(['form']):continue
        href=a.get('href','');label=clean(a.get_text(' ',strip=True)) or clean(a.get('aria-label','')) or clean(a.get('title',''))
        ctx=local_context(a)
        if label and label not in ctx:ctx=(label+' '+ctx).strip()
        contacts.extend(contact_from_link(href,label,ctx,url))
        try:
            full=urljoin(url,href)
            if urlsplit(full).scheme in {'http','https'}:
                links.append({'url':full.split('#')[0],'label':label,'context':ctx,'nofollow':'nofollow' in a.get('rel',[])})
        except ValueError:pass
    for node in soup.select('[data-email],[data-whatsapp],[data-telegram]'):
        if node.find_parent(['form']):continue
        if node.get('data-email'):
            em=normalized_email(node['data-email'])
            if em:contacts.append(Contact('email',em,url,local_context(node),'data_attribute',purpose(em,local_context(node),url),contact_url='mailto:'+em))
        for attr,prefix in [('data-whatsapp','https://wa.me/'),('data-telegram','https://t.me/')]:
            if node.get(attr):
                raw=node[attr].strip()
                value=raw if re.match(r'^(?:https?://|whatsapp://|tg://)',raw,re.I) else prefix+raw.lstrip('@+')
                contacts.extend(contact_from_link(value,'',local_context(node),url))
    for tag in soup(['script','style','noscript','template','svg']):tag.decompose()
    # Never scrape comment author lists / third-party post bodies for contact attribution.
    for node in soup.select('#comments,.comments,.comment-list,.comment-body,.review-list,template,[hidden],[aria-hidden="true"]'):node.decompose()
    contacts.extend(printed_messaging_contacts(soup,url))
    public_text_soup=BeautifulSoup(str(soup),'html.parser')
    for node in public_text_soup.select('form'):node.decompose()
    text=clean(public_text_soup.get_text(' ',strip=True))
    deob=re.sub(r'\s*(?:\[at\]|\(at\))\s*','@',text,flags=re.I)
    deob=re.sub(r'\s*(?:\[dot\]|\(dot\))\s*','.',deob,flags=re.I)
    for match in EMAIL_RE.finditer(deob):
        em=normalized_email(match.group(1))
        if em:
            evidence=deob[max(0,match.start()-90):match.end()+110]
            contacts.append(Contact('email',em,url,evidence,'visible_text' if deob==text else 'obfuscated_text',purpose(em,evidence,url),contact_url='mailto:'+em))
    # Plain printed messenger links, excluding scripts.
    for match in re.finditer(r'(?:https?://)?(?:t\.me|telegram\.me|telegram\.dog|wa\.me|wa\.link)/[^\s<>"\)\]]+',text):
        val=match.group().rstrip('.,;');ctx=text[max(0,match.start()-70):match.end()+70]
        contacts.extend(contact_from_link(val if '://' in val else 'https://'+val,val,ctx,url))
    contact_page=bool(CONTACT_TERMS.search(urlsplit(url).path+' '+title+' '+' '.join(headings[:2])))
    for form in soup.select('form'):
        # Search/login/newsletter forms are not contact forms. Require a message textarea.
        if form.select_one('textarea') and (contact_page or CONTACT_TERMS.search(clean(form.get_text(' ',strip=True)))):
            contacts.append(Contact('contact_form',url,url,clean(form.get_text(' ',strip=True))[:350] or title,'html_form','contact',contact_url=url))
    best={}
    rank={'mailto':6,'cf_email_decode':5,'explicit_telegram':5,'explicit_whatsapp':5,'json_ld':4,'data_attribute':4,'obfuscated_text':3,'visible_text':2}
    for c in contacts:
        k=messaging_key(c)
        if k not in best or rank.get(c.method,3)>rank.get(best[k].method,3):best[k]=c
    meta=soup.find('meta',attrs={'name':re.compile('^robots$',re.I)})
    nofollow=bool(meta and 'nofollow' in meta.get('content','').lower())
    return Parsed(url,title,headings,text,links,list(best.values()),types,names,
        bool(soup.select('video,iframe[src*="embed"],iframe[src*="player"],a[href*="/watch/"],a[href*="/movie/"]')),
        any(BINARY.search(urlsplit(x['url']).path) and re.search(r'\.(apk|xapk|apks|zip|rar|7z)$',urlsplit(x['url']).path,re.I) for x in links)
        or any(re.search(r'download|t[e\u00e9]l[e\u00e9]charger|descargar|baixar|\u062a\u0646\u0632\u064a\u0644',x['label'],re.I) for x in links),nofollow)

def contact_page_links(parsed,base):
    out=[]
    if parsed.nofollow:return out
    for link in parsed.links:
        if link['nofollow'] or not within_site(link['url'],base):continue
        try:url=normalize_url(link['url'])
        except ValueError:continue
        label=link['label']+' '+urlsplit(url).path
        score=100 if BUSINESS_TERMS.search(label) else 80 if re.search(r'contact|contato|contacto|kontakt|\u0627\u062a\u0635\u0644',label,re.I) else 60 if re.search(r'support|about|help|faq|frequently',label,re.I) else 15 if LEGAL_TERMS.search(label) else 0
        if score:out.append((score,url))
    return [x[1] for x in sorted(set(out),reverse=True)]

def external_candidates(parsed,base,limit):
    result=[]
    if parsed.nofollow:return result
    for link in parsed.links:
        if link['nofollow'] or within_site(link['url'],base) or excluded(link['url']):continue
        # Editorial partner/mirror/project links, NOT ad scripts, click trackers, arbitrary affiliate hops.
        text=link['label']+' '+link['context']
        if not re.search(r'mirror|new.domain|official.site|current.domain|domaine.actuel|acc[e\u00e9]dez|partner|friend|related.app|recommended.site|alternative|mod.site',text,re.I):continue
        try:clean_url=normalize_url(link['url'])
        except ValueError:continue
        if any(x in clean_url.lower() for x in ['click','tracking','redirect=','affiliate','utm_']):continue
        if clean_url not in result:result.append(clean_url)
        if len(result)>=limit:break
    return result
