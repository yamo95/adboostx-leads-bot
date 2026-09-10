import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import fresh_discovery as f
import contact_context as c
import scan

class FreshTests(unittest.TestCase):
    def test_skip_known_before_crawl(self):
        p=f.build_plan('a'*32,['https://old.example/','https://new.example/'],{f.host_key('old.example')})
        self.assertEqual(p['urls'],['https://new.example/']); self.assertEqual(p['known_sites_skipped'],1)
    def test_no_recycle_when_all_seen(self):
        self.assertEqual(f.build_plan('a'*32,['https://old.example/'],{f.host_key('old.example')})['urls'],[])
    def test_canonical_host(self):
        self.assertEqual(f.host_key('WWW.Old.Example'),f.host_key('old.example'))
    def test_prefer_contact_page(self):
        p=f.build_plan('a'*32,['https://new.example/'],set(),['https://new.example/contact'])
        self.assertEqual(p['urls'],['https://new.example/contact'])
    def test_frozen_plan_validated(self):
        p=f.build_plan('a'*32,['https://new.example/'],set());self.assertIs(f.validate_plan(p,'a'*32,p['pool_hash']),p)
        p['urls'].append('https://changed.example/')
        with self.assertRaises(ValueError):f.validate_plan(p,'a'*32)
    def test_reject_unsafe_and_social(self):
        for u in ['http://127.0.0.1/','https://t.me/Someone','https://facebook.com/example','https://x.example/a.apk','https://u:p@example.com/']:
            self.assertIsNone(f.candidate(u))
    def test_history_input_strict(self):
        self.assertEqual(f.decode_seen('a'*16+','+'b'*16),{'a'*16,'b'*16})
        for v in ['owner@example.com','a'*17,','*100,'a'*60001]:
            with self.assertRaises(ValueError):f.decode_seen(v)
    def test_search_results_are_urls_only(self):
        html='<a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fnew.example%2Fcontact">Contact @Whatever</a><a href="https://t.me/Other">x</a>'
        self.assertEqual(f.results(html,'unused'),['https://new.example/contact'])
    def test_target_and_plan_segments(self):
        p=f.build_plan('a'*32,['https://n%d.example/'%i for i in range(121)],set())
        a=f.metadata(p,0);b=f.metadata(p,1)
        self.assertTrue(a['has_more']);self.assertFalse(b['has_more']);self.assertEqual(a['target'],30)
    def test_legacy_mode_unmodified(self):
        with patch.dict(os.environ,{'SEED_BATCH':'auto'}),patch.object(f.legacy,'main',return_value=7) as m:
            self.assertEqual(f.main(),7);m.assert_called_once()
    def test_fresh_requires_complete_history(self):
        with patch.dict(os.environ,{'SEED_BATCH':'fresh','GITHUB_EVENT_NAME':'workflow_dispatch','SEARCH_ROUND_ID':'a'*32,'SEARCH_PAGE':'0','SEARCH_POOL_HASH':'','SEARCH_SEEN_HOSTS':''}):
            with self.assertRaisesRegex(ValueError,'HISTORY'):f.main()
    def test_hooks_and_plan_are_restored(self):
        parse,order,select=scan.parse,f.deep.growth.ordered_candidates,f.deep.select
        ns=scan.main.__globals__;copy=ns['_save_operator_copy'];payload={'contacts':[],'summary':{}}
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'sealed').mkdir();(root/'fresh_candidates.json').write_text('[{"url":"https://new.example/contact"}]')
            def fake():
                rows=f.deep.growth.ordered_candidates([{'url':'https://old.example/','kind':'existing','source':'old','basis':'old'}])
                chosen=f.deep.select([r['url'] for r in rows],'search')
                self.assertEqual(chosen,['https://new.example/contact'])
                ns['_save_operator_copy'](payload)
                return 0
            env={'SEED_BATCH':'fresh','GITHUB_EVENT_NAME':'workflow_dispatch','SEARCH_ROUND_ID':'a'*32,'SEARCH_PAGE':'0','SEARCH_POOL_HASH':'','SEARCH_SEEN_HOSTS':f.host_key('old.example')}
            with patch.object(f,'ROOT',root),patch.dict(os.environ,env),patch.object(f,'discover',return_value=([],[])),patch.object(f.messaging,'main',side_effect=fake),patch.dict(ns,{'_save_operator_copy':lambda x:x}):
                self.assertEqual(f.main(),0)
                self.assertEqual(payload['search_round']['strategy'],'fresh')
                self.assertEqual(json.loads((root/'sealed/fresh-plan.json').read_text())['urls'],['https://new.example/contact'])
        self.assertIs(scan.parse,parse);self.assertIs(f.deep.growth.ordered_candidates,order);self.assertIs(f.deep.select,select);self.assertIs(ns['_save_operator_copy'],copy)

class ContextTests(unittest.TestCase):
    def rows(self,html,source='https://publisher.example/contact'):
        return {r['contact']:r for r in c.parse(html,source)[0]}
    def test_heading_contact(self):
        r=self.rows('<h2>Contact owner</h2><ul><li><a href="https://t.me/OwnerOne">Telegram</a></li></ul>')
        self.assertEqual(r['@OwnerOne']['role'],'business')
    def test_no_neighbor_promotion(self):
        r=self.rows('<main><section><h2>Advertising</h2><p><a href="https://t.me/OwnerOne">Contact</a></p></section><section><h2>Friends</h2><p><a href="https://t.me/FriendOne">Friend</a></p></section></main>')
        self.assertNotEqual(r['@FriendOne']['role'],'business')
    def test_no_broad_page_keyword(self):
        r=self.rows('<h1>Advertising options</h1><main><div>'+'x'*500+'</div><a href="https://t.me/FriendOne">Friends</a></main>')
        self.assertNotEqual(r['@FriendOne']['role'],'business')
    def test_split_handle(self):
        self.assertIn('@ContactOne',self.rows('<p>Telegram contact: <strong>@ContactOne</strong></p>'))
    def test_username_subdomain(self):
        r=self.rows('<p>Contact owner <a href="https://ownerone.t.me/">Telegram</a></p>')
        self.assertIn('@ownerone',r)
    def test_tg_scheme(self):
        self.assertIn('@OwnerOne',self.rows('<p>Contact owner <a href="tg://resolve?domain=OwnerOne">Telegram</a></p>'))
    def test_no_private_or_unsupported_links(self):
        self.assertEqual(c.canonical('javascript:alert(1)'),'javascript:alert(1)')
        self.assertEqual(c.canonical('https://user:pass@ownerone.t.me'),'https://user:pass@ownerone.t.me')
    def test_hidden_contacts_ignored(self):
        self.assertNotIn('@HiddenOne',self.rows('<div hidden><p>Telegram contact @HiddenOne</p></div>'))
    def test_bot_not_promoted_to_human(self):
        self.assertEqual(self.rows('<p>Contact <a href="https://t.me/OwnerBot">Telegram</a></p>')['@OwnerBot']['profile_type'],'bot')
    def test_legal_and_seo_not_promoted(self):
        for purpose in ['DMCA complaints','Guest post backlinks']:
            r=self.rows('<p>'+purpose+' <a href="https://t.me/OwnerOne">Contact admin</a></p>')
            self.assertIn(r['@OwnerOne']['role'],{'legal','seo_service'})
    def test_whatsapp_split_explicit(self):
        self.assertIn('+923416681993',self.rows('<p>WhatsApp support: <strong>+92 341 6681993</strong></p>'))

if __name__=='__main__':unittest.main()
