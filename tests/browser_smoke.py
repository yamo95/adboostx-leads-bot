"""B219 browser checks using synthetic rows only; no private key or outreach.

python tests/browser_smoke.py --docs docs
python tests/browser_smoke.py --docs docs --hosted
Hosted mode also fetches the public encrypted report index and one ciphertext
through the browser. It does NOT decrypt production reports or test a phone.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
import re
import threading
from datetime import datetime, timezone
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit
from playwright.sync_api import sync_playwright, expect

APP = 'https://yamo95.github.io/adboostx-leads-bot/'
KEY_ID = 'b219c932768c4a5e52dda6bec834872f899811fe5142b0cd34f4f113afadf29b'

class Quiet(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


def fixture():
    now = datetime.now(timezone.utc).isoformat()
    row = dict(domain='publisher.example', niche='Synthetic test data', role='contact',
               quality='PUBLISHED_GENERAL_ROUTE', site_fit='PASS', profile_type='unverified',
               source_url='https://publisher.example/contact', via='',
               evidence='Synthetic fixture only', observed_at=now, notes='Not a real lead')
    return dict(summary=dict(run_id='1', created_at=now),
                sites=[dict(domain=row['domain'], state='SCANNED', html_pages_opened=1)],
                contacts=[
                    dict(row, channel='email', contact='fixture@guestpost.cc',
                         contact_url='mailto:fixture@guestpost.cc'),
                    dict(row, channel='email', contact='fixture@domain-evo.com',
                         contact_url='mailto:fixture@domain-evo.com'),
                    dict(row, channel='telegram', contact='@ExampleOwner',
                         contact_url='https://t.me/ExampleOwner', role='business',
                         quality='PUBLISHED_BUSINESS_ROUTE'),
                    dict(row, channel='telegram', contact='@ExampleCommunity',
                         contact_url='https://t.me/ExampleCommunity', profile_type='community')])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--docs', type=Path, default=Path('docs'))
    parser.add_argument('--hosted', action='store_true')
    parser.add_argument('--out', type=Path, default=Path('browser-checks'))
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    server = None
    base = APP
    if not args.hosted:
        server = ThreadingHTTPServer(('127.0.0.1', 0), partial(Quiet, directory=str(args.docs.resolve())))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        base = 'http://127.0.0.1:%s/' % server.server_port
    checks = []
    def check(label, condition):
        if not condition:
            raise AssertionError(label)
        checks.append(label)
    try:
        with sync_playwright() as p:
            launch = {'headless': True}
            if os.getenv('BROWSER_EXECUTABLE'):
                launch['executable_path'] = os.environ['BROWSER_EXECUTABLE']
            browser = p.chromium.launch(**launch)
            for label, width, height, mobile in [('desktop', 1440, 1000, False), ('mobile-emulated', 390, 844, True)]:
                context = browser.new_context(viewport={'width': width, 'height': height},
                                              is_mobile=mobile, has_touch=mobile,
                                              service_workers='block')
                blocked = []
                def gate(route):
                    request = route.request
                    if request.method != 'GET' or urlsplit(request.url).hostname not in {
                            '127.0.0.1', 'yamo95.github.io', 'raw.githubusercontent.com'}:
                        blocked.append((request.method, urlsplit(request.url).hostname))
                        route.abort()
                    else:
                        route.continue_()
                context.route('**/*', gate)
                page = context.new_page()
                errors = []
                page.on('pageerror', lambda error: errors.append(str(error)))
                response = page.goto(base, wait_until='networkidle', timeout=45000)
                check(label + ': page HTTP 200', response.status == 200)
                expect(page.locator('#login')).to_be_visible()
                expect(page.locator('#app')).to_be_hidden()
                check(label + ': WebCrypto available', page.evaluate('!!globalThis.crypto?.subtle'))
                check(label + ': no horizontal overflow on login', page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1'))
                page.locator('#remember').check()
                expect(page.locator('#passwordBox')).to_be_visible()
                page.locator('#remember').uncheck()
                expect(page.locator('#passwordBox')).to_be_hidden()
                for name in ['app.js', 'review.js', 'style.css']:
                    fetched = context.request.get(base + name, timeout=30000)
                    check(label + ': exact ' + name,
                          fetched.ok and hashlib.sha256(fetched.body()).digest() ==
                          hashlib.sha256((args.docs / name).read_bytes()).digest())
                if args.hosted and not mobile:
                    meta = page.evaluate('''async () => {
                      const idx = await jsonFile(INDEX,1000000);
                      if (idx.key_id!==KEY_ID || !Array.isArray(idx.runs) || !idx.runs.length) throw Error('INDEX');
                      if (!idx.runs.every(e=>/^private-b219-results\\/runs\\/\\d+-\\d+\\.json$/.test(e.path))) throw Error('PATH');
                      const e = await jsonFile(idx.runs[0].path);
                      if(e.key_id!==KEY_ID || e.format!=='publisher-leads-rsa-oaep-aesgcm-v1') throw Error('ENVELOPE');
                      if(Object.keys(e).sort().join(',')!=='ciphertext,format,key_id,nonce,wrapped_key') throw Error('PLAINTEXT');
                      return {reports:idx.runs.length,key_id:e.key_id,nonce:buf(e.nonce).length,wrapped:buf(e.wrapped_key).length};
                    }''')
                    check('hosted: encrypted report accessible through browser', meta['nonce'] == 12 and meta['wrapped'] == 384)
                    (args.out / 'hosted-report-metadata.json').write_text(json.dumps(meta, indent=2))
                page.evaluate('''data => {
                  snaps.set('synthetic',data);rebuild();
                  $('login').hidden=true;$('app').hidden=false;$('lock').hidden=false;
                }''', fixture())
                expect(page.locator('#cards > article')).to_have_count(1)
                page.select_option('#channel', 'all')
                page.select_option('#quality', 'all')
                expect(page.locator('#cards > article')).to_have_count(4)
                check(label + ': initial review warnings', page.locator('#cards .warning').count() == 2)
                page.fill('#search', 'fixture')
                page.select_option('#channel', 'email')
                page.select_option('#follow', 'uncontacted')
                page.locator('#fit').check()
                page.locator('#newOnly').check()
                expect(page.locator('#cards > article')).to_have_count(2)
                check(label + ': filter changes retain warnings', page.locator('#cards .warning').count() == 2)
                check(label + ': cards fit viewport', page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1'))
                page.screenshot(path=str(args.out / (label + '-synthetic.png')), full_page=True)
                page.select_option('#quality', 'published')
                expect(page.locator('#cards > article')).to_have_count(0)
                page.fill('#search', '')
                page.select_option('#channel', 'all')
                expect(page.locator('#cards > article')).to_have_count(1)
                page.locator('#cards > article select').select_option('followup')
                page.select_option('#follow', 'followup')
                expect(page.locator('#cards > article')).to_have_count(1)
                check(label + ': follow-up saved locally', page.evaluate("JSON.parse(localStorage.getItem(STORE))['telegram|@exampleowner']==='followup'"))
                page.click('#markSeen')
                expect(page.locator('#cards > article')).to_have_count(0)
                page.locator('#newOnly').uncheck()
                expect(page.locator('#cards > article')).to_have_count(1)
                page.click('#lock')
                expect(page.locator('#login')).to_be_visible()
                check(label + ': lock clears visible data', page.locator('#cards > article').count() == 0)
                check(label + ': no JS exceptions', not errors)
                check(label + ': no outbound writes or contact requests', not blocked)
                context.close()
            browser.close()
        result = dict(mode='hosted-public-with-synthetic-ui' if args.hosted else 'local-synthetic-ui',
                      checks=len(checks), passed=checks, real_private_key_used=False,
                      real_reports_decrypted=False, physical_phone_test=False)
        (args.out / 'summary.json').write_text(json.dumps(result, indent=2))
        print(json.dumps(result, indent=2))
    finally:
        if server:
            server.shutdown()

if __name__ == '__main__':
    main()
