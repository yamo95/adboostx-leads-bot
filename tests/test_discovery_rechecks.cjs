'use strict';
const fs=require('node:fs'),vm=require('node:vm'),path=require('node:path'),assert=require('node:assert/strict');
const {webcrypto}=require('node:crypto');
const dir=process.env.APP_DIR||path.join(__dirname,'..','docs');
class Element{
 constructor(){this.children=[];this.value='';this.checked=false;this.hidden=false;this._text='';this.parentNode=null;this.listeners={};this.classList={toggle(){}};}
 set textContent(x){this._text=String(x??'');this.children=[];}get textContent(){return this._text+this.children.map(x=>x.textContent).join('');}
 append(...xs){for(const x of xs){x.parentNode=this;this.children.push(x);}}
 replaceChildren(...xs){this.children=[];this.append(...xs);}
 setAttribute(){}addEventListener(t,f){(this.listeners[t]||=[]).push(f);}removeEventListener(t,f){this.listeners[t]=(this.listeners[t]||[]).filter(x=>x!==f);}
}
const html=fs.readFileSync(dir+'/index.html','utf8');
const nodes=Object.fromEntries([...html.matchAll(/\bid="([^"]+)"/g)].map(m=>[m[1],new Element()]));
for(const node of Object.values(nodes))node.parentNode=new Element();
for(const m of html.matchAll(/<select[^>]*id="([^"]+)"[^>]*>[\s\S]*?<option value="([^"]+)"/g))nodes[m[1]].value=m[2];
const storage=new Map();
const ctx=vm.createContext({URL,Blob,TextEncoder,TextDecoder,Uint8Array,atob,btoa,AbortController,crypto:webcrypto,Date,console,
 setTimeout(){return 1;},clearTimeout(){},confirm(){return true;},navigator:{},
 document:{getElementById:id=>nodes[id]||Object.values(nodes).flatMap(n=>n.parentNode.children).find(n=>n.id===id),createElement:()=>new Element(),addEventListener(){}},
 localStorage:{getItem:k=>storage.get(k)||null,setItem:(k,v)=>storage.set(k,v),removeItem:k=>storage.delete(k)}});
for(const f of ['app.js','review.js','round-search.js','fresh-search.js'])vm.runInContext(fs.readFileSync(dir+'/'+f,'utf8'),ctx,{filename:f});
const run=x=>vm.runInContext(x,ctx);let checks=0;
const check=(name,f)=>{f();checks++;console.log('PASS '+name);};
const base={domain:'publisher.example',state:'SCANNED',site_fit:'PASS',html_pages_opened:1};
const contact={...base,channel:'telegram',contact:'@CommunityExample',contact_url:'https://t.me/CommunityExample',profile_type:'community',quality:'COMMUNITY',source_url:'https://publisher.example/contact',evidence:'Updates'};
const payload=(s,c)=>({summary:{created_at:'2026-09-01T00:00:00Z'},sites:[s],contacts:[c]});
ctx.fixture=payload(base,contact);
check('community may be rechecked but is not a direct chat',()=>{assert.equal(run('recheckDomains([fixture]).length'),1);assert.equal(run('directMessaging(fixture.contacts[0])'),false);});
ctx.revised=payload({...base,extraction_revision:'messaging-intent-v3'},contact);
check('each extraction revision rechecks a site at most once',()=>assert.equal(run('recheckDomains([fixture,revised]).length'),0));
check('revision exclusion independent of report order',()=>assert.equal(run('recheckDomains([revised,fixture]).length'),0));
ctx.direct=payload(base,{...contact,profile_type:'contact_preview',quality:'PUBLISHED_GENERAL_ROUTE',role:'contact'});
check('site with direct contact not blindly rescanned',()=>assert.equal(run('recheckDomains([direct]).length'),0));
ctx.reject=payload({...base,site_fit:'REJECT'},contact);
check('irrelevant site excluded',()=>assert.equal(run('recheckDomains([reject]).length'),0));
ctx.many=Array.from({length:100},(_,i)=>{const domain='pub'+i+'.example';return payload({...base,domain},{...contact,domain});});
check('rechecks bounded to 80 websites',()=>assert.equal(run('recheckDomains(many).length'),80));
check('no contact values in recheck domain selection',()=>assert.ok(!run('JSON.stringify(recheckDomains(many))').includes('@')));
check('complete seen history remains separate',()=>assert.ok(run('siteFingerprints.toString()').includes('payloads')));
console.log(checks+' discovery/recheck UI checks passed (synthetic fixtures; no network).');
