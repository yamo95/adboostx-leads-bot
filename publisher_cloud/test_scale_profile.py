from datetime import datetime
import unittest
from unittest.mock import patch
import scale_profile as s

class CapacityTests(unittest.TestCase):
    def test_scheduled_limit(self):
        self.assertEqual(len(s.select_candidates(list(range(600)), 'auto')), 120)
    def test_acceptance_limit(self):
        self.assertEqual(len(s.select_candidates(list(range(600)), 'all')), 240)
    def test_entire_current_pool(self):
        self.assertEqual(s.select_candidates(list(range(212)), 'all'), list(range(212)))
    def test_empty(self):
        self.assertEqual(s.select_candidates([], 'auto'), [])
    def test_small(self):
        self.assertEqual(len(set(s.select_candidates(list(range(7)), '1'))), 7)
    def test_wrap_has_no_duplicate(self):
        self.assertEqual(len(set(s.select_candidates(list(range(121)), '1'))), 120)
    def test_two_runs_cover_pool(self):
        pool = list(range(212))
        self.assertEqual(len(set(s.select_candidates(pool, '0') + s.select_candidates(pool, '1'))), 212)
    def test_rotation_over_days(self):
        pool = list(range(480))
        seen = set()
        for day in (8,9):
            for hour in (9,18):
                seen.update(s.select_candidates(pool, 'auto', datetime(2026,9,day,hour)))
        self.assertEqual(len(seen),480)
    def test_negative(self):
        with self.assertRaises(ValueError): s.select_candidates([1], '-1')
    def test_invalid(self):
        with self.assertRaises(ValueError): s.select_candidates([1], 'bogus')
    def test_restores_state_on_error(self):
        original = s.q.choose, s.q.BATCH_SIZE, s.q.MAX_RELATED
        with patch.object(s.q, 'main', side_effect=RuntimeError('test')):
            with self.assertRaises(RuntimeError): s.main()
        self.assertEqual((s.q.choose,s.q.BATCH_SIZE,s.q.MAX_RELATED),original)
    def test_keeps_extractor_and_network_rules(self):
        original = s.q.scan.scan_site, s.q.scan.Fetcher, s.q.scan.grade, s.q.CONCURRENT_SITES
        def fake():
            self.assertEqual((s.q.scan.scan_site,s.q.scan.Fetcher,s.q.scan.grade,s.q.CONCURRENT_SITES),original)
            self.assertEqual(s.q.MAX_RELATED,12)
            self.assertIs(s.q.choose,s.select_candidates)
            return 0
        with patch.object(s.q,'main',side_effect=fake): self.assertEqual(s.main(),0)

if __name__ == '__main__': unittest.main()
