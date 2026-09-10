import base64,json,unittest
from datetime import datetime,timezone,timedelta
from unittest.mock import patch
import catalog_candidates as c
class CatalogTests(unittest.TestCase):
 def test_only_scoped_public_domains(self):
  for h in ['apknew.example','newflix.example','sport-stream.example','game-repack.example']:
   self.assertEqual(c.selected_domain(h),'https://'+h+'/')
  for h in ['127.0.0.1','u:p@apk.example','apk.example/x','google.com','netflix.com','iptv-flix.example','apk-casino.example']:
   self.assertIsNone(c.selected_domain(h),h)
 def test_stream_split_and_attribution(self):
  r=c.CandidateReader();r.feed(b'GlobalRank,Domain\n1,example.com\n2,ap');r.feed(b'knew.example\n3,apknew.example')
  self.assertEqual(r.finish(),['https://apknew.example/'])
  self.assertIn('CC BY 3.0',c.ATTRIBUTION)
 def test_html_rejected_as_csv(self):
  with self.assertRaisesRegex(ValueError,'HEADER'):r=c.CandidateReader();r.feed(b'<html>blocked</html>\n')
 def test_oversized_response_and_line(self):
  with patch.object(c,'MAX_BYTES',2):
   with self.assertRaisesRegex(ValueError,'SIZE'):c.CandidateReader().feed(b'abcd')
  with self.assertRaisesRegex(ValueError,'LINE_SIZE'):c.CandidateReader().feed(b'a'*4097)
 def test_twenty_four_hours_not_calendar_day(self):
  at=datetime(2026,9,11,tzinfo=timezone.utc); cache={'last_attempt_at':(at-timedelta(hours=23)).isoformat()}
  self.assertTrue(c.recent_attempt(cache,at));self.assertFalse(c.recent_attempt(cache,at+timedelta(hours=2)))
 def test_reservation_blocks_retry_after_failed_download(self):
  self.assertTrue(c.recent_attempt({'last_attempt_at':c.now().isoformat(),'state':'reserved'}))
 def test_cache_accepts_only_expected_source_and_urls(self):
  obj={'format':1,'source':c.SOURCE,'urls':['https://apknew.example/']}
  enc=lambda o:{'content':base64.b64encode(json.dumps(o).encode()).decode()}
  self.assertEqual(c.decode_record(enc(obj)),obj)
  obj['urls']=['http://127.0.0.1/']
  with self.assertRaisesRegex(ValueError,'CACHE_URL'):c.decode_record(enc(obj))
 def test_cap_prevents_unbounded_candidates(self):
  with patch.object(c,'MAX_CANDIDATES',1):
   r=c.CandidateReader();r.feed(b'GlobalRank,Domain\n1,apkone.example\n2,apktwo.example\n')
   self.assertEqual(len(r.finish()),1)
if __name__=='__main__':unittest.main()
