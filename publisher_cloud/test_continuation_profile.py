import unittest
from unittest.mock import patch
from datetime import datetime
import continuation_profile as c

class ContinuationTests(unittest.TestCase):
    def rows(self,n=720):
        return [{'url':f'https://publisher{i}.example.com/', 'kind':'regional',
                 'source':'fixture','basis':'fixture'} for i in range(n)]
    def test_approved_next_page(self):
        pool,selected=c.plan(self.rows())
        self.assertEqual(len(selected),220+len(c.TARGETS))
    def test_adding_targets_does_not_shift_page_boundary(self):
        _,s=c.plan(self.rows())
        self.assertNotIn('https://publisher499.example.com/',s)
        self.assertIn('https://publisher500.example.com/',s)
    def test_old_base_feeds_not_repeated_in_next_mode(self):
        rows=self.rows(500)+[{'url':'https://old.example.com/','kind':'existing'}]
        _,s=c.plan(rows)
        self.assertNotIn('https://old.example.com/',s)
    def test_targets_have_no_contact_values(self):
        p,_=c.plan([])
        self.assertTrue(all('contact' not in r for r in p))
    def test_targets_are_actual_public_websites(self):
        self.assertTrue(all(c.growth.candidate_url(u) for u in c.TARGETS))
    def test_unique_hosts(self):
        _,s=c.plan(self.rows()+self.rows())
        self.assertEqual(len(s),len(set(c.growth.scan.host(u) for u in s)))
    def test_next_hard_limit(self):
        _,s=c.plan(self.rows(1400))
        self.assertEqual(len(s),500)
    def test_next_only_current_pool(self):
        self.assertEqual(c.select(['https://a.example.com/'],'next',next_urls=['https://b.example.com/']),[])
    def test_next_dedupe(self):
        a='https://a.example.com/'
        self.assertEqual(c.select([a],'next',next_urls=[a,a]),[a])
    def test_schedule_unchanged(self):
        pool=[r['url'] for r in self.rows()]
        now=datetime(2026,9,10,9)
        self.assertEqual(c.select(pool,'auto',now),c.BASE_SELECT(pool,'auto',now))
    def test_manual_old_modes_unchanged(self):
        pool=[r['url'] for r in self.rows()]
        for b in ('0','1','2','3','all'):
            self.assertEqual(c.select(pool,b),c.BASE_SELECT(pool,b))
    def test_reject_bad_modes(self):
        with self.assertRaises(ValueError):c.select(['https://a.example.com/'],'invalid')
    def test_restore_on_failure(self):
        import tempfile
        from pathlib import Path
        old=(c.growth.ordered_candidates,c.growth.select_candidates)
        with tempfile.TemporaryDirectory() as d,patch.object(c.growth.scan,'ROOT',Path(d)),patch.object(c.growth,'main',side_effect=RuntimeError('fixture')):
            with self.assertRaises(RuntimeError):c.main()
        self.assertEqual((c.growth.ordered_candidates,c.growth.select_candidates),old)

if __name__=='__main__':unittest.main()
