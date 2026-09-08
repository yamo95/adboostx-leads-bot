import unittest
from unittest.mock import patch
import delivery as d
class DeliveryTests(unittest.TestCase):
    def setUp(self): d.PAGES.clear()
    def test_no_comment_contacts(self):
        c,_,_=d.audited_parse('<div id="comments"><a href="https://t.me/Someone">Contact</a></div>','https://publisher.example/contact')
        self.assertEqual(c,[])
    def test_wa_mismatch_held(self):
        c,_,_=d.audited_parse('<a href="https://wa.me/447380143621">WhatsApp +447380143622</a>','https://publisher.example/contact')
        self.assertEqual(c[0]['profile_type'],'short_link_unresolved')
    def test_community_not_person(self):
        c,_,_=d.audited_parse('<a href="https://t.me/OurChannel">Join our channel</a>','https://publisher.example/')
        self.assertEqual(c[0]['profile_type'],'community')
    def test_legal(self):
        c,_,_=d.audited_parse('<a href="mailto:abuse@publisher.example">Copyright claims</a>','https://publisher.example/contact')
        self.assertEqual(c[0]['role'],'legal')
    def test_nofollow(self):
        _,links,_=d.audited_parse('<meta name="robots" content="nofollow"><a href="/contact">Contact</a>','https://publisher.example/')
        self.assertEqual(links,[])
    def test_single_app(self):
        d.audited_parse('<title>Honista APK</title><h1>Honista APK</h1><a href="/download">Download APK</a>','https://publisher.example/')
        p={'sites':[{'domain':'publisher.example'}],'contacts':[],'files':{},'summary':{}}
        with patch.object(d,'BASE_SEAL',side_effect=lambda p,k:p):
            self.assertEqual(d.corrected_seal(p,None)['sites'][0]['site_fit'],'PASS')
    def test_unreachable_review(self):
        p={'sites':[{'domain':'publisher.example'}],'contacts':[],'files':{},'summary':{}}
        with patch.object(d,'BASE_SEAL',side_effect=lambda p,k:p):
            self.assertEqual(d.corrected_seal(p,None)['sites'][0]['site_fit'],'REVIEW')
    def test_discovery_failure_not_fatal(self):
        with patch.object(d.urllib.request,'urlopen',side_effect=OSError):
            self.assertEqual(d.discover([]),[])

class HopsTests(unittest.IsolatedAsyncioTestCase):
    async def test_site_linked_channel_yields_business_handle(self):
        c,_,_=d.audited_parse('<a href="https://t.me/OurChannel">Join our channel</a>','https://publisher.example/')
        class Fetcher:
            async def get(self,url,**kwargs):
                if url.endswith('OurChannel'):
                    return {'state':'ok','html':'<div class="tgme_page_extra">100 subscribers</div><div class="tgme_page_description">Business: @OurManager</div>'}
                return {'state':'ok','html':'<div>Send Message</div>'}
        out=await d.telegram_hops(c,Fetcher())
        manager=next(x for x in out if x['contact']=='@OurManager')
        self.assertEqual(manager['profile_type'],'contact_preview')
        self.assertEqual(manager['via'],'https://publisher.example/')
        self.assertEqual(manager['role'],'business')
if __name__=='__main__': unittest.main()
