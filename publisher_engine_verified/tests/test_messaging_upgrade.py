"""Synthetic regression fixtures. Not a live crawl or a precision/recall benchmark."""
import pytest
from bs4 import BeautifulSoup
from leadengine.parse import parse_page,contact_from_link,normalized_phone
from leadengine.telegram import bio_contacts,inspect_public_telegram
from leadengine.quality import score_contacts
from leadengine.export import contact_clusters,write_exports,effective_contacts
from leadengine.models import Contact,Page
from leadengine.engine import Engine

BASE='https://publisher.org/contact'
NUMBER='+254781156568'

def one(url,label='Business contact',context='Business contact'):
    return contact_from_link(url,label,context,BASE)[0]

@pytest.mark.parametrize('url',[
    'https://wa.me/254781156568',
    'https://api.whatsapp.com/send?phone=%2B254781156568&text=hello',
    'https://web.whatsapp.com/send?phone=254781156568',
    'whatsapp://send?phone=254781156568',
    'https://wa.me/%2B254781156568',
])
def test_phone_link_variants(url):
    c=one(url)
    assert c.kind=='whatsapp' and c.value==NUMBER
    assert c.contact_url=='https://wa.me/254781156568' and 'hello' not in c.contact_url

@pytest.mark.parametrize('url',[
    'https://wa.link/sd39wm','https://wa.me/message/ABCD1234567',
    'https://t.me/m/ABCD1234567',
])
def test_business_short_links_not_invented_phone_or_person(url):
    c=one(url)
    assert c.value==url and c.verification=='published_short_link_unresolved'

@pytest.mark.parametrize('url',[
    'https://wa.me/123','https://wa.me/1234567890','https://wa.me/000000000',
    'https://wa.me/1234bad5678','https://wa.me/1234567890123456',
    'https://wa.me:bad/254781156568','https://wa.me:8000/254781156568',
    'https://user:secret@wa.me/254781156568',
    'https://api.whatsapp.com/send?phone=254781156568&phone=254781156569',
    'https://api.whatsapp.com/other?phone=254781156568',
    'https://t.me:bad/publisherads','https://t.me:8000/publisherads',
    'https://wa.me.evil.org/254781156568',
])
def test_invalid_messenger_inputs(url):
    assert not contact_from_link(url,'Contact','Business',BASE)

@pytest.mark.parametrize('url',[
    'https://chat.whatsapp.com/ABCDEF123456',
    'https://www.whatsapp.com/channel/ABCDEF123456',
])
def test_whatsapp_communities_are_not_direct_contacts(url):
    assert one(url).purpose=='community_invite'

@pytest.mark.parametrize('path',['share/url?url=x','proxy?x=1','socks?x=1','addstickers/MyPack','addemoji/MyPack','addlist/AAA','boost/MyChannel','c/123/3','login','iv?url=x'])
def test_telegram_special_commands_not_people(path):
    assert not contact_from_link('https://t.me/'+path,'Contact','Contact',BASE)

def test_telegram_valid_name_starting_with_command_is_allowed():
    assert one('https://t.me/shareholders_help').value.endswith('shareholders_help')

def test_printed_labeled_whatsapp_and_telegram():
    p=parse_page('<p>Business WhatsApp: +254 781 156 568</p><p>Telegram: @BusinessDesk</p>',BASE)
    assert {c.value for c in p.contacts}=={NUMBER,'https://t.me/BusinessDesk'}

def test_plain_phone_and_at_name_not_assumed_messengers():
    assert not parse_page('<p>Phone +254 781 156 568</p><p>@BusinessDesk</p>',BASE).contacts

def test_local_number_without_country_not_invented():
    assert not parse_page('<p>WhatsApp: 0781156568</p>',BASE).contacts

def test_form_template_and_hidden_examples_are_not_contacts():
    p=parse_page('<form><p>WhatsApp: +254781156568</p><a href="https://t.me/InputExample">Example</a><i data-whatsapp="254781156568"></i></form><template><a href="https://wa.me/254781156568">Contact</a></template><div hidden>Telegram: @HiddenExample</div><p aria-hidden="true">WhatsApp: +254781156568</p>',BASE)
    assert not p.contacts

def test_data_attribute_full_url_not_double_prefixed():
    p=parse_page('<div data-whatsapp="https://wa.me/254781156568">Contact</div>',BASE)
    assert len(p.contacts)==1 and p.contacts[0].value==NUMBER

def test_case_insensitive_telegram_dedup_with_same_source():
    p=parse_page('<p><a href="https://t.me/BUSINESSdesk">Contact</a></p><p><a href="https://telegram.me/businessDESK">Contact</a></p>',BASE)
    assert len([c for c in p.contacts if c.kind=='telegram'])==1

