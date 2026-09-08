import asyncio,json,socket
from copy import deepcopy
from datetime import datetime,timezone,timedelta
import pytest
from leadengine.parse import parse_page,contact_from_link,normalized_email,contact_page_links
from leadengine.classify import classify
from leadengine.urls import normalize_url,within_site,hostname
from leadengine.quality import score_contacts
from leadengine.models import Contact,Page
from leadengine.export import csv_text,lead_rows,effective_contacts
from leadengine.fetch import PublicResolver,RobotsPolicy
from leadengine.engine import Engine
from leadengine.telegram import inspect_public_telegram

APK='<html><title>Honista APK Download</title><h1>Honista</h1><p>One Android application, version 13</p><a href="/download/">Download APK</a><a href="/contact">Contact</a></html>'
STREAM='<title>Watch Movies Online Free</title><h1>Movies</h1><a href="/movie/a">Watch now</a><a href="/faqs/">FAQ</a>'

@pytest.mark.parametrize('url',['http://127.0.0.1/','http://10.0.0.1/','http://169.254.169.254/','http://[::1]/','http://localhost/','file:///etc/passwd','https://user:secret@site.org/','https://site.org:8080/','https://site.org/file.apk','https://site.org/a.zip','http://2130706433/','http://127.1/'])
def test_unsafe_urls(url):
    with pytest.raises(ValueError):normalize_url(url)

def test_url_normalization():
    assert normalize_url('https://publisher.org/a?utm_source=x&b=1#top')=='https://publisher.org/a?b=1'
    assert within_site('https://ww8.publisher.org/','https://publisher.org/')
    assert not within_site('https://publisher.org.attacker.org/','https://publisher.org/')
    assert not within_site('https://another.github.io/','https://owner.github.io/')
    assert hostname('https://www.publisher.org/')=='publisher.org'

def test_single_app_pass():
    result=classify([parse_page(APK,'https://honistaapk.in.net/')])
    assert result['classification']=='PASS'
    assert result['category']=='apk_single_app'

def test_apk_guide_not_pass():
    html='<title>How to find the best APK websites</title><h1>APK safety guide</h1><p>We review apk sites and describe download risks.</p>'
    assert classify([parse_page(html,'https://publisher.org/')])['classification']!='PASS'

def test_streaming_pass():assert classify([parse_page(STREAM,'https://publisher.org/')])['classification']=='PASS'

def test_sports_news_not_pass():
    p=parse_page('<title>Football news and live scores</title><h1>Sports news</h1><p>See our analysis of live streaming rights and the latest sports scores.</p>','https://publisher.org/')
    assert classify([p])['classification']!='PASS'

def test_sports_streaming_pass():
    p=parse_page('<title>Live football streams</title><a href="/live/game">Watch live football</a>','https://publisher.org/')
    assert classify([p])['classification']=='PASS'

def test_hosting_pass():
    p=parse_page('<title>File hosting for game mod creators</title><h1>Upload your files, share and earn</h1><a href="/upload">Upload mods</a><p>Earn from every download.</p>','https://publisher.org/')
    assert classify([p])['classification']=='PASS'

def test_shortener_pass():
    p=parse_page('<title>Paid URL shortener</title><h1>Shorten links and earn money</h1><a href="/signup">Shorten your URL</a><p>Publisher payouts</p>','https://publisher.org/')
    assert classify([p])['classification']=='PASS'

def test_agency_not_pass():
    p=parse_page('<title>Digital marketing agency</title><h1>APK streaming services</h1><a href="/download">Download</a><p>We build APK websites and game mods.</p>','https://publisher.org/')
    assert classify([p])['classification']!='PASS'

def test_faq_is_prioritized():assert 'https://publisher.org/faqs/' in contact_page_links(parse_page(STREAM,'https://publisher.org/'),'https://publisher.org/')

