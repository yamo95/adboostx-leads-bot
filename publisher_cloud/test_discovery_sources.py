import asyncio
import json
import unittest
from unittest.mock import patch
from bs4 import BeautifulSoup
import discovery_sources as d
import fresh_discovery as f
import messaging_enrichment as m

class DiscoveryTests(unittest.TestCase):
    def test_rotation_and_all_niches(self):
        first=d.query_plan(35);second=d.query_plan(36)
        self.assertEqual(len(first),12)
        self.assertEqual({r['family'] for r in first},set(d.FAMILIES))
        self.assertFalse({r['query'] for r in first}&{r['query'] for r in second})
        self.assertEqual(first,d.query_plan(35))
    def test_ddg_old_and_new_markup(self):
        for cls in ['result__a','result-link']:
            rows,state=d.parse_search('<a class="'+cls+'" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fpublisher.example%2Fcontact">Contact @NotEvidence</a>','duckduckgo-html')
            self.assertEqual(rows,['https://publisher.example/contact']);self.assertEqual(state,'results')
    def test_challenge_is_not_zero_results(self):
        self.assertEqual(d.parse_search('<form id="challenge-form">Unfortunately bots use DuckDuckGo too.</form>','duckduckgo-html'),([], 'challenge'))
    def test_markup_failure_distinguished_from_empty(self):
        self.assertEqual(d.parse_search('<html>Some other page</html>','duckduckgo-html')[1],'unexpected_markup')
        self.assertEqual(d.parse_search('<div class="no-results">No results found</div>','duckduckgo-html')[1],'no_results')
    def test_rss_no_third_party_contact_import(self):
        text='<rss><channel><item><link>https://publisher.example/contact</link><description>Message @NotEvidence +12345678901</description></item></channel></rss>'
        rows,state=d.parse_search(text,'bing-rss');self.assertEqual(rows,['https://publisher.example/contact']);self.assertEqual(state,'results')
    def test_xml_entities_and_wrong_root_rejected(self):
        self.assertEqual(d.parse_search('<!DOCTYPE rss><rss/>','bing-rss')[1],'invalid_xml')
        self.assertEqual(d.parse_search('<html/>','bing-rss')[1],'unexpected_markup')
    def test_private_social_binary_and_iptv_filtered(self):
        for u in ['http://127.0.0.1/contact','https://publisher.example/a.apk','https://t.me/Someone','https://youtube.com/a','https://best-iptv.com/','https://u:p@publisher.example/']:
            self.assertIsNone(d.clean_candidate(u),u)
    def test_health_distinguishes_blocked_and_valid_empty(self):
        self.assertEqual(d.health([{'state':'challenge','candidates':0}])['state'],'unavailable')
        self.assertEqual(d.health([{'state':'no_results','candidates':0}])['state'],'available')
        self.assertEqual(d.health([{'state':'results','candidates':1},{'state':'http_429','candidates':0}])['state'],'degraded')
    def test_independent_provider_failover_and_circuit_break(self):
        class Fake:
            async def __aenter__(self):return self
            async def __aexit__(self,*_):pass
            async def get(self,*args,**kw):return {'state':'ok','html':'<form id="challenge-form">blocked</form>','status':202}
        async def rss(*_):return {'state':'ok','status':200,'html':'<rss><channel><item><link>https://new.example/contact</link></item></channel></rss>'}
        with patch.object(d.scan,'Fetcher',Fake),patch.object(d,'fetch_rss',side_effect=rss):
            rows,checks=asyncio.run(d.discover())
        self.assertEqual(rows,['https://new.example/contact'])
        self.assertEqual(sum(c['provider']=='duckduckgo-html' for c in checks),1)
        self.assertEqual(sum(c['provider']=='bing-rss' for c in checks),12)
    def test_unapproved_rss_endpoint_never_requested(self):
        with self.assertRaises(ValueError):asyncio.run(d.fetch_rss(None,'https://evil.example/rss'))

class PlanTests(unittest.TestCase):
    def test_versioned_recheck_does_not_masquerade_as_new(self):
        seen={f.host_key('old.example'),f.host_key('skip.example')}
        p=f.build_plan('a'*32,['https://old.example/','https://skip.example/','https://new.example/'],seen,recheck={f.host_key('old.example')})
        self.assertEqual(p['urls'],['https://new.example/','https://old.example/'])
        self.assertEqual(p['new_candidate_sites'],1);self.assertEqual(p['recheck_sites'],1);self.assertEqual(p['known_sites_skipped'],1)
        self.assertEqual(f.metadata(p,0)['recheck_sites'],1)
        self.assertEqual(f.metadata(p,0)['extraction_revision'],'messaging-intent-v3')
    def test_no_unrequested_recycling(self):
        p=f.build_plan('a'*32,['https://old.example/'],{f.host_key('old.example')})
        self.assertEqual(p['urls'],[])
    def test_recheck_budget_and_frozen_old_plan(self):
        with self.assertRaises(ValueError):f.build_plan('a'*32,[],set(),recheck={str(i) for i in range(81)})
        p=f.build_plan('a'*32,['https://new.example/'],set());p.pop('recheck_sites');p.pop('discovery_health')
        self.assertIs(f.validate_plan(p,'a'*32),p)

class ContactIntentTests(unittest.TestCase):
    def contacts(self,html):
        desc=BeautifulSoup('<div>'+html+'</div>','html.parser').div
        return m.from_description(desc,'https://t.me/SiteNews','https://publisher.example/')
    def test_admin_is_general_contact_not_claimed_owner(self):
        rows=self.contacts('Admin: @FixtureAdmin');self.assertEqual(len(rows),1);self.assertEqual(rows[0]['role'],'contact')
    def test_split_advertising_label_and_handle(self):
        rows=self.contacts('Advertising:<br><a href="https://t.me/FixtureAds">@FixtureAds</a>')
        self.assertEqual(rows[0]['role'],'business');self.assertEqual(rows[0]['via'],'https://publisher.example/')
    def test_does_not_carry_intent_into_friends(self):
        self.assertEqual(self.contacts('Advertising:<br>Our friends @FriendFixture'),[])
    def test_multilingual_admin(self):
        for label in ['\u0410\u0434\u043c\u0438\u043d:', '\u0644\u0644\u062a\u0648\u0627\u0635\u0644:', '\u8054\u7cfb:']:
            self.assertEqual(len(self.contacts(label+' @FixtureAdmin')),1,label)
    def test_bot_still_bot_and_declines_honoured(self):
        rows=self.contacts('Admin: @FixtureAdminBot');self.assertEqual(rows[0]['profile_type'],'bot')
        self.assertEqual(self.contacts('No ads contact @FixtureAdmin'),[])
    def test_legal_seo_excluded(self):
        self.assertEqual(self.contacts('Guest post backlinks admin: @FixtureAdmin'),[])
        self.assertEqual(self.contacts('DMCA admin: @FixtureAdmin'),[])

if __name__=='__main__':unittest.main()
