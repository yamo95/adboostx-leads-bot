'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const {webcrypto}=require('node:crypto');
const docs=process.env.APP_DIR||require('node:path').join(__dirname,'..','docs');
class E{
 constructor(){this.children=[];this.value='';this.hidden=false;this.disabled=false;this.checked=false;this.listeners={};this._text='';this.className='';this.classList={toggle(){}};this.parentNode=null;}
 set textContent(x){this._text=String(x??'');this.children=[];}get textContent(){return this._text+this.children.map(x=>x.textContent||'').join('');}
 append(...xs){for(const x of xs){x.parentNode=this;this.children.push(x);}}replaceChildren(...xs){this.children=[];this._text='';this.append(...xs);}
 setAttribute(){}focus(){}click(){return this.onclick?.();}
 addEventListener(e,fn){(this.listeners[e]||=[]).push(fn);}removeEventListener(e,fn){this.listeners[e]=(this.listeners[e]||[]).filter(x=>x!==fn);}
}
const html=fs.readFileSync(docs+'/index.html','utf8');
const nodes=Object.fromEntries([...html.matchAll(/\bid="([^"]+)"/g)].map(m=>[m[1],new E()]));
for(const [id,n] of Object.entries(nodes))n.id=id;
for(const m of html.matchAll(/<select[^>]*id="([^"]+)"[^>]*>[\s\S]*?<option value="([^"]+)"/g))nodes[m[1]].value=m[2];
const root=new E();root.append(...Object.values(nodes));
function locate(n,id){return n.id===id?n:n.children.map(c=>locate(c,id)).find(Boolean);}
const storage=new Map(),requests=[];
let handler=async(url,opts)=>new Response(JSON.stringify({workflow_runs:[]}),{status:200});
const ctx=vm.createContext({URL,Blob,TextEncoder,TextDecoder,Uint8Array,atob,btoa,AbortController,crypto:webcrypto,Date,console,
 setTimeout(){return 1;},clearTimeout(){},confirm(){return true;},navigator:{},
 fetch:async(url,opts={})=>{requests.push({url,opts});return handler(url,opts);},
 document:{getElementById:id=>locate(root,id),createElement:()=>new E(),addEventListener(){}},
 localStorage:{getItem:k=>storage.get(k)||null,setItem:(k,v)=>storage.set(k,v),removeItem:k=>storage.delete(k)}
});
for(const f of ['app.js','review.js','round-search.js','fresh-search.js'])vm.runInContext(fs.readFileSync(docs+'/'+f,'utf8'),ctx,{filename:f});
const run=s=>vm.runInContext(s,ctx);let n=0;
async function check(label,fn){await fn();n++;console.log('PASS '+label);}
const base={domain:'publisher.example',channel:'telegram',contact:'@OwnerExample',contact_url:'https://t.me/OwnerExample',role:'business',quality:'PUBLISHED_BUSINESS_ROUTE',profile_type:'contact_preview',source_url:'https://publisher.example/contact',evidence:'Contact owner',site_fit:'PASS',observed_at:'2026-09-10T09:00:00Z'};
ctx.base=base;ctx.rid='a'.repeat(32);
const p={summary:{run_id:'100',created_at:'2026-09-10T09:00:00Z'},sites:[{domain:base.domain,state:'SCANNED',html_pages_opened:1}],contacts:[base]};ctx.p=p;
async function main(){
 await check('UI diagnostics added',()=>assert.ok(locate(root,'searchDiagnostics')));
 await check('agency Telegram held despite fit label',()=>assert.equal(run("directMessaging({...base,domain:'filmy4.org'})"),false));
 await check('agency WhatsApp held despite fit label',()=>assert.equal(run("directMessaging({...base,domain:'filmy4.org',channel:'whatsapp',contact:'+12345678901',contact_url:'https://wa.me/12345678901'})"),false));
 await check('direct Telegram accepted',()=>assert.equal(run('directMessaging(base)'),true));
 for(const type of ['bot','community','unverified','short_link_unresolved'])await check('reject '+type,()=>{ctx.type=type;assert.equal(run('directMessaging({...base,profile_type:type})'),false);});
 await check('WhatsApp phone link accepted',()=>assert.equal(run("directMessaging({...base,channel:'whatsapp',contact:'+12345678901',contact_url:'https://wa.me/12345678901'})"),true));
 await check('email never counts',()=>assert.equal(run("directMessaging({...base,channel:'email',contact:'a@b.com',contact_url:'mailto:a@b.com'})"),false));
 await check('stable canonical site hashes',async()=>{
  ctx.other={...p,sites:[{domain:'www.PUBLISHER.example'}]};
  const a=await run('siteFingerprints([p])'),b=await run('siteFingerprints([other,p])');assert.equal(a.length,1);assert.equal(a[0],b[0]);assert.match(a[0],/^[a-f0-9]{16}$/);
 });
 await check('no empty history',async()=>assert.rejects(run('siteFingerprints([])'),/HISTORY/));
 ctx.state={format:1,strategy:'fresh',id:ctx.rid,baseline:[],page:0,seen_hosts:['a'.repeat(16)]};
 ctx.fresh={...p,search_round:{id:ctx.rid,strategy:'fresh',pool_size:15,known_sites_skipped:1200}};
 await check('new direct chats counted once',async()=>assert.equal((await run('roundFindings(state,[fresh,fresh])')).length,1));
 await check('old chats not new',async()=>{ctx.state.baseline=[await run('contactHash(base)')];assert.equal((await run('roundFindings(state,[fresh])')).length,0);});
 await check('legacy round compatible',async()=>{ctx.old={...ctx.state,strategy:undefined,baseline:[]};assert.equal((await run('roundFindings(old,[fresh])')).length,1);});
 run('searchState=state;searchToken="MOCK_TOKEN";privateKey={}');
 handler=async()=>new Response(null,{status:204});
 await check('fresh dispatch uses exact host history',async()=>{
  await run("githubSearch('/actions/workflows/'+SEARCH_WORKFLOW+'/dispatches','POST',{ref:'main',inputs:{batch:'search',round_id:rid,page:'0',pool_hash:''}})");
  const req=requests.at(-1),body=JSON.parse(req.opts.body);assert.equal(body.inputs.batch,'fresh');assert.equal(body.inputs.seen_hosts,'a'.repeat(16));assert.ok(!req.opts.body.includes('@OwnerExample'));assert.ok(!req.opts.body.includes('MOCK_TOKEN'));
 });
 await check('later page uses frozen plan without sending history again',async()=>{
  run('searchState.page=1');await run("githubSearch('/actions/workflows/'+SEARCH_WORKFLOW+'/dispatches','POST',{ref:'main',inputs:{page:'1'}})");assert.equal(JSON.parse(requests.at(-1).opts.body).inputs.seen_hosts,'');
 });
 await check('legacy dispatch unchanged',async()=>{
  run('searchState.strategy=undefined');await run("githubSearch('/actions/workflows/'+SEARCH_WORKFLOW+'/dispatches','POST',{ref:'main',inputs:{batch:'search'}})");assert.equal(JSON.parse(requests.at(-1).opts.body).inputs.batch,'search');
 });
 await check('token not persisted',()=>assert.ok(![...storage.values()].join('').includes('MOCK_TOKEN')));
 const rows=Array.from({length:29},(_,i)=>({...base,contact:'@NewContact'+i,contact_url:'https://t.me/NewContact'+i}));ctx.twentyNine={...ctx.fresh,contacts:rows};ctx.state={...ctx.state,strategy:'fresh',baseline:[]};
 await check('29 stays below target',async()=>assert.equal((await run('roundFindings(state,[twentyNine])')).length,29));
 ctx.thirty={...ctx.fresh,contacts:[...rows,{...base,contact:'@NumberThirty',contact_url:'https://t.me/NumberThirty'}]};
 await check('30 direct unique meets target',async()=>assert.equal((await run('roundFindings(state,[thirty])')).length,30));
 // UI click path uses new start while Resume retains original recovery logic.
 run('privateKey={};searchToken="MOCK_TOKEN";searchState=null;snaps.set("baseline",p);refresh=async()=>true;advanceSearch=async()=>{globalThis.advanced=searchState.strategy}');
 await check('new click prepares a fresh round with baseline',async()=>{
  await run('startSearch(false)');assert.equal(run('searchState.strategy'),'fresh');assert.equal(run('searchState.baseline.length'),1);assert.equal(run('searchState.seen_hosts.length'),1);assert.equal(run('advanced'),'fresh');
 });
 await check('first-added date untouched',()=>{run('rebuild()');assert.equal(run('firstAdded[routeID(base)]'),'2026-09-10T09:00:00.000Z');});
 await check('direct chat view applies quality filter',()=>{locate(root,'directView').click();assert.equal(nodes.quality.value,'direct');assert.equal(nodes.channel.value,'messaging');assert.equal(run('visible.length'),1);});
 await check('lock removes credentials',()=>{run('lock()');assert.equal(run('searchToken'),'');assert.equal(run('searchRunning'),false);});
 console.log(n+' fresh UI regression checks passed (mock dispatch).');
}
main().catch(e=>{console.error(e);process.exitCode=1;});