def test_extract_and_ignore_comments():
    html='''<h1>Contact</h1><p>Advertising: <a href="mailto:ads@publisher.org">Email ads</a></p>
    <p>hello [at] publisher [dot] org</p><div id="comments"><a href="mailto:visitor@other.org">visitor</a></div>
    <script>var e='analytics@thirdparty.org';</script><a href="https://t.me/share/url?url=x">Share</a>'''
    p=parse_page(html,'https://publisher.org/contact')
    vals={c.value for c in p.contacts}
    assert 'ads@publisher.org' in vals and 'hello@publisher.org' in vals
    assert 'visitor@other.org' not in vals and 'analytics@thirdparty.org' not in vals
    assert not any(c.kind=='telegram' for c in p.contacts)

def test_email_filters():
    assert normalized_email('x@example.com') is None
    assert normalized_email('icon@2x.png') is None
    assert normalized_email('admin@publisher.org')=='admin@publisher.org'

def test_cf_email():
    value='contact@publisher.org';key=42;encoded=bytes([key]+[ord(x)^key for x in value]).hex()
    p=parse_page(f'<h1>Contact</h1><a data-cfemail="{encoded}">protected</a>','https://publisher.org/contact')
    assert any(c.value==value and c.method=='cf_email_decode' for c in p.contacts)

def test_telegram_invites_and_share():
    cs=contact_from_link('https://t.me/%2BiHSsdgstQvgzM2Zl','Telegram','Contact','https://publisher.org/')
    assert cs[0].purpose=='community_invite'
    assert not contact_from_link('https://t.me/share/url?url=x','','','https://publisher.org/')
    c=contact_from_link('https://t.me/s/publishernews/123','Channel','News','https://publisher.org/')[0]
    assert c.value=='https://t.me/publishernews' and c.purpose=='community'

def test_whatsapp():
    c=contact_from_link('https://api.whatsapp.com/send?phone=%2B972501234567','Advertising','Advertising contact','https://publisher.org/')[0]
    assert c.value=='+972501234567' and c.kind=='whatsapp'
    assert not contact_from_link('https://wa.me/123','Contact','Contact','https://publisher.org/')

def test_no_phone_from_year():
    p=parse_page('<p>2026 123 Copyright. 150000 users.</p>','https://publisher.org/')
    assert not p.contacts

def test_form_detection():
    p=parse_page('<h1>Contact us</h1><form><input name="email"><textarea name="message"></textarea></form>','https://publisher.org/contact')
    assert any(c.kind=='contact_form' for c in p.contacts)
    p=parse_page('<form><input name="email"><button>Subscribe</button></form>','https://publisher.org/')
    assert not p.contacts

def test_legal_not_business():
    p=parse_page('<p>Copyright complaints: <a href="mailto:dmca@publisher.org">Contact</a></p>','https://publisher.org/')
    assert p.contacts[0].purpose=='legal_only'

class FakeDNS:
    async def check(self,email):return 'mx_present_mailbox_unverified'

@pytest.mark.asyncio
async def test_score_business_and_community(cfg):
    cfg['crawl']['verify_mx']=True
    cs=parse_page('<h1>Contact</h1><p>Partnerships <a href="mailto:ads@publisher.org">Advertising</a></p><a href="https://t.me/+ABC123abc">Telegram</a>','https://publisher.org/contact').contacts
    out=await score_contacts(cs,'https://publisher.org/',cfg,FakeDNS())
    assert out[0].kind=='email' and out[0].tier=='READY'
    assert next(c for c in out if c.kind=='telegram').tier=='COMMUNITY'

@pytest.mark.asyncio
async def test_dns_not_checked_not_ready(cfg):
    c=Contact('email','ads@publisher.org','https://publisher.org/contact','Advertising','mailto','business')
    out=await score_contacts([c],'https://publisher.org/',cfg)
    assert out[0].tier=='REVIEW'

@pytest.mark.asyncio
async def test_unconfirmed_telegram_not_ready(cfg):
    c=Contact('telegram','https://t.me/publisheradmin','https://publisher.org/contact','Advertising','explicit_telegram','business')
    assert (await score_contacts([c],'https://publisher.org/',cfg))[0].tier=='REVIEW'

