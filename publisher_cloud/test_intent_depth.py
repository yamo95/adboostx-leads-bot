import asyncio
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch,AsyncMock
import intent_depth as subject

class Fixture:
    def __init__(self,html='',slow=False):self.html=html;self.calls=[];self.slow=slow
    async def get(self,url,**kwargs):
        self.calls.append((url,kwargs))
        if self.slow and len(self.calls)>1:await asyncio.sleep(1)
        return {'state':'ok','final_url':url,'html':self.html if len(self.calls)==1 else '<p>Contact our team</p>','status':200}

class IntentTests(unittest.TestCase):
    def test_configuration(self):self.assertEqual(len(subject.targets()),119)
    def test_targets_unique(self):self.assertEqual(len(set(map(subject.scan.host,subject.targets()))),119)
    def test_targets_no_query(self):self.assertTrue(all('?' not in u for u in subject.targets()))
    def test_public_post(self):self.assertEqual(subject.document_url('https://t.me/PublicDemo/45'),'https://t.me/PublicDemo/45?embed=1&mode=tme')
    def test_article(self):self.assertEqual(subject.document_url('https://telegra.ph/Contact-09-10'),'https://telegra.ph/Contact-09-10')
    def test_not_private_invite(self):self.assertIsNone(subject.document_url('https://t.me/+private'))
    def test_not_profile_document(self):self.assertIsNone(subject.document_url('https://t.me/OwnerExample'))
    def test_not_login(self):self.assertIsNone(subject.document_url('https://t.me/login?token=abc'))
    def test_no_arbitrary_domain(self):self.assertIsNone(subject.document_url('https://other.example/contact'))
    def test_label_required(self):self.assertEqual(subject.linked_documents('<p><a href="https://t.me/PublicDemo/45">Sponsored unrelated news</a></p>','https://site.example/'),[])
    def test_contact_label(self):self.assertEqual(len(subject.linked_documents('<p>Contact us: <a href="https://t.me/PublicDemo/45">Details</a></p>','https://site.example/')),1)
    def test_comment_excluded(self):self.assertEqual(subject.linked_documents('<div class="comment"><p>Contact us: <a href="https://t.me/PublicDemo/45">Details</a></p></div>','https://site.example/'),[])
    def test_ads_role(self):self.assertEqual(subject.intent_role('Ads: @OwnerExample','https://t.me/ChannelExample'),'business')
    def test_support_separate(self):self.assertEqual(subject.intent_role('Support: @OwnerExample','https://t.me/ChannelExample'),'support')
    def test_seo_hold(self):self.assertEqual(subject.intent_role('Backlinks Ads: @OwnerExample','https://t.me/ChannelExample'),'seo_service')
    def test_standard_delegates(self):
        with patch.dict(os.environ,{'SEARCH_DEPTH':'standard'}),patch.object(subject.fresh_discovery,'main',return_value=19) as call:
            self.assertEqual(subject.main(),19);call.assert_called_once()
    def test_schedule_cannot_opt_in(self):
        with patch.dict(os.environ,{'SEARCH_DEPTH':'focused','GITHUB_EVENT_NAME':'schedule'}):
            with self.assertRaises(ValueError):subject.main()
    def test_more_than_eight_pages(self):
        html=''.join('<a href="/contact/%d">Contact</a>'%i for i in range(30))
        f=Fixture(html)
        with patch.object(subject,'deeper_hops',AsyncMock(side_effect=lambda c,*_:c)):
            s,c,r=asyncio.run(subject.scan_site('https://publisher.example/',f))
        self.assertEqual(s['page_attempts'],18);self.assertTrue(all(k['site']=='https://publisher.example/' for u,k in f.calls))
    def test_advertising_first(self):
        f=Fixture('<a href="/about-us">About</a><a href="/advertise">Advertise</a>')
        with patch.object(subject,'deeper_hops',AsyncMock(side_effect=lambda c,*_:c)):
            asyncio.run(subject.scan_site('https://publisher.example/',f))
        self.assertTrue(f.calls[1][0].endswith('/advertise'))
    def test_does_not_follow_download(self):
        f=Fixture('<a href="/download/file.apk">Contact download</a>')
        with patch.object(subject,'deeper_hops',AsyncMock(side_effect=lambda c,*_:c)):
            asyncio.run(subject.scan_site('https://publisher.example/',f))
        self.assertFalse(any('.apk' in u for u,k in f.calls))
    def test_timeout_keeps_evidence(self):
        f=Fixture('<p>Contact <a href="https://t.me/OwnerExample">Contact owner</a></p>',True)
        with patch.object(subject,'PAGE_SECONDS',0.01),patch.object(subject,'deeper_hops',AsyncMock(side_effect=lambda c,*_:c)):
            s,c,r=asyncio.run(subject.scan_site('https://publisher.example/',f))
        self.assertGreater(len(c),0);self.assertEqual(s['html_pages_opened'],1);self.assertIn('website_time_budget',s['partial_reasons'])
    def test_main_restores_core_hooks(self):
        with TemporaryDirectory() as folder:
            root=Path(folder);(root/'seeds.txt').write_text('original\n');fn=subject.scan.scan_site;role=subject.messaging.extended_role
            with patch.object(subject.scan,'ROOT',root),patch.dict(os.environ,{'SEARCH_DEPTH':'focused','GITHUB_EVENT_NAME':'push'}):
                with patch.object(subject.scan,'main',return_value=0) as stub:
                    stub.__globals__={'_save_operator_copy':lambda x:x}
                    self.assertEqual(subject.main(),0)
            self.assertIs(subject.scan.scan_site,fn);self.assertIs(subject.messaging.extended_role,role);self.assertEqual((root/'seeds.txt').read_text(),'original\n')

if __name__=='__main__':unittest.main()
