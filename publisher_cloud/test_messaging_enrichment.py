import asyncio
import unittest
from bs4 import BeautifulSoup
import messaging_enrichment as m

class Fixture:
    def __init__(self,pages):self.pages=pages;self.calls=[]
    async def get(self,u,**kw):
        self.calls.append(u)
        return self.pages.get(u,{'state':'blocked'})

def page(desc,kind='12 subscribers'):
    return {'state':'ok','html':f'<div class="tgme_page_extra">{kind}</div><div class="tgme_page_description">{desc}</div>'}

class EnrichmentTests(unittest.TestCase):
    def test_line_boundaries(self):
        desc=BeautifulSoup('Support: <a>@HelpDemo</a><br>Advertising: <a>@AdsDemo</a><br>Our friend: <a>@FriendDemo</a>','html.parser')
        rows=m.from_description(desc,'https://t.me/ChannelDemo','https://one.example/')
        self.assertEqual({r['contact']:r['role'] for r in rows},{'@HelpDemo':'support','@AdsDemo':'business'})
    def test_description_links(self):
        desc=BeautifulSoup('Business: <a href="https://t.me/AdsDemo">Contact us</a>','html.parser')
        self.assertEqual(m.from_description(desc,'https://t.me/ChannelDemo','https://one.example/')[0]['contact'],'@AdsDemo')
    def test_description_email(self):
        desc=BeautifulSoup('Partnership: contact@one.example','html.parser')
        rows=m.from_description(desc,'https://t.me/ChannelDemo','https://one.example/')
        self.assertEqual(rows[0]['channel'],'email')
    def test_legal_not_business(self):
        desc=BeautifulSoup('DMCA: legal@one.example','html.parser')
        self.assertEqual(m.from_description(desc,'https://t.me/ChannelDemo','https://one.example/'),[])
    def test_seo_not_business(self):
        desc=BeautifulSoup('Business guest posts: @AdsDemo','html.parser')
        self.assertEqual(m.from_description(desc,'https://t.me/ChannelDemo','https://one.example/'),[])
    def test_plain_number_not_whatsapp(self):
        desc=BeautifulSoup('Contact: +447311131281','html.parser')
        self.assertEqual(m.from_description(desc,'https://t.me/ChannelDemo','https://one.example/'),[])
    def test_explicit_whatsapp(self):
        desc=BeautifulSoup('Contact WhatsApp: +447311131281','html.parser')
        self.assertEqual(m.from_description(desc,'https://t.me/ChannelDemo','https://one.example/')[0]['channel'],'whatsapp')
    def test_unlabelled_handle_ignored(self):
        desc=BeautifulSoup('Friends @OtherDemo','html.parser')
        self.assertEqual(m.from_description(desc,'https://t.me/ChannelDemo','https://one.example/'),[])
    def test_cyrillic_contacts(self):
        desc=BeautifulSoup('\u041a\u043e\u043d\u0442\u0430\u043a\u0442\u044b: @OwnerDemo','html.parser')
        self.assertEqual(m.from_description(desc,'https://t.me/ChannelDemo','https://one.example/')[0]['role'],'contact')
    def test_invite_public_description_not_join(self):
        url='https://t.me/+PublicInvite'
        f=Fixture({url:page('Advertising: @AdsDemo'),'https://t.me/AdsDemo':{'state':'ok','html':'Send Message'}})
        start=m.scan.route(url,'Channel','https://one.example/')
        out=asyncio.run(m.enriched_hops([start],f))
        self.assertEqual(len(out),2);self.assertEqual(out[0]['profile_type'],'community')
        self.assertEqual(out[1]['via'],'https://one.example/');self.assertEqual(out[1]['profile_type'],'contact_preview')
        self.assertEqual(f.calls,[url,'https://t.me/AdsDemo'])
    def test_no_deep_channel_recursion(self):
        f=Fixture({'https://t.me/ChannelDemo':page('Advertising: @AdsDemo'),'https://t.me/AdsDemo':page('Business: @NextDemo')})
        out=asyncio.run(m.enriched_hops([m.scan.route('https://t.me/ChannelDemo','Channel','https://one.example/')],f))
        self.assertNotIn('@NextDemo',[r['contact'] for r in out])
    def test_bounded_requests(self):
        contacts=[m.scan.route('https://t.me/Person'+str(i),'Contact','https://one.example/') for i in range(25)]
        f=Fixture({});asyncio.run(m.enriched_hops(contacts,f));self.assertEqual(len(f.calls),8)
    def test_preview_cache(self):
        f=Fixture({'https://t.me/PersonDemo':page('',kind='')})
        async def both():
            await asyncio.gather(m.get_preview(f,'https://t.me/PersonDemo'),m.get_preview(f,'https://t.me/PersonDemo'))
        asyncio.run(both());self.assertEqual(len(f.calls),1)
    def test_invite_codes_case_sensitive(self):
        self.assertNotEqual(m.preview_key('https://t.me/+Abc'),m.preview_key('https://t.me/+abc'))
    def test_whatsapp_code_case_sensitive(self):
        self.assertNotEqual(m.preview_key('https://wa.link/Abc'),m.preview_key('https://wa.link/abc'))
    def test_query_cache_separation(self):
        self.assertNotEqual(m.preview_key('https://wa.me/message/AB?x=1'),m.preview_key('https://wa.me/message/AB?x=2'))
    def test_whatsapp_short_resolution(self):
        u='https://wa.link/abc123';f=Fixture({u:{'state':'cross_site_redirect','final_url':'https://api.whatsapp.com/send?phone=447311131281'}})
        rows=asyncio.run(m.enriched_hops([m.scan.route(u,'Contact support','https://one.example/')],f))
        self.assertEqual(len(rows),2);self.assertEqual(rows[1]['contact'],'+447311131281')
    def test_short_redirect_rejects_other_host(self):
        u='https://wa.link/abc123';f=Fixture({u:{'state':'cross_site_redirect','final_url':'https://evil.example/?phone=447311131281'}})
        self.assertEqual(len(asyncio.run(m.enriched_hops([m.scan.route(u,'Contact','https://one.example/')],f))),1)
    def test_script_not_source(self):
        desc=BeautifulSoup('<script>Business @AdsDemo</script>','html.parser')
        self.assertEqual(m.from_description(desc,'https://t.me/ChannelDemo','https://one.example/'),[])
    def test_bot_remains_bot(self):
        desc=BeautifulSoup('Business: @AdsDemoBot','html.parser')
        self.assertEqual(m.from_description(desc,'https://t.me/ChannelDemo','https://one.example/')[0]['profile_type'],'bot')
    def test_no_ads_respected(self):
        desc=BeautifulSoup('No ads. Contact @AdsDemo','html.parser')
        self.assertEqual(m.from_description(desc,'https://t.me/ChannelDemo','https://one.example/'),[])

if __name__=='__main__':unittest.main()