@pytest.mark.asyncio
async def test_external_source_never_ready(cfg):
    c=Contact('email','ads@publisher.org','https://unrelated.org/','Advertising','hunter_domain_search','business')
    result=(await score_contacts([c],'https://publisher.org/',cfg))[0]
    assert result.tier!='READY' and result.association=='external_source_unconfirmed'

def test_db_budget_persists(db):
    assert db.reserve('serper',2,3,'lifetime')
    assert not db.reserve('serper',2,3,'lifetime')
    assert db.reserve('serper',1,3,'lifetime')
    assert not db.reserve('serper',1,3,'lifetime')

def test_dedup_override_suppression(db):
    assert db.add_site('https://www.publisher.org/')
    assert not db.add_site('http://publisher.org/a')
    assert db.set_override('publisher.org','PASS','Single app')
    assert db.rows('SELECT manual_decision FROM sites')[0]['manual_decision']=='PASS'
    db.purge('publisher.org')
    assert not db.add_site('https://publisher.org/')
    assert db.candidates(10)==[]

def test_csv_injection():
    text=csv_text([{'domain':'=cmd()'},{'domain':'+1234'},{'domain':'@sum(1)'}],['domain'])
    assert "'=cmd()" in text and "'+1234" in text and "'@sum(1)" in text

@pytest.mark.asyncio
async def test_dns_ssrf_guard():
    resolver=PublicResolver()
    class Delegate:
        async def resolve(self,*a):return [{'host':'127.0.0.1'}]
        async def close(self):pass
    resolver.delegate=Delegate()
    with pytest.raises(OSError):await resolver.resolve('evil.org',443)

class FakeFetcher:
    def __init__(self,pages):self.pages=pages;self.visited=[]
    async def fetch(self,url,**kwargs):
        self.visited.append(url)
        value=self.pages.get(url)
        return value if isinstance(value,Page) else Page(url=url,final_url=url,status=200 if value else 404,state='ok' if value else 'http_error',html=value or '')
    async def policy(self,url):return RobotsPolicy(True,None,'ok')
class FakeProviders:
    def available(self):return []
    async def search(self,q):return []
    async def commoncrawl_paths(self,d):return []
    async def hunter(self,d):return []

@pytest.mark.asyncio
async def test_pipeline_fixture(cfg,db):
    db.add_site('https://publisher.org/')
    f=FakeFetcher({'https://publisher.org/':APK,'https://publisher.org/contact':'<title>Contact</title><h1>Contact us</h1><form><input name="email"><textarea name="message"></textarea></form>'})
    engine=Engine(cfg,db)
    result=await engine.scan_site(db.rows('SELECT * FROM sites')[0],f,FakeProviders())
    assert result['classification']=='PASS' and result['contact_state']=='READY'
    assert db.rows('SELECT * FROM contacts')[0]['kind']=='contact_form'
    assert len(lead_rows(db,cfg))==1 and len(effective_contacts(db,cfg))==1
    assert not any(u.endswith('.apk') for u in f.visited)

@pytest.mark.asyncio
async def test_unreachable_not_reject(cfg,db):
    db.add_site('https://publisher.org/')
    f=FakeFetcher({'https://publisher.org/':Page(url='https://publisher.org/',state='robots_denied')})
    r=await Engine(cfg,db).scan_site(db.rows('SELECT * FROM sites')[0],f,FakeProviders())
    assert r['classification']=='REVIEW' and r['contact_state']=='NOT_CHECKED'

