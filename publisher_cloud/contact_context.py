"""DOM-bounded public contact enrichment. No JS execution, guesses or messages."""
from __future__ import annotations
import re
from urllib.parse import urljoin, urlsplit, parse_qs
from bs4 import BeautifulSoup, Comment
import scan

BASE_PARSE = scan.parse
INTENT = re.compile(r'contact|support|help|owner|admin|business|advertis|partnership|cooperation|reklam|contato|contacto|kontak|hubungi|lien\s*he', re.I)
EXCLUDED_CONTEXT = re.compile(r'guest\s*post|backlink|niche\s*edit|link\s*insertion|do\s*not\s*contact|not\s*accepting\s*ads|no\s+ads|website\s+for\s+sale', re.I)
HEADINGS = ['h1','h2','h3','h4','h5','h6']
RESERVED = set('www addemoji addlist addstickers addstyle addtheme auction auth boost call confirmphone contact giftcode invoice joinchat login m nft proxy setlanguage share socks web'.split())

def canonical(raw):
    """Accept documented Telegram deep links and username.t.me, not arbitrary JS."""
    try:
        p = urlsplit(raw)
        if p.username or p.password: return raw
        if p.scheme == 'tg' and p.netloc == 'resolve' and set(parse_qs(p.query)) <= {'domain','text','profile'}:
            user = parse_qs(p.query).get('domain', [''])[0]
            return 'https://t.me/' + user if re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{2,31}',user) else raw
        host = p.hostname or ''
        if p.scheme in {'https','http'} and host.endswith('.t.me') and host.count('.') == 2 and p.path in {'','/'}:
            user = host[:-5]
            if user.lower() not in RESERVED and not p.query and re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{2,31}',user): return 'https://t.me/'+user
    except ValueError: pass
    return raw

def local_context(node):
    """Only a small semantic block and its own heading, never an entire page."""
    pieces = [node.get_text(' ',strip=True), node.get('aria-label',''), node.get('title','')]
    for parent in list(node.parents)[:3]:
        if parent.name in {'body','html','main'}: break
        text = scan.clean(parent.get_text(' ',strip=True))
        if len(text) <= 350 and len(parent.select('a[href]')) <= 3:
            pieces.append(text)
        # A heading directly before a list/card labels its own block only.
        heading = parent.find_previous_sibling(HEADINGS)
        if heading is not None:
            siblings = list(heading.next_siblings)
            intervening = [s for s in siblings[:siblings.index(parent)] if getattr(s,'name',None)] if parent in siblings else []
            if not intervening:
                pieces.append(heading.get_text(' ',strip=True))
                break
        if parent.name in {'section','article','footer','nav'}: break
    return scan.clean(' | '.join(dict.fromkeys(p for p in pieces if p)))[:500]

def parse(html, source):
    contacts, links, text = BASE_PARSE(html, source)
    soup = BeautifulSoup(html,'html.parser')
    for node in soup(['script','style','form','noscript','template','svg']): node.decompose()
    for node in soup.select('[hidden],[aria-hidden="true"], [style*="display:none"], [style*="display: none"]'): node.decompose()
    for node in soup.find_all(string=lambda s:isinstance(s,Comment)): node.extract()
    # Never mine application descriptions, user comments, legal boilerplate or posts.
    if re.search(r'dmca|privacy|terms|copyright',urlsplit(source).path,re.I): return contacts,links,text
    additions=[]
    for a in soup.select('a[href]'):
        if a.find_parent(class_=re.compile(r'comment|review-body|user-post',re.I)): continue
        raw=canonical(urljoin(source,a['href'].strip()))
        row=scan.route(raw,'',source)
        if not row or row['channel'] not in {'telegram','whatsapp'}: continue
        context=local_context(a)
        if not INTENT.search(context) or EXCLUDED_CONTEXT.search(context): continue
        enriched=scan.route(raw,context,source)
        if enriched and enriched['role'] in {'business','contact','support'}:
            enriched['notes']='Published link with a bounded local contact heading; not an ownership or activity verification.'
            additions.append(enriched)
    # Text-only handles split by <span>/<strong> are missed by line-only parsing.
    for block in soup.select('p,li,dd'):
        if block.find_parent(class_=re.compile(r'comment|review-body|user-post',re.I)): continue
        value=scan.clean(block.get_text(' ',strip=True))
        if len(value)>350 or not INTENT.search(value) or EXCLUDED_CONTEXT.search(value): continue
        if re.search(r'telegram',value,re.I):
            for handle in scan.HANDLE.findall(value)[:3]:
                row=scan.route('https://t.me/'+handle,value,source)
                if row: additions.append(row)
        if re.search(r'whats\s*app',value,re.I):
            for candidate in re.findall(r'\+[1-9][0-9\s().-]{7,22}[0-9]',value)[:3]:
                number=scan.phone(candidate)
                if number:
                    row=scan.route('https://wa.me/'+number[1:],value,source)
                    if row: additions.append(row)
    # Original purpose exclusions outrank context recovery.
    held={(c['channel'],c['contact'].casefold()) for c in contacts if c['role'] in {'legal','seo_service'}}
    additions=[c for c in additions if (c['channel'],c['contact'].casefold()) not in held]
    return scan.unique(contacts+additions),links,text
