import os
import unittest
from unittest.mock import patch
import search_round as subject

RID = 'a' * 32
SEEDS = ['https://publisher%d.example/contact' % i for i in range(275)]

class SearchRoundTests(unittest.TestCase):
    def test_target_is_thirty_messaging(self):
        self.assertEqual(subject.TARGET, 30)
    def test_non_overlapping_pages(self):
        a, ma = subject.page_plan(SEEDS, RID, 0)
        b, mb = subject.page_plan(SEEDS, RID, 1, ma['pool_hash'])
        c, mc = subject.page_plan(SEEDS, RID, 2, ma['pool_hash'])
        self.assertEqual([len(a), len(b), len(c)], [120,120,35])
        self.assertEqual(len(set(a+b+c)),275)
        self.assertTrue(ma['has_more']); self.assertTrue(mb['has_more'])
        self.assertFalse(mc['has_more'])
    def test_deterministic_order(self):
        self.assertEqual(subject.page_plan(SEEDS,RID,0),subject.page_plan(list(reversed(SEEDS)),RID,0))
    def test_drift_is_rejected(self):
        _, meta=subject.page_plan(SEEDS,RID,0)
        with self.assertRaisesRegex(RuntimeError,'POOL_CHANGED'):
            subject.page_plan(SEEDS[:-1],RID,1,meta['pool_hash'])
    def test_hosts_deduplicated(self):
        chosen, meta=subject.page_plan(['https://a.example/','https://a.example/contact'],RID,0)
        self.assertEqual(len(chosen),1)
    def test_no_wrap_at_end(self):
        chosen, meta=subject.page_plan(SEEDS,RID,3)
        self.assertEqual(chosen,[]); self.assertFalse(meta['has_more'])
    def test_invalid_input(self):
        for rid,page in [('x'*32,'0'),(RID,'-1'),(RID,'13'),(RID,'1;echo bad')]:
            with self.assertRaises(ValueError):
                subject.request({'SEARCH_ROUND_ID':rid,'SEARCH_PAGE':page})
    def test_invalid_hash(self):
        with self.assertRaises(ValueError):
            subject.request({'SEARCH_ROUND_ID':RID,'SEARCH_PAGE':'0','SEARCH_POOL_HASH':'bad'})
    def test_excludes_social_seeds(self):
        chosen,_=subject.page_plan(['https://t.me/Example','https://publisher.example/'],RID,0)
        self.assertEqual(chosen,['https://publisher.example/'])
    def test_summary_is_unchanged(self):
        payload={'summary':{'status':'LIVE_SCAN_COMPLETE'},'contacts':[]}
        subject.annotate_payload(payload,{'id':RID,'completion':'PAGE_ONLY'})
        self.assertEqual(payload['summary'],{'status':'LIVE_SCAN_COMPLETE'})
        self.assertEqual(payload['search_round']['completion'],'PAGE_ONLY')
    def test_legacy_modes_use_existing_entrypoint(self):
        with patch.dict(os.environ,{'SEED_BATCH':'auto'}), patch.object(subject.messaging,'main',return_value=17) as run:
            self.assertEqual(subject.main(),17);run.assert_called_once()
    def test_search_requires_dispatch(self):
        with patch.dict(os.environ,{'SEED_BATCH':'search','SEARCH_ROUND_ID':RID,'SEARCH_PAGE':'0','GITHUB_EVENT_NAME':'push'}):
            with self.assertRaises(RuntimeError):subject.main()
    def test_hooks_restored_and_metadata_before_encryption(self):
        old_select=subject.deep.select
        namespace=subject.scan.main.__globals__
        old_copy=namespace['_save_operator_copy']
        payload={'summary':{},'contacts':[]}
        def fake():
            chosen=subject.deep.select(SEEDS,'search')
            self.assertEqual(len(chosen),120)
            namespace['_save_operator_copy'](payload)
            return 0
        with patch.dict(os.environ,{'SEED_BATCH':'search','SEARCH_ROUND_ID':RID,'SEARCH_PAGE':'0','GITHUB_EVENT_NAME':'workflow_dispatch'}), patch.dict(namespace,{'_save_operator_copy':lambda p:dict(p)}),patch.object(subject.messaging,'main',side_effect=fake):
            self.assertEqual(subject.main(),0)
        self.assertEqual(payload['search_round']['id'],RID)
        self.assertIs(subject.deep.select,old_select)
        self.assertIs(namespace['_save_operator_copy'],old_copy)

class HistoryTests(unittest.TestCase):
    def test_history_is_not_pruned_at_sixty(self):
        rows=[{'path':'private-b219-results/runs/%d-1.json'%i,'created_at':'2026-09-09T12:00:00Z'} for i in range(100)]
        result=subject.history_entries({'runs':rows},{'runs':[]},{'created_at':'2026-09-10T12:00:00Z'},100,1)
        self.assertEqual(len(result['runs']),101)
        self.assertEqual(set(result['runs'][0]),{'path','created_at'})
    def test_bootstrap_from_recent_index(self):
        result=subject.history_entries({'runs':[]},{'runs':[{'path':'private-b219-results/runs/1-1.json','summary':{'created_at':'2026-09-09T12:00:00Z'}}]},{'created_at':'2026-09-10T12:00:00Z'},2,1)
        self.assertEqual(len(result['runs']),2)
    def test_history_rejects_unrelated_path(self):
        with self.assertRaises(ValueError):
            subject.history_entries({'runs':[{'path':'https://example.com','created_at':'2026-09-09'}]},{'runs':[]},{'created_at':'2026-09-09'},3,1)

if __name__=='__main__':unittest.main()
