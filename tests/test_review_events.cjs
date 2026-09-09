'use strict';
// Dependency-free UI event regression harness. All rows below are synthetic.
// No private key, real report, outbound request, browser or cloud runner needed.
// Run from repository root: node tests/test_review_events.cjs
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const docs = process.env.APP_DIR || path.resolve(__dirname, '..', 'docs');
class Element {
  constructor(tag='div') {
    this.tagName=tag; this.children=[]; this._text=''; this.value='';
    this.checked=false; this.hidden=false; this.listeners={};
    this.className=''; this.classList={toggle(){}};
  }
  set textContent(value) { this._text=String(value ?? ''); this.children=[]; }
  get textContent() { return this._text+this.children.map(c=>c.textContent||'').join(''); }
  append(...children) { this.children.push(...children); }
  replaceChildren(...children) { this._text=''; this.children=[...children]; }
  setAttribute() {}
  addEventListener(type, callback) { (this.listeners[type] ||= []).push(callback); }
  removeEventListener(type, callback) {
    this.listeners[type]=(this.listeners[type]||[]).filter(fn=>fn!==callback);
  }
  fire(type) { for (const fn of this.listeners[type]||[]) fn({target:this,type}); }
}
const html=fs.readFileSync(path.join(docs,'index.html'),'utf8');
const nodes=Object.fromEntries([...html.matchAll(/\bid="([^"]+)"/g)].map(m=>[m[1],new Element()]));
for (const m of html.matchAll(/<select[^>]*id="([^"]+)"[^>]*>[\s\S]*?<option value="([^"]+)"/g)) nodes[m[1]].value=m[2];
const storage=new Map();
const context=vm.createContext({
  URL, TextEncoder, TextDecoder, Uint8Array, atob, btoa, setTimeout, clearTimeout,
  document:{getElementById:id=>nodes[id],createElement:tag=>new Element(tag),addEventListener(){}},
  localStorage:{getItem:key=>storage.get(key)||null,setItem:(key,value)=>storage.set(key,value),removeItem:key=>storage.delete(key)},
  navigator:{},
});
for (const filename of ['app.js','review.js']) vm.runInContext(fs.readFileSync(path.join(docs,filename),'utf8'),context,{filename});
const run=source=>vm.runInContext(source,context);
const row={domain:'publisher.example',niche:'Synthetic fixture',role:'contact',
  quality:'PUBLISHED_GENERAL_ROUTE',site_fit:'PASS',profile_type:'unverified',
  source_url:'https://publisher.example/contact',via:'',evidence:'Contact fixture',
  observed_at:new Date().toISOString(),notes:'Synthetic fixture only'};
context.fixture={summary:{run_id:'1',created_at:row.observed_at},
  sites:[{domain:row.domain,state:'SCANNED',html_pages_opened:1}],
  contacts:[
    {...row,channel:'email',contact:'fixture@guestpost.cc',contact_url:'mailto:fixture@guestpost.cc'},
    {...row,channel:'email',contact:'fixture@domain-evo.com',contact_url:'mailto:fixture@domain-evo.com'},
    {...row,channel:'telegram',contact:'@ExampleOwner',contact_url:'https://t.me/ExampleOwner',role:'business',quality:'PUBLISHED_BUSINESS_ROUTE'},
    {...row,channel:'telegram',contact:'@ExampleCommunity',contact_url:'https://t.me/ExampleCommunity',profile_type:'community'},
  ]};
run('snaps.set("fixture",fixture);rebuild();');
let checks=0;
function check(name,fn) { fn(); checks++; console.log('PASS '+name); }
function noticesPresent() {
  const held=run('visible.map((g,i)=>({i,reason:reviewReason(g.primary)})).filter(x=>x.reason)');
  assert.equal(held.length,2,'Both synthetic vendor rows must remain visible in All findings');
  for (const item of held) {
    const warnings=nodes.cards.children[item.i].children.filter(c=>c.className==='warning');
    assert.equal(warnings.length,1,`Exactly one review notice required for ${item.reason}`);
    assert.ok(warnings[0].textContent.length>20,'Review notice must contain its explanation');
  }
}
check('preferred view retains only the eligible contact',()=>assert.equal(nodes.total.textContent,'1'));
check('raw evidence groups are retained',()=>assert.equal(run('groups.length'),4));
nodes.channel.value='all';nodes.quality.value='all';
check('quality change retains review notices',()=>{nodes.quality.fire('change');noticesPresent();});
for (const [id,event,value] of [['search','input','fixture'],['channel','change','email'],['follow','change','uncontacted']]) {
  check(id+' event retains review notices',()=>{nodes[id].value=value;nodes[id].fire(event);noticesPresent();});
}
for (const id of ['fit','newOnly']) {
  check(id+' event retains review notices',()=>{nodes[id].checked=true;nodes[id].fire('change');noticesPresent();});
}
check('repeated filtering does not duplicate notices',()=>{nodes.quality.fire('change');nodes.quality.fire('change');noticesPresent();});
for (const id of ['search','channel','quality','follow','fit','newOnly']) {
  check(id+' has exactly one render listener',()=>assert.equal(nodes[id].listeners[id==='search'?'input':'change'].length,1));
}
check('preferred filter continues to exclude held vendor rows',()=>{nodes.quality.value='published';nodes.quality.fire('change');assert.equal(run('visible.length'),0);});
check('business filter continues to expose eligible contact',()=>{
  nodes.search.value='';nodes.channel.value='all';nodes.quality.value='business';
  nodes.quality.fire('change');assert.equal(run('visible.length'),1);
});
check('seen filter still works',()=>{run('seen.add(visible[0].id)');nodes.newOnly.fire('change');assert.equal(run('visible.length'),0);});
console.log(`${checks} UI event regression checks passed (DOM harness; not a browser test).`);
