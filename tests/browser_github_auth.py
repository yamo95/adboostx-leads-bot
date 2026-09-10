"""Existing B219 auth UI regression. Synthetic ephemeral key/token; no live API writes.

Only the pinned public key and matching KEY_ID are substituted in served scripts.
All remaining application bytes are used unchanged. No real credentials are read.
"""
from __future__ import annotations
import argparse
import base64
import hashlib
import json
import os
import re
import subprocess
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from playwright.sync_api import sync_playwright, expect

TOKEN = 'TOKEN_TEST_ONLY_NOT_A_REAL_GITHUB_TOKEN'
SLOT = 'admaven-b219-mobile-v1-github-vault-v1'
PASSWORD = 'synthetic-test-passphrase-2026'

class Quiet(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--docs', type=Path, default=Path('docs'))
    parser.add_argument('--out', type=Path, default=Path('browser-auth-checks'))
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    # Node is also used by the application's dependency-free regression tests.
    result = subprocess.run(['node', '-e', "const c=require('node:crypto');const k=c.generateKeyPairSync('rsa',{modulusLength:3072,publicKeyEncoding:{type:'spki',format:'der'},privateKeyEncoding:{type:'pkcs8',format:'pem'}});process.stdout.write(JSON.stringify({public:k.publicKey.toString('base64'),private:k.privateKey}));"], capture_output=True, text=True, check=True)
    fixture = json.loads(result.stdout)
    key_id = hashlib.sha256(base64.b64decode(fixture['public'])).hexdigest()
    server = ThreadingHTTPServer(('127.0.0.1',0), partial(Quiet, directory=str(args.docs.resolve())))
    threading.Thread(target=server.serve_forever,daemon=True).start()
    base = 'http://127.0.0.1:%d/' % server.server_port
    checks = []
    def check(name, condition):
        assert condition, name
        checks.append(name)
    try:
        with sync_playwright() as pw:
            launch = {'headless':True}
            if os.getenv('BROWSER_EXECUTABLE'):
                launch['executable_path'] = os.environ['BROWSER_EXECUTABLE']
            browser = pw.chromium.launch(**launch)
            for label, width, height, mobile in [('desktop',1440,1000,False),('mobile-emulated',390,844,True)]:
                context = browser.new_context(viewport={'width':width,'height':height},is_mobile=mobile,has_touch=mobile,service_workers='block')
                requests, errors = [], []
                def route(request_route):
                    request = request_route.request
                    if request.url.startswith(base):
                        name = request.url.split('/')[-1]
                        if name in {'app.js','github-auth.js'}:
                            code = (args.docs/name).read_text()
                            code = re.sub(r"const KEY_ID='[^']+'", 'const KEY_ID='+json.dumps(key_id), code)
                            code = re.sub(r"const PUBLIC_SPKI = '[^']+'", 'const PUBLIC_SPKI = '+json.dumps(fixture['public']), code)
                            request_route.fulfill(status=200,content_type='application/javascript',body=code)
                        else:
                            request_route.continue_()
                    elif request.url.startswith('https://raw.githubusercontent.com/'):
                        request_route.fulfill(status=200,content_type='application/json',body=json.dumps({'format':1,'key_id':key_id,'runs':[]}),headers={'Access-Control-Allow-Origin':'*'})
                    elif request.url.startswith('https://api.github.com/repos/yamo95/adboostx-leads-bot/actions/workflows/operator-acceptance-b219.yml') and request.method == 'GET':
                        requests.append(request.method)
                        request_route.fulfill(status=200,content_type='application/json',body='{"state":"active"}',headers={'Access-Control-Allow-Origin':'*'})
                    else:
                        errors.append('Unexpected network request: '+request.method)
                        request_route.abort()
                context.route('**/*',route)
                page = context.new_page()
                page.on('pageerror',lambda e:errors.append(str(e)))
                page.goto(base,wait_until='networkidle')
                page.locator('#remember').check()
                page.fill('#password',PASSWORD)
                page.set_input_files('#access',{'name':'synthetic-access.pem','mimeType':'text/plain','buffer':fixture['private'].encode()})
                expect(page.locator('#app')).to_be_visible()
                page.locator('#searchAuth').evaluate('(e)=>e.open=true')
                expect(page.locator('#searchRemember')).to_be_checked()
                page.fill('#searchToken',TOKEN)
                page.click('#searchConnect')
                page.wait_for_function('(slot)=>localStorage.getItem(slot)!==null',arg=SLOT)
                check(label+': encrypted token saved',page.evaluate('(token)=>!JSON.stringify(localStorage).includes(token)',TOKEN))
                check(label+': token input cleared',page.input_value('#searchToken')=='')
                check(label+': validation GET only',requests==['GET'])
                page.reload(wait_until='networkidle')
                check(label+': reload starts locked',page.evaluate("privateKey===null && searchToken===''") )
                page.fill('#savedPassword',PASSWORD)
                page.click('#unlock')
                page.wait_for_function('(token)=>searchToken===token',arg=TOKEN)
                check(label+': automatic restore after saved-password unlock',page.input_value('#searchToken')=='')
                check(label+': restore did not send authorization requests or start a scan',requests==['GET'] and page.evaluate('!searchRunning'))
                page.locator('#searchAuth').evaluate('(e)=>e.open=true')
                check(label+': no horizontal overflow',page.evaluate('document.documentElement.scrollWidth <= innerWidth+1'))
                page.screenshot(path=str(args.out/(label+'-encrypted-auth.png')),full_page=True)
                page.click('#lock')
                check(label+': lock clears live token, retains ciphertext',page.evaluate('(slot)=>!searchToken && !!localStorage.getItem(slot)',SLOT))
                page.fill('#savedPassword',PASSWORD);page.click('#unlock')
                page.wait_for_function('(token)=>searchToken===token',arg=TOKEN)
                page.locator('#searchAuth').evaluate('(e)=>e.open=true')
                page.once('dialog',lambda dialog:dialog.accept())
                page.click('#searchForgetToken')
                check(label+': token forgotten, saved report access retained',page.evaluate('(slot)=>!searchToken && !localStorage.getItem(slot) && !!localStorage.getItem(VAULT)',SLOT))
                page.reload(wait_until='networkidle');page.fill('#savedPassword',PASSWORD);page.click('#unlock')
                expect(page.locator('#app')).to_be_visible()
                check(label+': deleted token stays deleted',page.evaluate("searchToken===''") )
                check(label+': no script errors or forbidden network activity',not errors)
                context.close()
            browser.close()
        summary={'checks':len(checks),'passed':checks,'mode':'local-browser-real-WebCrypto-synthetic-key-and-token','physical_phone_test':False,'real_github_token_used':False,'live_dispatch':False}
        (args.out/'summary.json').write_text(json.dumps(summary,indent=2))
        print(json.dumps(summary,indent=2))
    finally:
        server.shutdown()

if __name__=='__main__':
    main()
