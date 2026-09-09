'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const {webcrypto}=require('node:crypto');
const docs=process.env.APP_DIR||path.join(__dirname,'..','docs');
class Element{
 constructor(){this.children=[];this.value='';this.hidden=false;this.disabled=false;this.checked=false;this.listeners={};this._text='';this.className='';this.classList={toggle(){}};}
 set textContent(x){this._text=String(x??'');this.children=[];}get textContent(){return this._text+this.children.map(x=>x.textContent||'').join('');}
 append(...xs){this.children.push(...xs);}replaceChildren(...xs){this.children=[...xs];this._text='';}
 setAttribute(){}focus(){}click(){this.onclick?.();}
 addEventListener(e,fn){(this.listeners[e]||=[]).push(fn);}removeEventListener(e,fn){this.listeners[e]=(this.listeners[e]||[]).filter(x=>x!==fn);}
 fire(e){for(const fn of this.listeners[e]||[])fn({target:this});}
}
const html=fs.readFileSync(path.join(docs,'index.html'),'utf8');
const nodes=Object.fromEntries([...html.matchAll(/\bid="([^"]+)"/g)].map(m=>[m[1],new Element()]));
for(const m of html.matchAll(/<select[^>]*id="([^"]+)"[^>]*>[\s\S]*?<option value="([^"]+)"/g))nodes[m[1]].value=m[2];
const storage=new Map(),requests=[];let handler=async()=>new Response('{}',{status:404});
const ctx=vm.createContext({URL,Blob,TextEncoder,TextDecoder,Uint8Array,atob,btoa,AbortController,crypto:webcrypto,Date,console,
 setTimeout(){return 1;},clearTimeout(){},confirm(){return true;},navigator:{},
 fetch:async(url,opts={})=>{requests.push({url,opts});return handler(url,opts);},
 document:{getElementById:id=>nodes[id],createElement:()=>new Element(),addEventListener(){}},
 localStorage:{getItem:k=>storage.get(k)||null,setItem:(k,v)=>storage.set(k,v),removeItem:k=>storage.delete(k)}
});
for(const f of ['app.js','review.js','round-search.js'])vm.runInContext(fs.readFileSync(path.join(docs,f),'utf8'),ctx,{filename:f});
const run=s=>vm.runInContext(s,ctx);let checks=0;
async function check(label,fn){await fn();checks++;console.log('PASS '+label);}
const base={domain:'publisher.example',channel:'telegram',contact:'@ExampleOwner',contact_url:'https://t.me/ExampleOwner',role:'business',quality:'PUBLISHED_BUSINESS_ROUTE',profile_type:'contact_preview',source_url:'https://publisher.example/contact',evidence:'Contact owner',site_fit:'PASS',niche:'APK',observed_at:'2026-09-09T21:00:00Z'};
const report=(contacts,time='2026-09-09T20:00:00Z',id='1')=>({summary:{run_id:id,created_at:time},sites:[{domain:base.domain,state:'SCANNED',html_pages_opened:1}],contacts});
const rid='a'.repeat(32);ctx.base=base;ctx.rid=rid;ctx.payload=report([base]);
async function main(){
 await check('Telegram eligible',()=>assert.equal(run('eligibleMessaging(base)'),true));
 for(const [label,patch] of [
  ['email',{channel:'email',contact:'owner@publisher.com',contact_url:'mailto:owner@publisher.com'}],
  ['community',{profile_type:'community'}],['bot',{profile_type:'bot'}],['unresolved',{profile_type:'short_link_unresolved'}],
  ['review site',{site_fit:'REVIEW'}],['missing source',{source_url:''}],['missing evidence',{evidence:''}],['declined outreach',{evidence:'Do not contact for advertising'}]
 ])await check('excludes '+label,()=>{ctx.patch=patch;assert.equal(run('eligibleMessaging({...base,...patch})'),false);});
 await check('WhatsApp eligible',()=>assert.equal(run("eligibleMessaging({...base,channel:'whatsapp',contact:'+12345678901',contact_url:'https://wa.me/12345678901'})"),true));
 await check('first-added uses report date, not observation time',()=>{run('snaps.set("old",payload);rebuild()');assert.equal(run('firstAdded[routeID(base)]'),'2026-09-09T20:00:00.000Z');});
 ctx.later=report([{...base,observed_at:'2026-09-10T23:00:00Z'}],'2026-09-10T22:00:00Z','2');
 await check('later scan cannot change first-added',()=>{run('snaps.set("new",later);rebuild()');assert.equal(run('firstAdded[routeID(base)]'),'2026-09-09T20:00:00.000Z');});
 await check('date visible on each card',()=>assert.equal(nodes.cards.children[0].children.filter(e=>e.className==='small lead-added').length,1));
 await check('date survives filtering without duplicates',()=>{nodes.channel.fire('change');nodes.channel.fire('change');assert.equal(nodes.cards.children[0].children.filter(e=>e.className==='small lead-added').length,1);});
 for(const id of ['search','channel','quality','follow','fit','newOnly'])await check('one filter listener '+id,()=>assert.equal(nodes[id].listeners[id==='search'?'input':'change'].length,1));
 ctx.historical=report([{...base,profile_type:'community'}]);
 await check('raw baseline includes old excluded routes',async()=>{ctx.baseline=await run('baselineHashes([historical])');assert.equal(ctx.baseline.length,1);});
 ctx.fresh=report([base,{...base,contact:'@EXAMPLEOWNER'},{...base,contact:'@NewOwner',contact_url:'https://t.me/NewOwner'}]);ctx.fresh.search_round={id:rid};
 await check('no counting old routes or case variants',async()=>{const n=await run('roundFindings({id:rid,baseline},[fresh])');assert.equal(n.length,1);assert.equal(n[0].contact,'@NewOwner');});
 await check('unrelated run not counted',async()=>assert.equal((await run('roundFindings({id:"b".repeat(32),baseline:[]},[fresh])')).length,0));
 await check('historical first date backfills independent of load order',()=>{run('firstAdded={};rememberDates([later,payload])');assert.equal(run('firstAdded[routeID(base)]'),'2026-09-09T20:00:00.000Z');});
 await check('no token in source or persistent storage',()=>assert.ok(![...storage.values()].join('').includes('TOKEN_TEST_ONLY')));
 await check('CSP permits only added GitHub API origin',()=>{assert.ok(html.includes('connect-src https://raw.githubusercontent.com https://api.github.com;'));assert.ok(!html.includes("unsafe-inline"));});
 await check('CSV has separate first-added and last-observed columns',()=>assert.ok(run('csv.toString()').includes("'added_at','observed_at'")));
 // Simulate the real dispatch and polling functions, never contact live GitHub.
 ctx.state={format:1,id:rid,started_at:new Date().toISOString(),target:30,page:0,pool_hash:'',baseline:[],pending:null,status:'running'};
 run('privateKey={};searchToken="TOKEN_TEST_ONLY";searchState=state;searchRunning=true;snaps.clear();');
 handler=async(url,opts)=>opts.method==='POST'?new Response(null,{status:204}):new Response(JSON.stringify({workflow_runs:[]}),{status:200});
 await check('button controller dispatches existing workflow on main',async()=>{
  await run('advanceSearch(searchEpoch)');const req=requests.find(r=>r.opts.method==='POST');assert.ok(req);
  const body=JSON.parse(req.opts.body);assert.equal(body.ref,'main');assert.equal(body.inputs.batch,'search');assert.equal(body.inputs.round_id,rid);assert.equal(body.inputs.page,'0');
  assert.ok(!req.opts.body.includes('PRIVATE KEY'));assert.ok(req.url.endsWith('operator-acceptance-b219.yml/dispatches'));
 });
 await check('no blind re-dispatch while request is pending',async()=>{const before=requests.filter(r=>r.opts.method==='POST').length;await run('advanceSearch(searchEpoch)');assert.equal(requests.filter(r=>r.opts.method==='POST').length,before);});
 await check('GitHub token never persisted',()=>assert.ok(![...storage.values()].join('').includes('TOKEN_TEST_ONLY')));
 await check('lock clears authorization and automatic continuation',()=>{run('lock()');assert.equal(run('searchToken'),'');assert.equal(run('searchRunning'),false);});
 const contacts=Array.from({length:30},(_,i)=>({...base,contact:'@New'+i,contact_url:'https://t.me/New'+i}));
 ctx.thirty=report(contacts);ctx.thirty.search_round={id:rid,page:0,target:30,pool_size:30,pool_hash:'c'.repeat(64),has_more:false};
 await check('30 unique quality messaging contacts completes without another dispatch',async()=>{
  run('privateKey={};searchToken="TOKEN_TEST_ONLY";searchState={...state,pending:null};searchRunning=true;snaps.clear();snaps.set("30",thirty)');
  const before=requests.length;await run('advanceSearch(searchEpoch)');assert.equal(run('searchState.status'),'complete');assert.equal(requests.length,before);assert.equal(nodes.searchCount.textContent,'30 / 30');
 });
 ctx.twentyNine=report(contacts.slice(0,29),'2026-09-09T20:00:00Z','99');ctx.twentyNine.search_round={...ctx.thirty.search_round};
 handler=async()=>new Response(JSON.stringify({workflow_runs:[{id:99,display_title:'B219 search '+rid+' page 0',head_branch:'main',status:'completed',conclusion:'success',updated_at:new Date().toISOString()}]}),{status:200});
 await check('29 at source exhaustion is not success',async()=>{
  run('searchState={...state,pending:null,status:"running"};searchRunning=true;snaps.clear();snaps.set("29",twentyNine);refresh=async()=>true');
  await run('advanceSearch(searchEpoch)');assert.equal(run('searchState.status'),'exhausted');assert.equal(nodes.searchCount.textContent,'29 / 30');
 });
 await check('0 at source exhaustion is not success',async()=>{
  ctx.zero=report([],'2026-09-09T20:00:00Z','99');ctx.zero.search_round={...ctx.thirty.search_round};
  run('searchState={...state,pending:null,status:"running"};searchRunning=true;snaps.clear();snaps.set("zero",zero)');
  await run('advanceSearch(searchEpoch)');assert.equal(run('searchState.status'),'exhausted');assert.equal(nodes.searchCount.textContent,'0 / 30');
 });
 console.log(checks+' search/date checks passed (mock network; not a live dispatch).');
}
main().catch(e=>{console.error(e);process.exitCode=1;});