@pytest.mark.asyncio
async def test_cross_domain_redirect_not_attributed(cfg,db):
    db.add_site('https://publisher.org/')
    f=FakeFetcher({'https://publisher.org/':Page(url='https://publisher.org/',final_url='https://newbrand.org/',state='ok',status=200,html='<a href="mailto:ads@newbrand.org">Ads</a>')})
    r=await Engine(cfg,db).scan_site(db.rows('SELECT * FROM sites')[0],f,FakeProviders())
    assert r['classification']=='REVIEW' and not db.rows('SELECT * FROM contacts')
    assert db.rows("SELECT * FROM sites WHERE domain='newbrand.org'")

@pytest.mark.asyncio
async def test_telegram_channel_bio(cfg):
    original=Contact('telegram','https://t.me/publishernews','https://publisher.org/','Telegram contact','explicit_telegram','contact')
    f=FakeFetcher({'https://t.me/publishernews':'<div class="tgme_page_extra">1,234 subscribers</div><div class="tgme_page_description">Advertising: @publisherads</div>'})
    out=await inspect_public_telegram([original],f)
    assert out[0].purpose=='community'
    assert out[1].value=='https://t.me/publisherads'
    scored=await score_contacts(out,'https://publisher.org/',cfg)
    assert not any(c.tier=='READY' for c in scored)

def test_redirect_alias_dedup(db,cfg):
    db.add_site('https://publisher.org/')
    db.add_site('https://ww8.publisher.org/')
    db.save_result('publisher.org',{'final_url':'https://ww8.publisher.org/','classification':'PASS'},[],[])
    assert not db.add_site('https://ww8.publisher.org/contact')
    assert len(lead_rows(db,cfg))==1

def test_stale_contact_not_exported(db,cfg):
    db.add_site('https://publisher.org/')
    old=(datetime.now(timezone.utc)-timedelta(days=90)).isoformat()
    c=Contact('email','ads@publisher.org','https://publisher.org/contact','Advertising','mailto','business',score=90,tier='READY',observed_at=old)
    db.save_result('publisher.org',{'classification':'PASS','contact_state':'READY','best_contact':c.dict()},[c],[])
    with db.connect() as conn:conn.execute('UPDATE sites SET last_scan=?',(old,))
    assert effective_contacts(db,cfg)==[]
    assert lead_rows(db,cfg)[0]['contact_state']=='STALE'

@pytest.mark.asyncio
async def test_manual_override_survives_recheck(cfg,db):
    db.add_site('https://publisher.org/');db.set_override('publisher.org','PASS','Human approval')
    f=FakeFetcher({'https://publisher.org/':'<title>Welcome</title><p>Publisher page</p>'})
    await Engine(cfg,db).scan_site(db.rows('SELECT * FROM sites')[0],f,FakeProviders())
    assert db.rows('SELECT manual_decision FROM sites')[0]['manual_decision']=='PASS'

@pytest.mark.asyncio
async def test_full_run_offline_fixture_exports(cfg,db,monkeypatch,tmp_path):
    from leadengine import engine as module
    from pathlib import Path
    Path(cfg['base_dir'],'seeds.txt').write_text('https://publisher.org/\n')
    class ContextFetcher(FakeFetcher):
        def __init__(self,*args):super().__init__({'https://publisher.org/':APK,'https://publisher.org/contact':'<title>Contact</title><form><textarea></textarea></form>'})
        async def __aenter__(self):return self
        async def __aexit__(self,*args):pass
    class ContextProviders(FakeProviders):
        def __init__(self,*args):pass
        async def __aenter__(self):return self
        async def __aexit__(self,*args):pass
    monkeypatch.setattr(module,'Fetcher',ContextFetcher);monkeypatch.setattr(module,'Providers',ContextProviders)
    r=await Engine(cfg,db).run(discover=False)
    assert r['scanned']==1 and r['ready']==1
    assert Path(cfg['data_dir'],'exports','ready.csv').exists()
    assert db.rows('SELECT state FROM runs')[0]['state']=='complete'

@pytest.mark.asyncio
async def test_same_engine_run_overlap_rejected(cfg,db):
    engine=Engine(cfg,db);engine.busy=True
    with pytest.raises(RuntimeError):await engine.run(discover=False)
