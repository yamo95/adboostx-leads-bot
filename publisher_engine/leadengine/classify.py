from __future__ import annotations
import re
from .parse import Parsed

APK=re.compile(r'\bapk\b|\bxapk\b|android.app|modded.app|\u0623\u0646\u062f\u0631\u0648\u064a\u062f|\u0627\u0646\u062f\u0631\u0648\u064a\u062f',re.I)
STREAM=re.compile(r'watch.{0,24}movies|movies.{0,24}(?:online|free)|films?.{0,25}streaming|streaming.{0,25}(?:films?|s[e\u00e9]ries)|watch.{0,20}tv.shows|nonton.film|assistir.filmes|ver.pel[i\u00ed]culas',re.I)
SPORT=re.compile(r'football|soccer|sports?|nba|nfl|ufc|cricket|futebol|f[u\u00fa]tbol|basketball',re.I)
LIVE=re.compile(r'live.stream|streams?|watch.live|ao.vivo|en.vivo|en.direct',re.I)
MOD=re.compile(r'\bmods?\b|modpack|game.modifications',re.I)
HOST=re.compile(r'file.hosting|file.sharing|upload.{0,25}files|upload.{0,25}mods|hosting.platform|download.{0,25}earn',re.I)
SHORT=re.compile(r'url.shortener|link.shortener|shorten.{0,15}links|shorten.{0,15}url|paid.shortener',re.I)
AGENCY=re.compile(r'(?:seo|digital.marketing|web.design).{0,20}(?:agency|services)|lead.generation.software',re.I)
NEWS=re.compile(r'news|reviews|journal|blog|guide|best.{0,25}sites|how.to',re.I)

def classify(pages: list[Parsed]) -> dict:
    if not pages:return {'classification':'REVIEW','category':'unknown','relevance':0,'reasons':['No readable page; absence of access is not evidence of irrelevance.']}
    home=pages[0]
    primary=' '.join([home.title]+home.headings[:2])
    text=' '.join(p.text[:35000] for p in pages)
    links=[x for p in pages for x in p.links]
    labels=' '.join(x['label'] for x in links)
    paths=' '.join(x['url'] for x in links)
    schema=set(x for p in pages for x in p.schema_types)
    download=any(p.has_download for p in pages)
    player=any(p.has_player for p in pages)
    candidates=[]
    if APK.search(text+' '+primary):
        app_schema=bool(schema & {'SoftwareApplication','MobileApplication'})
        operational=download and (bool(APK.search(primary)) or app_schema)
        score=15+35*bool(APK.search(primary))+30*download+20*app_schema
        names=set(n.lower() for p in pages for n in p.schema_names)
        app_sections=sum(bool(re.search(r'games|apps|categories|all.apps',x['label'],re.I)) for x in links)
        category='apk_catalog' if app_sections>=3 or len(names)>3 else 'apk_single_app'
        candidates.append((score,category,operational,['APK / Android evidence','Download entry point present' if download else 'No download entry point confirmed','Single-app sites are accepted' if category=='apk_single_app' else 'Multiple app / catalog navigation signals']))
    if SPORT.search(primary+' '+text) and LIVE.search(primary+' '+text):
        operational=player or bool(re.search(r'/live/|/streams?/|/watch/|watch.live|live.stream|ao.vivo',paths+' '+labels,re.I))
        score=20+25*bool(SPORT.search(primary))+25*bool(LIVE.search(primary))+25*operational
        if NEWS.search(primary) and not operational:score=min(score,45)
        candidates.append((score,'sports_streaming',operational,['Sports and live-stream terms','Stream navigation / player evidence' if operational else 'Could be sports news or a guide; inspect manually']))
    if STREAM.search(primary+' '+text):
        entry=bool(re.search(r'watch.now|start.watching|go.to.home|use.the.old|acc[e\u00e9]dez|domaine.actuel|current.domain',labels,re.I))
        catalog=player or bool(re.search(r'/movies?/|/tv/|/series/|/watch/',paths,re.I))
        score=20+30*bool(STREAM.search(primary))+35*bool(catalog or entry)
        candidates.append((score,'streaming' if catalog else 'streaming_gateway',bool(catalog or entry),['Movie / series streaming evidence','Catalog navigation' if catalog else 'Entry / mirror landing page; target identity needs review']))
    if MOD.search(primary+' '+text) and not APK.search(primary):
        score=15+35*bool(MOD.search(primary))+25*download+15*bool(re.search(r'game|minecraft|gta|truck|skyrim|creator|simulator',text,re.I))
        candidates.append((score,'game_mods',download,['Game-mod evidence','Download action present' if download else 'No download action confirmed']))
    if HOST.search(primary+' '+text):
        upload=bool(re.search(r'upload|share.files|host.files',labels+' '+text,re.I))
        earn=bool(re.search(r'earn|pay.per.download|creator|storage|file.size',text,re.I))
        score=25+25*bool(HOST.search(primary))+25*upload+20*earn
        candidates.append((score,'file_hosting',upload and earn,['File-hosting / upload service','Upload and creator / storage / earnings signals']))
    if SHORT.search(primary+' '+text):
        action=bool(re.search(r'shorten|short.link|create.link',labels+' '+text,re.I))
        earn=bool(re.search(r'earn|payout|publisher|paid|monetiz',text,re.I))
        score=25+25*bool(SHORT.search(primary))+20*action+20*earn
        candidates.append((score,'monetized_shortener',action and earn,['Shortening service','Publisher earnings evidence' if earn else 'No monetized publisher offer confirmed']))
    if not candidates:
        state='REVIEW' if len(home.text)<160 else 'REJECT'
        return {'classification':state,'category':'unknown','relevance':0,'reasons':['Insufficient readable text' if state=='REVIEW' else 'No operational evidence of requested publisher niches']}
    score,category,operational,reasons=max(candidates,key=lambda x:(x[0],x[2]))
    if AGENCY.search(primary):
        operational=False;score=min(score,35);reasons.append('Agency / service-page false-positive guard')
    state='PASS' if score>=65 and operational else 'REVIEW' if score>=30 else 'REJECT'
    return {'classification':state,'category':category,'relevance':min(100,score),'reasons':reasons}
