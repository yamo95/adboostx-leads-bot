import unittest
import discovery_sources as discovery

class CatalogScopeTests(unittest.TestCase):
    def test_off_scope_substring_matches_rejected(self):
        for host in ['1xbetapk.example','1win-apk.example','rummyapk.example','incestflix.example','flixbus.com','napkin.ai','raf.mod.uk','army.mod.uk','guide.gov.uk','lottery-apk.example']:
            with self.subTest(host=host):
                self.assertIsNone(discovery.clean_candidate('https://'+host+'/'))
    def test_publisher_candidates_still_require_independent_scan(self):
        for host in ['apknew.example','newflix.example','gta5-mods.example','cricket-live.example']:
            self.assertEqual(discovery.clean_candidate('https://'+host+'/'),'https://'+host+'/')
    def test_third_party_directory_is_not_publisher_ownership(self):
        for url in ['https://telegram.im/foo','https://appbrain.com/app/foo','https://download.cnet.com/foo','https://techcult.com/best-telegram-channels/']:
            self.assertIsNone(discovery.clean_candidate(url))

if __name__=='__main__': unittest.main()