def test_display_link_mismatch_is_not_silently_corrected():
    c=one('https://wa.me/254781156568',label='WhatsApp +254 781 156 569')
    assert c.verification=='display_link_mismatch' and c.value==NUMBER

@pytest.mark.asyncio
async def test_mismatch_cannot_be_ready(cfg):
    c=one('https://wa.me/254781156568',label='WhatsApp +254 781 156 569')
    out=await score_contacts([c],BASE,cfg)
    assert out[0].tier=='REVIEW'

@pytest.mark.asyncio
async def test_unresolved_short_cannot_be_ready(cfg):
    out=await score_contacts([one('https://wa.link/sd39wm')],BASE,cfg)
    assert out[0].tier=='REVIEW'

@pytest.mark.asyncio
async def test_seo_sales_not_monetization_ready(cfg):
    c=one('https://wa.me/254781156568',context='Guest posts and niche edits business inquiries')
    out=await score_contacts([c],BASE,cfg)
    assert c.purpose=='seo_service' and out[0].tier=='EXCLUDED'

def bio(text):
    return bio_contacts(BeautifulSoup('<div>'+text+'</div>','html.parser').div,'https://t.me/PublisherChannel')

@pytest.mark.parametrize('role',['Advertising','Business cooperation','Paid promotions','Reklama','\u0420\u0435\u043a\u043b\u0430\u043c\u0430','\u5e7f\u544a'])
def test_explicit_multilingual_business_bio(role):
    cs=bio(role+': @TheBusinessDesk')
    assert len(cs)==1 and cs[0].purpose=='business'

def test_role_is_not_shared_with_legal_or_unlabelled_names():
    cs=bio('Advertising: @TheAdsDesk<br>DMCA: @TheLegalDesk<br>Friends: @TheFriendDesk')
    assert [c.value for c in cs]==['https://t.me/TheAdsDesk']

def test_multiline_role_and_href_only_handle():
    cs=bio('Business cooperation:<br><a href="https://t.me/TheAdsDesk">Talk to us</a>')
    assert len(cs)==1 and cs[0].purpose=='business'

def test_no_ads_opt_out_not_prospect():
    assert not bio('No advertising: @TheAdsDesk')

class Fetcher:
    def __init__(self,pages):self.pages=pages;self.visited=[]
    async def fetch(self,url,**kwargs):
        self.visited.append(url);html=self.pages.get(url)
        return Page(url=url,final_url=url,status=200 if html else 404,state='ok' if html else 'http_error',html=html or '')

def channel(bio):return '<div class="tgme_page_extra">1,000 subscribers</div><div class="tgme_page_description">'+bio+'</div>'
def seed():return Contact('telegram','https://t.me/PublisherChannel',BASE,'Official Telegram','explicit_telegram','community')
DIRECT='<p>If you have Telegram, you can contact Business Desk right away.</p><a>Send Message</a>'

@pytest.mark.asyncio
async def test_two_hop_bio_business_profile_and_provenance(cfg):
    f=Fetcher({'https://t.me/PublisherChannel':channel('Advertising @TheAdsDesk'), 'https://t.me/TheAdsDesk':DIRECT})
    cs=await inspect_public_telegram([seed()],f,max_profiles=2)
    assert f.visited==['https://t.me/PublisherChannel','https://t.me/TheAdsDesk']
    c=next(c for c in cs if c.value.endswith('TheAdsDesk'))
    assert c.verification=='public_contact_profile_observed' and any('Evidence chain:' in n for n in c.notes)
    await score_contacts(cs,BASE,cfg)
    assert c.association=='linked_profile_business_contact' and c.tier=='REVIEW'

@pytest.mark.asyncio
async def test_shared_budget_and_business_first():
    f=Fetcher({'https://t.me/PublisherChannel':channel('Ads @TheAdsDesk<br>Support @TheHelpDesk'),'https://t.me/TheAdsDesk':DIRECT})
    cs=await inspect_public_telegram([seed()],f,max_profiles=2)
    assert f.visited==['https://t.me/PublisherChannel','https://t.me/TheAdsDesk']
    assert next(c for c in cs if c.value.endswith('TheHelpDesk')).verification=='profile_not_checked_budget'

@pytest.mark.asyncio
async def test_no_bot_started():
    f=Fetcher({'https://t.me/PublisherChannel':channel('Advertising @Business_bot')})
    cs=await inspect_public_telegram([seed()],f)
    assert len(f.visited)==1 and cs[1].purpose=='bot'

@pytest.mark.asyncio
async def test_bot_page_even_without_bot_suffix():
    f=Fetcher({'https://t.me/PublisherChannel':'<div class="tgme_page_extra">bot</div><a>Start Bot</a>'})
    cs=await inspect_public_telegram([seed()],f)
    assert cs[0].purpose=='bot' and cs[0].verification=='public_bot_page_observed'

