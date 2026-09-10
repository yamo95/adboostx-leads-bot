'use strict';
// Synthetic keys and tokens ONLY. Execute: node tests/test_github_auth.cjs
const assert = require('node:assert/strict');
const fs = require('node:fs'), path = require('node:path'), vm = require('node:vm');
const { webcrypto, createHash } = require('node:crypto');
const docs = process.env.APP_DIR || path.join(__dirname, '..', 'docs');
const source = name => fs.readFileSync(path.join(docs, name), 'utf8');
const TOKEN = 'TOKEN_TEST_ONLY_NOT_A_REAL_GITHUB_TOKEN';
const SLOT = 'admaven-b219-mobile-v1-github-vault-v1';
const api = 'https://api.github.com/repos/yamo95/adboostx-leads-bot';
let checks = 0;
const check = async (label, callback) => { await callback(); checks++; console.log('PASS ' + label); };
let keys, spki, keyId;
function harness(storage = new Map()) {
  const nodes = {}, requests = [], events = {};
  class Element {
    constructor() { this.children = []; this.value = ''; this.checked = false; this.hidden = false; this.disabled = false; this.listeners = {}; this._text = ''; this.classList = {toggle(){}}; }
    set id(value) { this._id = value; nodes[value] = this; } get id() { return this._id; }
    set textContent(value) { this._text = String(value ?? ''); this.children = []; }
    get textContent() { return this._text + this.children.map(c => c.textContent).join(''); }
    append(...items) { for (const item of items) { item.parentNode = this; this.children.push(item); } }
    replaceChildren(...items) { this._text = ''; this.children = []; this.append(...items); }
    insertBefore(item, before) { const i = this.children.indexOf(before); item.parentNode = this; this.children.splice(i < 0 ? this.children.length : i, 0, item); }
    querySelector(selector) { return selector === 'p.small' ? this.children.find(c => c.className === 'small') : null; }
    setAttribute() {} focus() {} scrollIntoView() {}
    addEventListener(e, fn) { (this.listeners[e] ||= []).push(fn); }
    removeEventListener(e, fn) { this.listeners[e] = (this.listeners[e] || []).filter(x => x !== fn); }
  }
  const html = source('index.html');
  for (const match of html.matchAll(/\bid="([^"]+)"/g)) { const node = new Element(); node.id = match[1]; }
  for (const m of html.matchAll(/<select[^>]*id="([^"]+)"[^>]*>[\s\S]*?<option value="([^"]+)"/g)) nodes[m[1]].value = m[2];
  const root = new Element(); for (const node of Object.values(nodes)) root.append(node);
  const intro = new Element(); intro.className = 'small'; const actions = new Element();
  nodes.searchAuth.replaceChildren(intro, actions); actions.append(nodes.searchConnect, nodes.searchDisconnect);
  const main = new Element(); main.append(nodes.searchStart, nodes.searchStatus);
  const h = {nodes, storage, requests, events, confirm: true, denyWrite: false, denyDelete: false,
    handler: async url => url.startsWith(api) ? new Response('{"state":"active"}', {status:200}) : new Response('{}', {status:404})};
  const context = vm.createContext({ URL, Blob, Response, TextEncoder, TextDecoder, Uint8Array, atob, btoa, Date,
    AbortController, crypto:webcrypto, setTimeout(){return 1;}, clearTimeout(){}, navigator:{},
    confirm:() => h.confirm, addEventListener:(type, fn) => { events[type] = fn; },
    fetch:async (url, options = {}) => { requests.push({url, options}); return h.handler(url, options); },
    document:{getElementById:id=>nodes[id],createElement:()=>new Element(),addEventListener(){}},
    localStorage:{getItem:k=>storage.get(k)??null,setItem:(k,v)=>{if(h.denyWrite)throw Error('QUOTA');storage.set(k,v);},removeItem:k=>{if(h.denyDelete)throw Error('DENIED');storage.delete(k);}},
    TEST_KEY:keys.privateKey
  });
  for (const [,filename] of html.matchAll(/<script src="([^"]+)"/g)) {
    let text = source(filename);
    if (filename === 'app.js') text = text.replace(/const KEY_ID='[^']+'/,'const KEY_ID='+JSON.stringify(keyId));
    if (filename === 'github-auth.js') text = text.replace(/const PUBLIC_SPKI = '[^']+'/,'const PUBLIC_SPKI = '+JSON.stringify(spki));
    vm.runInContext(text, context, {filename});
  }
  h.run = code => vm.runInContext(code, context);
  h.unlock = () => h.run('enter(TEST_KEY)');
  h.connect = async (token = TOKEN) => {nodes.searchToken.value = token; await nodes.searchConnect.onclick();};
  return h;
}
async function main() {
  keys = await webcrypto.subtle.generateKey({name:'RSA-OAEP',modulusLength:3072,publicExponent:new Uint8Array([1,0,1]),hash:'SHA-256'},true,['encrypt','decrypt']);
  const pub = Buffer.from(await webcrypto.subtle.exportKey('spki',keys.publicKey));
  const pkcs8 = await webcrypto.subtle.exportKey('pkcs8', keys.privateKey);
  keys.privateKey = await webcrypto.subtle.importKey('pkcs8', pkcs8, {name:'RSA-OAEP',hash:'SHA-256'}, false, ['decrypt']);
  spki = pub.toString('base64'); keyId = createHash('sha256').update(pub).digest('hex');
  await check('production public key matches the existing report key ID',()=>{
    const actual=source('github-auth.js').match(/const PUBLIC_SPKI = '([^']+)'/)[1];
    assert.equal(createHash('sha256').update(Buffer.from(actual,'base64')).digest('hex'),source('app.js').match(/const KEY_ID='([^']+)'/)[1]);
  });
  let h = harness();
  await check('locked page cannot accept or persist authorization',async()=>{await h.connect();assert.equal(h.requests.length,0);assert.equal(h.storage.has(SLOT),false);});
  await h.unlock();
  await check('default remember option is visible and enabled after unlock',()=>assert.equal(h.nodes.searchRemember.checked,true));
  await check('connect stores ciphertext only',async()=>{await h.connect();assert.ok(h.storage.has(SLOT));assert.equal(h.run('searchToken'),TOKEN);assert.ok(![...h.storage.values()].join('').includes(TOKEN));assert.equal(h.nodes.searchToken.value,'');});
  const saved = h.storage.get(SLOT);
  await check('save uses only read-only validation, no scan or credential upload',()=>{
    const req=h.requests.filter(x=>x.url.startsWith(api));assert.equal(req.length,1);assert.equal(req[0].options.method,'GET');assert.equal(req[0].options.body,undefined);assert.equal(req[0].options.headers.Authorization,'Bearer '+TOKEN);
  });
  await check('locking clears only session authorization, preserving ciphertext',()=>{h.run('lock()');assert.equal(h.run('searchToken'),'');assert.equal(h.storage.get(SLOT),saved);});
  await check('existing enter path restores token without paste or GitHub request',async()=>{const n=h.requests.filter(x=>x.url.startsWith(api)).length;await h.unlock();assert.equal(h.run('searchToken'),TOKEN);assert.equal(h.requests.filter(x=>x.url.startsWith(api)).length,n);});
  await check('full page restart restores authorization after normal unlock',async()=>{h=harness(h.storage);assert.equal(h.run('searchToken'),'');await h.unlock();assert.equal(h.run('searchToken'),TOKEN);assert.equal(h.run('searchRunning'),false);});
  await check('disconnect preserves saved copy but clears memory',()=>{h.nodes.searchDisconnect.onclick();assert.equal(h.run('searchToken'),'');assert.equal(h.storage.get(SLOT),saved);});
  await h.unlock();
  await check('cancelled deletion leaves authorization intact',()=>{h.confirm=false;h.nodes.searchForgetToken.onclick();assert.equal(h.run('searchToken'),TOKEN);assert.equal(h.storage.get(SLOT),saved);h.confirm=true;});
  await check('forget token preserves report vault and lead-tracking data',()=>{
    h.storage.set('admaven-b219-mobile-v1-vault','{"fixture":"encrypted-access"}');h.storage.set('admaven-b219-mobile-v1','{"fixture":"followup"}');
    h.nodes.searchForgetToken.onclick();assert.equal(h.run('searchToken'),'');assert.ok(!h.storage.has(SLOT));assert.ok(h.storage.has('admaven-b219-mobile-v1-vault'));assert.ok(h.storage.has('admaven-b219-mobile-v1'));
  });
  await check('deleted token cannot return after restart',async()=>{h=harness(h.storage);await h.unlock();assert.equal(h.run('searchToken'),'');});
  await h.connect();
  await check('unchecking remember removes ciphertext but retains session use',async()=>{h.nodes.searchRemember.checked=false;await h.nodes.searchRemember.onchange();assert.equal(h.run('searchToken'),TOKEN);assert.ok(!h.storage.has(SLOT));});
  await check('checking remember saves current session without re-paste',async()=>{h.nodes.searchRemember.checked=true;await h.nodes.searchRemember.onchange();assert.ok(h.storage.has(SLOT));assert.ok(!h.storage.get(SLOT).includes(TOKEN));});
  await check('RSA encryption is randomized',()=>assert.notEqual(h.storage.get(SLOT),saved));
  await check('offline and 403/429 do not erase the saved token',async()=>{
    const before=h.storage.get(SLOT);for(const status of [403,429,500]){h.handler=async()=>new Response('{}',{status});await assert.rejects(h.run("githubSearch('/actions/workflows/'+SEARCH_WORKFLOW)"));assert.equal(h.storage.get(SLOT),before);}
    h.handler=async()=>{throw Error('NETWORK');};await assert.rejects(h.run("githubSearch('/actions/workflows/'+SEARCH_WORKFLOW)"));assert.equal(h.storage.get(SLOT),before);
  });
  await check('401 clears rejected credential and requests reauthorization',async()=>{h.handler=async()=>new Response('{}',{status:401});await assert.rejects(h.run("githubSearch('/actions/workflows/'+SEARCH_WORKFLOW)"));assert.equal(h.run('searchToken'),'');assert.ok(!h.storage.has(SLOT));assert.ok(h.nodes.githubVaultStatus.textContent.includes('401'));});
  await check('tampered ciphertext fails closed without preventing report unlock',async()=>{
    const value=JSON.parse(saved);value.ciphertext=(value.ciphertext[0]==='A'?'B':'A')+value.ciphertext.slice(1);
    const x=harness(new Map([[SLOT,JSON.stringify(value)]]));await x.unlock();assert.equal(x.run('searchToken'),'');assert.ok(x.run('privateKey'));assert.ok(x.nodes.githubVaultStatus.textContent.length>20);
  });
  await check('wrong scope or key identity cannot unlock a vault',async()=>{
    for(const patch of [{scope:'wrong-repository'},{key_id:'0'.repeat(64)},{ciphertext:'x'.repeat(5000)}]){const x=harness(new Map([[SLOT,JSON.stringify({...JSON.parse(saved),...patch})]]));await x.unlock();assert.equal(x.run('searchToken'),'');}
  });
  await check('different private key cannot decrypt the saved token',async()=>{
    const wrong=await webcrypto.subtle.generateKey({name:'RSA-OAEP',modulusLength:2048,publicExponent:new Uint8Array([1,0,1]),hash:'SHA-256'},false,['encrypt','decrypt']);
    await assert.rejects(webcrypto.subtle.decrypt({name:'RSA-OAEP',label:new TextEncoder().encode(SLOT+'|'+keyId+'|'+api+'|operator-acceptance-b219.yml')},wrong.privateKey,Buffer.from(JSON.parse(saved).ciphertext,'base64')));
  });
  await check('report decryption parameters cannot open credential ciphertext',async()=>{await assert.rejects(webcrypto.subtle.decrypt({name:'RSA-OAEP'},keys.privateKey,Buffer.from(JSON.parse(saved).ciphertext,'base64')));});
  await check('quota failure never falls back to plaintext persistence',async()=>{const x=harness();await x.unlock();x.denyWrite=true;await x.connect();assert.equal(x.run('searchToken'),TOKEN);assert.ok(!x.storage.has(SLOT));assert.ok(x.nodes.githubVaultStatus.textContent.length>20);});
  await check('lock during pending validation cannot resurrect or save token',async()=>{
    const x=harness();await x.unlock();let resolve;x.handler=()=>new Promise(r=>{resolve=r;});const pending=x.connect();x.run('lock()');resolve(new Response('{"state":"active"}',{status:200}));await pending;assert.equal(x.run('searchToken'),'');assert.ok(!x.storage.has(SLOT));
  });
  await check('disconnect during pending validation cannot resurrect token',async()=>{
    const x=harness();await x.unlock();let resolve;x.handler=()=>new Promise(r=>{resolve=r;});const pending=x.connect();x.nodes.searchDisconnect.onclick();resolve(new Response('{"state":"active"}',{status:200}));await pending;assert.equal(x.run('searchToken'),'');assert.ok(!x.storage.has(SLOT));
  });
  await check('lock while restoring cannot resurrect token',async()=>{const x=harness(new Map([[SLOT,saved]]));const pending=x.unlock();x.run('lock()');await pending;assert.equal(x.run('searchToken'),'');});
  await check('confirmed forget-all removes both saved access and GitHub token',async()=>{
    const x=harness(new Map([[SLOT,saved],['admaven-b219-mobile-v1-vault','{}']]));await x.unlock();x.confirm=false;x.nodes.forget.onclick();assert.ok(x.storage.has(SLOT));x.confirm=true;x.nodes.forget.onclick();assert.ok(!x.storage.has(SLOT));assert.ok(!x.storage.has('admaven-b219-mobile-v1-vault'));
  });
  await check('cross-tab deletion and pagehide clear live authorization',async()=>{
    const x=harness(new Map([[SLOT,saved]]));await x.unlock();x.storage.delete(SLOT);x.events.storage({key:SLOT});assert.equal(x.run('searchToken'),'');await x.connect();x.events.pagehide();assert.equal(x.run('searchToken'),'');assert.equal(x.run('privateKey'),null);
  });
  console.log(checks+' encrypted GitHub auth checks passed (synthetic keys/tokens; mocked network).');
}
main().catch(e=>{console.error(e);process.exitCode=1;});
