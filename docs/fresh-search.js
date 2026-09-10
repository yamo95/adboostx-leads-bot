'use strict';
// Upgrade the current B219 controller, without replacing legacy resumable rounds.
// The crawler receives only site fingerprints, never the decryption key or contacts.
// The contact page for this publisher links to the same two messaging routes
// published by a link-building agency. Keep evidence, but do not count it as a
// verified publisher contact. Sources: https://filmy4.org/contact-us/ and
// https://w3webrank.com/contact-us/ and https://w3webrank.com/.
const freshPriorReviewReason=reviewReason;
reviewReason=function(c){
 const h=String(c.domain||'').toLowerCase().replace(/^www\./,'');
 if(h==='filmy4.org'&&['telegram','whatsapp'].includes(c.channel))return 'SEO_SERVICE_CONTACT';
 return freshPriorReviewReason(c);
};
let freshDiagnostics=null;
async function siteFingerprints(payloads){
 const hosts=new Set();
 for(const p of payloads)for(const s of p.sites||[]){
  const h=String(s.domain||'').toLowerCase().replace(/^www\./,'').replace(/\.$/,'');
  if(h&&/^[a-z0-9.-]+$/.test(h))hosts.add(h);
 }
 if(!hosts.size)throw Error('COMPLETE_SITE_HISTORY_REQUIRED');
 if(hosts.size>3500)throw Error('SITE_HISTORY_LIMIT');
 return (await Promise.all([...hosts].map(async h=>hex(await crypto.subtle.digest('SHA-256',enc.encode(h))).slice(0,16)))).sort();
}
function directMessaging(c){
 if(!eligibleMessaging(c))return false;
 if(c.channel==='telegram')return c.profile_type==='contact_preview';
 return c.channel==='whatsapp'&&/^\+[1-9][0-9]{7,14}$/.test(String(c.contact));
}
const freshPriorFindings=roundFindings;
roundFindings=async function(state,payloads){
 if(state.strategy!=='fresh')return freshPriorFindings(state,payloads);
 const relevant=payloads.filter(p=>p.search_round?.id===state.id);
 const all=new Map();for(const p of relevant)for(const c of p.contacts||[])if(['telegram','whatsapp'].includes(c.channel)){
  const id=routeID(c),old=all.get(id);if(!old||directMessaging(c)&&!directMessaging(old))all.set(id,c);
 }
 const baseline=new Set(state.baseline),found=[];let known=0,held=0;
 for(const c of all.values()){
  if(!directMessaging(c)){held++;continue;}
  if(baseline.has(await contactHash(c))){known++;continue;}
  found.push(c);
 }
 const last=relevant.at(-1)?.search_round;
 freshDiagnostics={raw:all.size,known,held,newCount:found.length,
  scanned:new Set(relevant.flatMap(p=>(p.sites||[]).map(s=>s.domain))).size,
  skipped:Number(last?.known_sites_skipped||0),pool:Number(last?.pool_size||0),
  discovery:(last?.discovery_checks||[]).filter(x=>x.candidates>0).length};
 return found;
};
const freshPriorRenderSearch=renderSearch;
renderSearch=function(){
 freshPriorRenderSearch();
 if(!$('searchDiagnostics'))return;
 if(searchState?.strategy==='fresh'&&freshDiagnostics){
  const d=freshDiagnostics;
  $('searchDiagnostics').textContent=`${d.pool} אתרים חדשים ברשימת הסבב; ${d.skipped} אתרים מוכרים דולגו מראש. נבדקו ${d.scanned} אתרים. נמצאו ${d.raw} מסלולי צ׳אט: ${d.newCount} חדשים ומתאימים, ${d.known} כבר מוכרים, ${d.held} לבדיקה/קבוצות/בוטים. חיפושי רשת שהוסיפו מועמדים: ${d.discovery}.`;
 }else $('searchDiagnostics').textContent='חיפוש משופר בוחר אתרים שלא הופיעו בדוחות הקודמים. אימיילים, קבוצות, בוטים וחשבונות טלגרם שלא זוהו כצ׳אט ישיר אינם משלימים את יעד ה־30.';
};
const freshPriorGithub=githubSearch;
githubSearch=async function(path,method='GET',payload=null){
 if(method==='POST'&&path.endsWith('/dispatches')&&searchState?.strategy==='fresh'){
  payload={...payload,inputs:{...payload.inputs,batch:'fresh',seen_hosts:searchState.page===0?searchState.seen_hosts.join(','):''}};
 }
 return freshPriorGithub(path,method,payload);
};
const freshPriorStart=startSearch;
startSearch=async function(resume=false){
 if(resume)return freshPriorStart(true);
 if(searchRunning||searchFlight)return;
 if(!privateKey){searchMessage('פתח קודם את הדוחות.',true);return;}
 if(!searchToken){$('searchAuth').open=true;$('searchToken').focus();searchMessage('חבר GitHub כדי להפעיל חיפוש חדש.',true);return;}
 searchFlight=true;
 try{
  const version=generation;
  if(!await refresh())throw Error('INCOMPLETE_BASELINE');
  if(searchState&&!['complete','exhausted'].includes(searchState.status)&&!confirm('להתחיל סבב משופר חדש במקום הסבב הקודם? סריקה שכבר נשלחה לענן תוכל להסתיים.'))return;
  const payloads=[...snaps.values()];
  const [baseline,seen_hosts]=await Promise.all([baselineHashes(payloads),siteFingerprints(payloads)]);
  if(generation!==version||!privateKey||!searchToken)throw Error('LOCKED');
  searchState={format:1,strategy:'fresh',id:hex(crypto.getRandomValues(new Uint8Array(16))),
   started_at:new Date().toISOString(),target:30,page:0,pool_hash:'',baseline,seen_hosts,pending:null,status:'running'};
  freshDiagnostics=null;searchFound=[];$('searchRunLink').hidden=true;
  saveSearch();searchRunning=true;searchEpoch++;
  searchMessage('מגלה מקורות חדשים ומדלג על אתרים מוכרים לפני הסריקה. היעד: 30 צ׳אטים חדשים עם מקור.');renderSearch();
 }catch(e){searchMessage('לא הופעל חיפוש: '+e.message+'. הנתונים הקיימים נשמרו.',true);return;}
 finally{searchFlight=false;}
 void advanceSearch(searchEpoch);
};
// Existing button callbacks resolve these function bindings at click time.
const diagnostics=element('p','','small');diagnostics.id='searchDiagnostics';
$('searchStatus').parentNode.append(diagnostics);
$('searchStart').textContent='חיפוש משופר — אתרים חדשים';
if(searchState?.strategy==='fresh'&&(!Array.isArray(searchState.seen_hosts)||
 !searchState.seen_hosts.every(h=>/^[a-f0-9]{16}$/.test(h)))){
 searchState=null;searchMessage('מצב החיפוש השמור אינו תקין. אפשר לפתוח סבב חדש.',true);
}
renderSearch();

