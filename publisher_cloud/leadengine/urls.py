from __future__ import annotations
import ipaddress
import re
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

BINARY = re.compile(r'\.(?:apk|xapk|apks|exe|msi|dmg|pkg|zip|rar|7z|tar|gz|torrent|mp4|m3u8|mp3|avi|mkv|pdf|png|jpe?g|webp|svg|gif|woff2?|ttf)(?:$|/)',re.I)
SKIP_QUERY={'utm_source','utm_medium','utm_campaign','utm_term','utm_content','gclid','fbclid'}
SOCIAL_HOSTS={'t.me','telegram.me','telegram.dog','wa.me','api.whatsapp.com','web.whatsapp.com','chat.whatsapp.com',
              'facebook.com','instagram.com','x.com','twitter.com','youtube.com','discord.gg','discord.com',
              'linkedin.com','pinterest.com','reddit.com','tiktok.com','github.com','play.google.com','apps.apple.com'}
EXCLUDE_HOSTS=SOCIAL_HOSTS | {'google.com','bing.com','duckduckgo.com','wikipedia.org','trustpilot.com','similarweb.com',
                             'semrush.com','cloudflare.com','wordpress.org','wordpress.com','ad-maven.com','admaven.com'}

def hostname(value: str) -> str:
    try:
        h=(urlsplit(value if '://' in value else 'https://'+value).hostname or '').lower().rstrip('.')
        return h[4:] if h.startswith('www.') else h
    except ValueError: return ''

def normalize_url(value: str, *, allow_binary: bool=False) -> str:
    if not isinstance(value,str) or len(value)>2048: raise ValueError('Invalid URL')
    value=value.strip()
    if any(ord(x)<32 for x in value) or '\\' in value: raise ValueError('Invalid characters in URL')
    if value.startswith('//'): value='https:'+value
    if '://' not in value: value='https://'+value
    p=urlsplit(value)
    if p.scheme.lower() not in {'http','https'} or not p.hostname or p.username or p.password:
        raise ValueError('Only ordinary public HTTP(S) URLs are accepted')
    h=p.hostname.rstrip('.').lower().encode('idna').decode('ascii')
    if p.port not in {None,80,443}: raise ValueError('Only ports 80 and 443 are allowed')
    if h in {'localhost','metadata.google.internal'} or h.endswith(('.local','.internal','.localhost','.test','.invalid')):
        raise ValueError('Private host is not allowed')
    try:
        ip=ipaddress.ip_address(h)
        if not ip.is_global: raise ValueError('Non-public address is not allowed')
        h='['+h+']' if ip.version==6 else h
    except ValueError as e:
        if 'address is not allowed' in str(e): raise
        if '.' not in h or re.fullmatch(r'[0-9.]+',h): raise ValueError('Invalid public hostname')
    if not allow_binary and BINARY.search(p.path): raise ValueError('Downloads and media are not fetched')
    query=urlencode([(k,v) for k,v in parse_qsl(p.query,keep_blank_values=True) if k.lower() not in SKIP_QUERY])
    netloc=h+(f':{p.port}' if p.port and p.port != (443 if p.scheme=='https' else 80) else '')
    return urlunsplit((p.scheme.lower(),netloc,p.path or '/',query,''))

def root_url(value: str) -> str:
    p=urlsplit(normalize_url(value)); return urlunsplit((p.scheme,p.netloc,'','',''))+'/'

def within_site(value: str, base: str) -> bool:
    h,b=hostname(value),hostname(base)
    return bool(h and b and (h==b or h.endswith('.'+b)))

def excluded(value: str) -> bool:
    h=hostname(value)
    return any(h==x or h.endswith('.'+x) for x in EXCLUDE_HOSTS)
