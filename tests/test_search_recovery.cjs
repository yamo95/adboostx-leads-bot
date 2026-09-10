'use strict';
// Synthetic-only regression: explicit retry preserves the round and never
// silently retries an uncertain dispatch. No real token, key or network.
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const {webcrypto}=require('node:crypto');
const docs=process.env.APP_DIR||path.join(__dirname,'..','docs');
class Element{
 constructor(){this.children=[];this.value='';this.checked=false;this.hidden=false;this.listeners={};this._text='';this.classList={toggle(){}};}
 set textContent(x){this._text=String(x??'');this.children=[];}get textContent(){return this._text+this.children.map(c=>c.textContent||'').join('');}
 append(...xs){this.children.push(...xs);}replaceChildren(...xs){this.children=[...xs];this._text='';}
 setAttribute(){}focus(){}click(){this.onclick?.();}
 addEventListener(e,fn){(this.listeners[e]||=[]).push(fn);}removeEventListener(e,fn){this.listeners[e]=(this.listeners[e]||[]).filter(x=>x!==fn);}
}
const html=fs.readFileSync(path.join(docs,'index.html'),'utf8');
const nodes=Object.fromEntries([...html.matchAll(/\bid="([^"]+)"/g)].map(m=>[m[1],new Element()]));
for(const m of html.matchAll(/<select[^>]*id="([^"]+)"[^>]*>[\s\S]*?<option value="([^"]+)"/g))nodes[m[1]].value=m[2];
const storage=new Map(),requests=[];let runs=[],uncertain=false;
const ctx=vm.createContext({URL,Blob,TextEncoder,TextDecoder,Uint8Array,atob,btoa,AbortController,crypto:webcrypto,Date,console,
 setTimeout(){return 1;},clearTimeout(){},confirm(){return true;},navigator:{},
 fetch:async(url,opts={})=>{requests.push({url,opts});if(opts.method==='POST'){if(uncertain)throw Error('NETWORK_LOST');return new Response(null,{status:204});}return new Response(JSON.stringify({workflow_runs:runs}),{status:200});},
 document:{getElementById:id=>nodes[id],createElement:()=>new Element(),addEventListener(){}},
 localStorage:{getItem:k=>storage.get(k)||null,setItem:(k,v)=>storage.set(k,v),removeItem:k=>storage.delete(k)}
});
for(const f of ['app.js','review.js','round-search.js'])vm.runInContext(fs.readFileSync(path.join(docs,f),'utf8'),ctx,{filename:f});
const run=s=>vm.runInContext(s,ctx),tick=()=>new Promise(resolve=>setImmediate(resolve));let checks=0;
async function check(label,fn){await fn();checks++;console.log('PASS '+label);}
const id='a'.repeat(32),hash='b'.repeat(64),baseline=['c'.repeat(64)];
const state={format:1,id,target:30,page:1,pool_hash:hash,baseline,pending:{accepted:true},status:'paused',started_at:'2026-09-10T01:00:00Z'};
const row=n=>({id:n,display_title:'B219 search '+id+' page 1',head_branch:'main',status:'completed',conclusion:'failure'});
const posts=()=>requests.filter(x=>x.opts.method==='POST');
async function reset(){requests.length=0;runs=[];uncertain=false;ctx.initial=JSON.parse(JSON.stringify(state));run('privateKey={};searchToken="SYNTHETIC_TEST_TOKEN";searchState=initial;searchRunning=false;searchFlight=false;snaps.clear();refresh=async()=>true');}
async function main(){
 await reset();runs=[row(101),row(102)];
 await check('latest matching failed run is selected even out of order',async()=>assert.equal((await run('findSearchRun()')).id,102));
 await check('ordinary polling pauses on failure without resubmission',async()=>{run('searchRunning=true');await run('advanceSearch(searchEpoch)');assert.equal(posts().length,0);assert.equal(run('searchRunning'),false);});
 await check('explicit resume dispatches one replacement',async()=>{await run('startSearch(true)');await tick();assert.equal(posts().length,1);});
 await check('replacement uses same round, page and pool on current main',()=>{const p=JSON.parse(posts()[0].opts.body);assert.equal(p.ref,'main');assert.equal(p.inputs.round_id,id);assert.equal(p.inputs.page,'1');assert.equal(p.inputs.pool_hash,hash);assert.equal(p.inputs.batch,'search');});
 await check('baseline and original start date are retained',()=>{assert.equal(run('searchState.baseline[0]'),baseline[0]);assert.equal(run('searchState.started_at'),state.started_at);});
 await check('failed run excluded and accepted replacement persisted',()=>{assert.equal(run('searchState.retry_after_run_id'),'102');assert.equal(run('searchState.pending.accepted'),true);});
 await check('repeated polling cannot duplicate an accepted request',async()=>{await run('advanceSearch(searchEpoch)');await run('advanceSearch(searchEpoch)');assert.equal(posts().length,1);});
 await check('pause and resume preserve pending replacement without duplicates',async()=>{run('pauseSearch()');await run('startSearch(true)');await tick();assert.equal(posts().length,1);});
 await check('new replacement run wins over old failures',async()=>{runs=[row(102),{...row(103),status:'in_progress',conclusion:null},row(101)];assert.equal((await run('findSearchRun()')).id,103);await run('advanceSearch(searchEpoch)');assert.equal(posts().length,1);assert.equal(run('searchRunning'),true);});
 await check('resume during an active request does not dispatch again',async()=>{await run('startSearch(true)');await tick();assert.equal(posts().length,1);});
 await check('authorization never reaches persistent storage or inputs',()=>{assert.ok(!JSON.stringify([...storage.values()]).includes('SYNTHETIC_TEST_TOKEN'));assert.ok(!posts()[0].opts.body.includes('SYNTHETIC_TEST_TOKEN'));});
 await check('lock clears token and automatic continuation',()=>{run('lock()');assert.equal(run('searchToken'),'');assert.equal(run('searchRunning'),false);});
 await reset();runs=[row(102)];uncertain=true;
 await check('uncertain dispatch retains pending marker and pauses',async()=>{await run('startSearch(true)');await tick();assert.equal(posts().length,1);assert.ok(run('searchState.pending'));assert.equal(run('searchRunning'),false);});
 await check('resume never blindly retries an uncertain POST',async()=>{await run('startSearch(true)');await tick();assert.equal(posts().length,1);});
 await reset();runs=[{...row(102),status:'in_progress',conclusion:null}];
 await check('explicit resume does not replace a queued or running job',async()=>{await run('startSearch(true)');await tick();assert.equal(posts().length,0);assert.equal(run('searchState.retry_after_run_id'),undefined);});
 await reset();runs=[{...row(102),conclusion:'success',updated_at:new Date().toISOString()}];
 await check('successful job awaiting publication is not re-dispatched',async()=>{await run('startSearch(true)');await tick();assert.equal(posts().length,0);assert.equal(run('searchState.retry_after_run_id'),undefined);});
 console.log(checks+' search recovery regression checks passed (mock network).');
}
main().catch(e=>{console.error(e);process.exitCode=1;});