// A separate view makes source-backed direct chats and recent additions easy
// to find without silently relabeling the existing mixed contact inventory.
const directOption=element('option','\u05e6\u05f3\u05d0\u05d8 \u05d9\u05e9\u05d9\u05e8 \u05e2\u05dd \u05de\u05e7\u05d5\u05e8');directOption.value='direct';$('quality').append(directOption);
const freshPriorFiltered=filtered;
filtered=function(){
 const rows=freshPriorFiltered();
 if($('quality').value!=='direct')return rows;
 return rows.filter(g=>directMessaging(g.primary)).sort((a,b)=>(Date.parse(firstAdded[b.id])||0)-(Date.parse(firstAdded[a.id])||0)||a.id.localeCompare(b.id));
};
const directView=element('button','\u05e6\u05f3\u05d0\u05d8\u05d9\u05dd \u05d9\u05e9\u05d9\u05e8\u05d9\u05dd \u2014 \u05d4\u05d7\u05d3\u05e9\u05d9\u05dd \u05d1\u05e8\u05d0\u05e9','secondary');directView.id='directView';
directView.onclick=()=>{
 $('channel').value='messaging';$('quality').value='direct';$('search').value='';$('follow').value='all';$('newOnly').checked=false;$('fit').checked=true;render();
 $('cards').scrollIntoView?.({behavior:'smooth',block:'start'});
};
$('searchStart').parentNode.append(directView);
