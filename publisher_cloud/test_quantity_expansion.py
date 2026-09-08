import asyncio
from datetime import datetime
import unittest
from unittest.mock import patch
import quantity_expansion as q

class ExpansionTests(unittest.TestCase):
    def test_batch_cap(self):
        self.assertEqual(len(q.choose(list(range(700)), 'all')), 60)
    def test_small_pool(self):
        self.assertEqual(q.choose([1,2,3], 'all'), [1,2,3])
    def test_empty_pool(self):
        self.assertEqual(q.choose([], 'all'), [])
    def test_sequential_batches(self):
        pool=list(range(200));a=q.choose(pool,'0');b=q.choose(pool,'1')
        self.assertFalse(set(a)&set(b))
    def test_day_rotation(self):
        pool=list(range(240))
        runs=[q.choose(pool,'auto',datetime(2026,9,d,h)) for d in (8,9) for h in (9,18)]
        self.assertEqual(len(set(sum(runs,[]))),240)
    def test_no_duplicate_on_wrap(self):
        self.assertEqual(len(set(q.choose(list(range(61)),'1'))),60)
    def test_negative_batch(self):
        with self.assertRaises(ValueError):q.choose([1],'-1')
    def test_only_primary_url_and_approved_sections(self):
        text='# Android APKs\n## Modded APKs\n* [Good](https://a.example.com/) / [Telegram](https://t.me/other)\n## Telegram Channels\n* [Other](https://b.example.com/)\n'
        rows=q.parse_catalog(text,'apk','https://catalog.example.com')
        self.assertEqual([r['url'] for r in rows],['https://a.example.com/'])
    def test_no_social_or_binary_or_private(self):
        for u in ('https://t.me/bot','https://discord.gg/name','https://127.0.0.1/','https://a.example.com/a.apk'):
            self.assertIsNone(q.eligible_url(u))
    def test_no_signup_candidates(self):
        text='## Modded APKs\n* [A](https://a.example.com/) - Requires Sign-Up\n* [B](https://b.example.com/) - PW: xx\n'
        self.assertEqual(q.parse_catalog(text,'apk','source'),[])
    def test_no_contact_values_imported(self):
        text='## Stream Aggregators\n* [A](https://a.example.com/) - Telegram @Owner\n'
        row=q.parse_catalog(text,'streaming','source')[0]
        self.assertNotIn('contact',row)
        self.assertNotIn('@Owner',str(row))
    def test_host_dedupe(self):
        rows=q.unique_candidates([{'url':'https://a.example.com/a'},{'url':'http://www.a.example.com/b'}])
        self.assertEqual(len(rows),1)
    def test_pool_cap(self):
        rows=q.unique_candidates([{'url':f'https://s{i}.example.com/'} for i in range(800)])
        self.assertEqual(len(rows),600)
    def test_balance(self):
        result=q.balanced([{'kind':'a','url':'1'},{'kind':'a','url':'2'},{'kind':'b','url':'3'}])
        self.assertEqual([r['url'] for r in result],['1','3','2'])
    def test_source_allowlist(self):
        with self.assertRaises(ValueError):q.read_catalog('https://evil.example.com/')
    def test_related_limit_and_failure_review(self):
        class Fetcher:
            pages=[]
            async def __aenter__(self):return self
            async def __aexit__(self,*a):pass
        async def site(url,fetcher):
            if 'fail' in url:raise TimeoutError()
            return ({'domain':q.scan.host(url)},[],[f'https://extra{i}.example.com/' for i in range(20)])
        with patch.object(q.scan,'Fetcher',Fetcher),patch.object(q.scan,'scan_site',site):
            sites,contacts,pages=asyncio.run(q.expanded_run(['https://a.example.com/','https://fail.example.com/']))
        self.assertEqual(len(sites),8)
        self.assertEqual(sites[1]['site_fit'],'REVIEW')
    def test_sports_candidate_hint_not_pass(self):
        row=q.parse_catalog('## Sports Streaming\n* [A](https://a.example.com/)','streaming','src')[0]
        self.assertEqual(row['kind'],'sports')
        self.assertNotIn('site_fit',row)

if __name__=='__main__':unittest.main()
