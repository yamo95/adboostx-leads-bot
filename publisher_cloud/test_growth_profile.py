import unittest
from datetime import datetime
from unittest.mock import patch
import growth_profile as g

class GrowthTests(unittest.TestCase):
    def test_schedule_cap(self): self.assertEqual(len(g.select_candidates(list(range(1200)),'auto')),240)
    def test_acceptance_cap(self): self.assertEqual(len(g.select_candidates(list(range(1200)),'all')),500)
    def test_empty(self): self.assertEqual(g.select_candidates([]),[])
    def test_small(self): self.assertEqual(len(set(g.select_candidates(list(range(13)),'1'))),13)
    def test_wrap_unique(self): self.assertEqual(len(set(g.select_candidates(list(range(241)),'1'))),240)
    def test_negative(self):
        with self.assertRaises(ValueError):g.select_candidates([1],'-1')
    def test_rotation(self):
        values=[]
        for d in (8,9):
            for h in (9,18):values+=g.select_candidates(list(range(960)),'auto',datetime(2026,9,d,h))
        self.assertEqual(len(set(values)),960)
    def test_regional_scope(self):
        text='# French\n## Streaming\n* [A](https://a.example.com/) - Movies\n## Reading\n* [B](https://b.example.com/) - Books\n'
        self.assertEqual(len(g.parse_extra(text,'regional','src')),1)
    def test_non_latin_heading(self):
        text='## Streaming / \u0627\u0644\u0628\u062b\n* [A](https://a.example.com/) - Movies\n'
        self.assertEqual(len(g.parse_extra(text,'regional','src')),1)
    def test_radio_not_target(self):self.assertEqual(g.parse_extra('## Streaming\n* [A](https://a.example.com/) - Music Radio','regional','src'),[])
    def test_nested_scope(self):
        text='## Streaming\n### Movies\n* [A](https://a.example.com/) - Movies\n## Reading\n* [B](https://b.example.com/) - TV book'
        self.assertEqual(len(g.parse_extra(text,'regional','src')),1)
    def test_primary_only(self):
        rows=g.parse_extra('## Video File Hosts\n* [A](https://a.example.com/) / [Telegram](https://t.me/AAdmin)','video-hosts','src')
        self.assertEqual(len(rows),1);self.assertNotIn('AAdmin',str(rows));self.assertTrue(rows[0]['chat_hint'])
    def test_no_contact_import(self):
        row=g.parse_extra('## File Hosts\n* [A](https://a.example.com/) - @HiThere +15559999999','storage','src')[0]
        self.assertNotIn('contact',row);self.assertNotIn('HiThere',str(row));self.assertNotIn('555',str(row))
    def test_unsafe(self):
        for u in ['https://127.0.0.1/','https://10.0.0.1/','https://user:pass@a.example.com','https://a.example.com/a.apk','https://t.me/hello','https://discord.gg/hello']:
            self.assertIsNone(g.candidate_url(u))
    def test_host_dedupe(self):self.assertEqual(len(g.ordered_candidates([{'url':'https://a.example.com/a'},{'url':'http://www.a.example.com/b'}])),1)
    def test_prioritize_new(self):
        rows=g.ordered_candidates([{'url':'https://a.example.com','kind':'existing'},{'url':'https://b.example.com','kind':'regional'},{'url':'https://c.example.com','kind':'targeted'}])
        self.assertEqual([r['kind'] for r in rows],['targeted','regional','existing'])
    def test_pool_limit(self):self.assertEqual(len(g.ordered_candidates([{'url':f'https://a{i}.example.com'} for i in range(1700)])),1500)
    def test_no_unsafe_entries(self):
        for word in ['Requires Sign-Up','Casino','Password: hi','malware']:
            self.assertEqual(g.parse_extra('## Streaming\n* [A](https://a.example.com/) - Movies '+word,'regional','src'),[])
    def test_mod_guides_not_publishers(self):self.assertEqual(g.parse_extra('## Game Mods\n* [A](https://a.example.com/) - Game Modding Guides','mods','src'),[])
    def test_does_not_promote_fit(self):
        row=g.parse_extra('## Anime Streaming\n* [A](https://a.example.com/)','more-streaming','src')[0]
        self.assertNotIn('site_fit',row)
    def test_preserve_skips_schedule(self):
        with patch.dict('os.environ',{'GITHUB_EVENT_NAME':'schedule'}),patch.object(g,'get_public',side_effect=AssertionError('No request')):
            self.assertEqual(g.preserve_baseline()['baseline_saved'],0)
    def test_reject_baseline_path(self):
        import json
        raw=json.dumps({'key_id':g.KEY_ID,'runs':[{'path':'https://evil.example.com/'}]}).encode()
        with patch.dict('os.environ',{'GITHUB_EVENT_NAME':'push'}),patch.object(g,'get_public',return_value=raw) as mock:
            self.assertEqual(g.preserve_baseline()['baseline_errors'],1);self.assertEqual(mock.call_count,1)
    def test_section_boundary(self):
        text='# File Hosts\n* [A](https://a.example.com/)\n# File Search\n* [B](https://b.example.com/)'
        self.assertEqual(len(g.parse_extra(text,'storage','src')),1)

if __name__=='__main__':unittest.main()
