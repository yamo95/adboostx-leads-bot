import base64
import json
import unittest
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from scan import safe_url, same_site, phone, route, parse, role, grade, category, unique, seal, csv_content, selected_seeds, AAD

SOURCE='https://publisher.example/contact'

class ContactTests(unittest.TestCase):
    def test_public_url(self):
        self.assertEqual(safe_url('https://publisher.example/contact#top'),'https://publisher.example/contact')
    def test_unsafe_urls(self):
        for url in ['http://127.0.0.1/','http://localhost/','http://169.254.169.254/','http://10.0.0.1/','file:///etc/passwd','https://name:password@publisher.example/','https://publisher.example:8080/','https://publisher.example/app.apk']:
            with self.subTest(url=url), self.assertRaises(ValueError): safe_url(url)
    def test_site_boundary(self):
        self.assertTrue(same_site('https://www.publisher.example/contact','https://publisher.example'))
        self.assertFalse(same_site('https://publisher.example.attacker.test','https://publisher.example'))
    def test_phone_format(self):
        self.assertEqual(phone('+44 7380 143621'),'+447380143621')
        for value in ['1234567890','1111111111','0123456789','+44ABC123456']: self.assertIsNone(phone(value))
    def test_telegram_business(self):
        item=route('https://t.me/PublicBusinessDemo','Advertising contact',SOURCE)
        self.assertEqual(item['contact'],'@PublicBusinessDemo')
        self.assertEqual(grade(item),'PUBLISHED_BUSINESS_ROUTE')
    def test_telegram_bot(self):
        item=route('https://t.me/PublicBusinessDemoBot','Advertising contact',SOURCE)
        self.assertEqual(grade(item),'BOT')
    def test_telegram_invite(self):
        self.assertEqual(grade(route('https://t.me/+ExampleInvite','Join our community',SOURCE)),'COMMUNITY')
    def test_no_share_routes(self):
        self.assertIsNone(route('https://t.me/share/url?url=https://publisher.example','Share',SOURCE))
    def test_whatsapp_links(self):
        for url in ['https://wa.me/447380143621','https://api.whatsapp.com/send?phone=447380143621','whatsapp://send?phone=447380143621']:
            with self.subTest(url=url): self.assertEqual(route(url,'WhatsApp support',SOURCE)['contact'],'+447380143621')
    def test_short_link_unresolved(self):
        item=route('https://wa.link/abcdef','WhatsApp support',SOURCE)
        self.assertEqual(item['contact'],'https://wa.link/abcdef')
        self.assertEqual(grade(item),'REVIEW_SHORT_LINK')
    def test_purpose_exclusions(self):
        self.assertEqual(role('DMCA copyright complaint','https://publisher.example'),'legal')
        self.assertEqual(role('Guest post and backlink offers',SOURCE),'seo_service')
    def test_hidden_and_forms_ignored(self):
        items,_,_=parse('<form><p>WhatsApp +447380143621</p></form><template><a href="https://t.me/HiddenDemo">Contact</a></template><p hidden>Telegram @HiddenDemo</p>',SOURCE)
        self.assertEqual(items,[])
    def test_no_phone_guess(self):
        items,_,_=parse('<p>Phone +447380143621</p>',SOURCE)
        self.assertEqual(items,[])
    def test_labelled_whatsapp(self):
        items,_,_=parse('<p>WhatsApp: +44 7380 143621</p>',SOURCE)
        self.assertEqual(items[0]['contact'],'+447380143621')
    def test_legal_mail_not_business(self):
        items,_,_=parse('<p>DMCA complaints: <a href="mailto:abuse@publisher.example">abuse@publisher.example</a></p>',SOURCE)
        self.assertTrue(all(grade(x)=='EXCLUDE_PURPOSE' for x in items))
    def test_case_deduplication(self):
        a=route('https://t.me/PublicBusinessDemo','Contact',SOURCE)
        b=route('https://t.me/publicbusinessdemo','Advertising contact',SOURCE)
        self.assertEqual(len(unique([a,b])),1)
        self.assertEqual(unique([a,b])[0]['role'],'business')
    def test_single_apk(self):
        self.assertEqual(category('Honista APK download latest version',[]),('APK / app downloads','PASS'))
    def test_sports(self):
        self.assertEqual(category('Football live stream watch live match',[]),('Sports streaming','PASS'))
    def test_no_irrelevant_rejection(self):
        self.assertEqual(category('Temporary unavailable',[])[1],'REVIEW')
    def test_csv_injection(self):
        data=csv_content([{'v':'=HYPERLINK("x")'},{'v':'+447380143621'}],['v'])
        self.assertIn("'=HYPERLINK",data)
        self.assertIn("'+447380143621",data)
    def test_rotating_batches(self):
        seeds=['https://publisher'+str(i)+'.example/' for i in range(24)]
        self.assertFalse(set(selected_seeds(seeds,'0')) & set(selected_seeds(seeds,'1')))
        self.assertEqual(len(selected_seeds(seeds,'all')),24)
        with self.assertRaises(ValueError): selected_seeds(seeds,'9')

class EncryptionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.private=rsa.generate_private_key(public_exponent=65537,key_size=3072)
        cls.public=cls.private.public_key().public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo)
    def decrypt(self,envelope):
        key=self.private.decrypt(base64.b64decode(envelope['wrapped_key']),padding.OAEP(mgf=padding.MGF1(hashes.SHA256()),algorithm=hashes.SHA256(),label=None))
        return json.loads(AESGCM(key).decrypt(base64.b64decode(envelope['nonce']),base64.b64decode(envelope['ciphertext']),AAD))
    def test_roundtrip_and_no_plaintext(self):
        payload={'contacts':[{'contact':'@PrivateExample','evidence':'business demo'}]}
        result=seal(payload,self.public)
        self.assertEqual(self.decrypt(result),payload)
        self.assertNotIn('PrivateExample',json.dumps(result))
    def test_randomized_encryption(self):
        a,b=seal({'a':1},self.public),seal({'a':1},self.public)
        self.assertNotEqual(a['nonce'],b['nonce'])
        self.assertNotEqual(a['ciphertext'],b['ciphertext'])
    def test_tamper_detection(self):
        data=seal({'a':1},self.public)
        ciphertext=bytearray(base64.b64decode(data['ciphertext']));ciphertext[0]^=1
        data['ciphertext']=base64.b64encode(ciphertext).decode()
        with self.assertRaises(InvalidTag): self.decrypt(data)
    def test_reject_private_key_as_recipient(self):
        private=self.private.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption())
        with self.assertRaises(ValueError): seal({},private)

if __name__=='__main__': unittest.main()
