import unittest
from unittest.mock import patch
import deep_profile as d

class DeepTests(unittest.TestCase):
    def test_public_only(self):
        for u in ['http://localhost/','https://127.0.0.1/','https://t.me/channel','https://site.example/file.apk','https://u:p@example.com/']:
            self.assertIsNone(d.eligible(u))
    def test_game_sections(self):
        text='# Download Games\n* [A](https://one.example/) - Download\n## News\n* [B](https://two.example/)\n## Game Repacks\n* [C](https://three.example/)\n'
        rows=d.parse_new(text,'deep-games',d.NEW_SOURCES['deep-games'])
        self.assertEqual([r['url'] for r in rows],['https://one.example/','https://three.example/'])
    def test_no_contacts_from_catalog(self):
        text='# Download Games\n* [A](https://one.example/) - Telegram @Person example@a.com\n'
        row=d.parse_new(text,'deep-games',d.NEW_SOURCES['deep-games'])[0]
        self.assertNotIn('@',str(row)); self.assertNotIn('contact',row)
    def test_no_password_or_unsafe(self):
        text='# Download Games\n* [A](https://one.example/) - PW: test\n* [B](https://two.example/) - malware\n'
        self.assertEqual(d.parse_new(text,'deep-games',d.NEW_SOURCES['deep-games']),[])
    def test_apk_explicit_only(self):
        text='## Software\n* [A](https://one.example/) - APK Downloads\n* [B](https://two.example/) - Music\n'
        self.assertEqual(len(d.parse_new(text,'deep-regional-apk',d.NEW_SOURCES['deep-regional-apk'])),1)
    def test_invalid_feed(self):
        with self.assertRaises(ValueError):d.parse_new('','deep-games','https://bad.example/')
    def test_dedupe(self):
        self.assertEqual(len(d.target_rows(['https://one.example/contact','http://www.one.example/'])),1)
    def test_configuration_bound(self):
        with self.assertRaises(ValueError):d.target_rows(['https://one.example']*501)
    def test_deep_selection_only(self):
        self.assertEqual(d.select(['https://one.example','https://two.example'],'deep',deep_urls=['https://two.example']),['https://two.example'])
    def test_deep_limit(self):
        urls=[f'https://x{i}.example/' for i in range(800)]
        self.assertEqual(len(d.select(urls,'deep',deep_urls=urls)),500)
    def test_schedule_unchanged(self):
        urls=[f'https://x{i}.example/' for i in range(800)]
        self.assertEqual(d.select(urls,'1'),d.continuation.BASE_SELECT(urls,'1'))
    def test_missing_candidates_empty(self):
        self.assertEqual(d.select(['https://one.example'],'deep',deep_urls=['https://missing.example']),[])
    def test_duplicates_not_new(self):
        urls=['https://one.example/']*3
        self.assertEqual(len(d.select(urls,'deep',deep_urls=urls)),1)
    def test_targets_are_not_preapproved(self):
        row=d.target_rows(['https://one.example'])[0]
        self.assertNotIn('site_fit',row);self.assertNotIn('role',row)
    def test_no_extract_or_network_replacement(self):
        scan=d.growth.scan
        before=(scan.scan_site,scan.Fetcher,scan.grade)
        with patch.object(d.growth,'main',return_value=0):
            self.assertEqual(d.main(),0)
        self.assertEqual((scan.scan_site,scan.Fetcher,scan.grade),before)
    def test_restored_after_failure(self):
        before=(d.growth.EXTRA_SOURCES,d.growth.parse_extra,d.growth.ordered_candidates,d.growth.select_candidates,d.growth.scan.BUSINESS)
        with patch.object(d.growth,'main',side_effect=RuntimeError()):
            with self.assertRaises(RuntimeError):d.main()
        self.assertEqual((d.growth.EXTRA_SOURCES,d.growth.parse_extra,d.growth.ordered_candidates,d.growth.select_candidates,d.growth.scan.BUSINESS),before)

if __name__=='__main__':unittest.main()