@pytest.mark.asyncio
async def test_second_hop_channel_does_not_expand_forever():
    f=Fetcher({'https://t.me/PublisherChannel':channel('Advertising @TheAdsDesk'),'https://t.me/TheAdsDesk':channel('Advertising @NextAdsDesk')})
    cs=await inspect_public_telegram([seed()],f)
    assert len(f.visited)==2 and not any(c.value.endswith('NextAdsDesk') for c in cs)

@pytest.mark.asyncio
async def test_channel_posts_and_other_people_are_not_scraped():
    html=channel('Latest updates')+'<div class="tgme_widget_message_text">Advertising @UnrelatedPoster</div>'
    f=Fetcher({'https://t.me/PublisherChannel':html})
    cs=await inspect_public_telegram([seed()],f)
    assert len(cs)==1

@pytest.mark.asyncio
async def test_zero_preview_budget_makes_no_requests():
    f=Fetcher({});cs=await inspect_public_telegram([seed()],f,max_profiles=0)
    assert not f.visited and len(cs)==1

@pytest.mark.asyncio
async def test_failed_profile_not_claimed_verified():
    f=Fetcher({});cs=await inspect_public_telegram([seed()],f)
    assert cs[0].verification=='telegram_preview_unavailable'

class Provider:
    def __init__(self):self.queries=[];self.hunters=[]
    def available(self):return ['fixture']
    async def search(self,q):self.queries.append(q);return [{'url':'https://publisher.org/advertise'}]
    async def commoncrawl_paths(self,d):return []
    async def hunter(self,d):self.hunters.append(d);return []

@pytest.mark.asyncio
async def test_email_does_not_stop_messaging_recovery(cfg,db):
    db.add_site('https://publisher.org/')
    html='<title>Honista APK download</title><h1>Honista Android app</h1><a href="/download">Download APK</a><p>Business <a href="mailto:ads@publisher.org">Email</a></p>'
    f=Fetcher({'https://publisher.org/':html,'https://publisher.org/advertise':'<h1>Advertising</h1><a href="https://wa.me/254781156568">WhatsApp business</a>'})
    p=Provider();engine=Engine(cfg,db)
    await engine.scan_site(db.rows('SELECT * FROM sites')[0],f,p)
    assert len(p.queries)==1 and 'whatsapp' in p.queries[0].lower()
    assert not p.hunters and any(r['kind']=='whatsapp' for r in db.rows('SELECT * FROM contacts'))
    assert len(f.visited)<=cfg['crawl']['max_pages_per_site']

@pytest.mark.asyncio
async def test_recovery_cap_is_not_bypassed(cfg,db):
    db.add_site('https://publisher.org/')
    f=Fetcher({'https://publisher.org/':'<title>Honista APK download</title><h1>Honista Android app</h1><a href="/download">Download APK</a><p>Business <a href="mailto:ads@publisher.org">Email</a></p>'})
    p=Provider();e=Engine(cfg,db);e.contact_queries=cfg['search']['contact_queries_per_run']
    await e.scan_site(db.rows('SELECT * FROM sites')[0],f,p)
    assert not p.queries

def test_shared_route_casefold_clusters_and_not_proven_owners():
    rows=[{'domain':'a.org','kind':'telegram','value':'https://t.me/SharedDesk','source_url':'https://a.org/contact','purpose':'contact'},
          {'domain':'b.org','kind':'telegram','value':'https://t.me/shareddesk','source_url':'https://b.org/contact','purpose':'contact'}]
    groups=contact_clusters(rows)
    assert len(groups)==1 and groups[0]['domain_count']==2
    assert 'NOT established' in groups[0]['action']

def test_channel_and_legal_routes_do_not_create_outreach_clusters():
    rows=[{'domain':d,'kind':'telegram','value':'https://t.me/Shared','source_url':'https://'+d+'/contact','purpose':'community'} for d in ['a.org','b.org']]
    assert not contact_clusters(rows)

def test_cluster_export_exists_on_empty_database(cfg,db):
    from pathlib import Path
    Path(cfg['data_dir']).mkdir(parents=True,exist_ok=True)
    out=write_exports(db,cfg)
    assert (out/'contact_clusters.csv').exists()


def test_two_explicitly_joined_ads_handles_keep_the_role():
    cs=bio('Advertising: @FirstAdsDesk \u2014 @SecondAdsDesk')
    assert len(cs)==2 and all(c.purpose=='business' for c in cs)

def test_unrelated_second_handle_does_not_inherit_role():
    cs=bio('Advertising: @FirstAdsDesk Friends: @SomeOtherPerson')
    assert len(cs)==1
