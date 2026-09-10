'use strict';
// B219 controller extension. No tokens, private keys or contacts in dispatch data.
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
const FRESH_EXTRACTION_REVISION='messaging-intent-v3';
function recheckDomains(payloads){
 const latest=new Map(),revised=new Set(),whatsappRevised=new Set();
 for(const p of [...payloads].sort((a,b)=>String(a.summary?.created_at||'').localeCompare(String(b.summary?.created_at||'')))){
  for(const site of p.sites||[]){
   const h=String(site.domain||'').toLowerCase().replace(/^www\./,'').replace(/\.$/,'');
   if(!h||!/^[a-z0-9.-]+$/.test(h))continue;
   if(site.extraction_revision===FRESH_EXTRACTION_REVISION)revised.add(h);
   if(site.whatsapp_context_revision==='whatsapp-label-v1')whatsappRevised.add(h);
   if(site.state==='SCANNED'&&site.html_pages_opened>0)latest.set(h,{site,contacts:(p.contacts||[]).filter(c=>c.domain===site.domain)});
  }
 }
 return [...latest].filter(([h,{site,contacts}])=>site.site_fit==='PASS'&&
  ((!revised.has(h)&&contacts.some(c=>c.channel==='telegram'&&['community','unverified'].includes(c.profile_type)&&publicURL(c.source_url)))||
   (!whatsappRevised.has(h)&&contacts.some(c=>c.channel==='email'&&published(c)&&/contact|kontakt|contato|kontak/i.test(String(c.source_url)))))&&
  !contacts.some(c=>directMessaging(c))).map(([h])=>h).sort().slice(0,80);
}
async function recheckFingerprints(payloads){
 return Promise.all(recheckDomains(payloads).map(async h=>hex(await crypto.subtle.digest('SHA-256',enc.encode(h))).slice(0,16)));
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
 const last=[...relevant].sort((a,b)=>(a.search_round.page||0)-(b.search_round.page||0)).at(-1)?.search_round;
 freshDiagnostics={raw:all.size,known,held,newCount:found.length,
  scanned:new Set(relevant.flatMap(p=>(p.sites||[]).map(s=>s.domain))).size,
  skipped:Number(last?.known_sites_skipped||0),pool:Number(last?.pool_size||0),
  discovery:(last?.discovery_checks||[]).filter(x=>x.candidates>0).length,
  rechecks:Number(last?.recheck_sites||0),unseen:Number(last?.new_candidate_sites??last?.pool_size??0),
  health:last?.discovery_health?.state||'unknown',failed:Number(last?.discovery_health?.failed||0)};
 return found;
};
const freshPriorRenderSearch=renderSearch;
renderSearch=function(){
 freshPriorRenderSearch();
 if(!$('searchDiagnostics'))return;
 if(searchState?.strategy==='fresh'&&freshDiagnostics){
  const d=freshDiagnostics;
  $('searchDiagnostics').textContent=`${d.unseen} אתרים חדשים; ${d.rechecks} אתרים לבדיקת חילוץ חוזרת. ${d.skipped} דולגו. נבדקו ${d.scanned}. צ׳אטים: ${d.newCount} חדשים, ${d.known} מוכרים, ${d.held} לבדיקה. מקורות גילוי שהוסיפו מועמדים: ${d.discovery}; בקשות שנכשלו: ${d.failed}.`;
  if(searchState.status==='exhausted'&&!d.pool)searchMessage(d.health==='unavailable'?'מקורות הגילוי לא היו זמינים. לא נסרקו אתרים בסבב הזה; היעד לא הושג.':'לא נמצאו מועמדים נוספים לסריקה. היעד לא הושג.',true);
 }else $('searchDiagnostics').textContent='חיפוש מקורות חדשים ובדיקה ממוקדת של דפי קשר וערוצים שבהם חסר איש קשר ישיר. קונטקטים מוכרים, קבוצות, בוטים ואימיילים אינם נספרים ליעד של 30 צ׳אטים חדשים.';
};
const freshPriorGithub=githubSearch;
githubSearch=async function(path,method='GET',payload=null){
 if(method==='POST'&&path.endsWith('/dispatches')&&searchState?.strategy==='fresh'){
  payload={...payload,inputs:{...payload.inputs,batch:'fresh',seen_hosts:searchState.page===0?searchState.seen_hosts.join(','):'',recheck_hosts:searchState.page===0?(searchState.recheck_hosts||[]).join(','):''}};
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
  const [baseline,seen_hosts,recheck_hosts]=await Promise.all([baselineHashes(payloads),siteFingerprints(payloads),recheckFingerprints(payloads)]);
  if(generation!==version||!privateKey||!searchToken)throw Error('LOCKED');
  searchState={format:1,strategy:'fresh',id:hex(crypto.getRandomValues(new Uint8Array(16))),
   started_at:new Date().toISOString(),target:30,page:0,pool_hash:'',baseline,seen_hosts,recheck_hosts,pending:null,status:'running'};
  freshDiagnostics=null;searchFound=[];$('searchRunLink').hidden=true;
  saveSearch();searchRunning=true;searchEpoch++;
  searchMessage('מגלה מקורות חדשים ובודק אנשי קשר שפוספסו בדפי קשר ובערוצים. היעד: 30 צ׳אטים חדשים עם מקור.');renderSearch();
 }catch(e){searchMessage('לא הופעל חיפוש: '+e.message+'. הנתונים הקיימים נשמרו.',true);return;}
 finally{searchFlight=false;}
 void advanceSearch(searchEpoch);
};
const diagnostics=element('p','','small');diagnostics.id='searchDiagnostics';
$('searchStatus').parentNode.append(diagnostics);
$('searchStart').textContent='חיפוש משופר — אתרים חדשים';
if(searchState?.strategy==='fresh'&&(!Array.isArray(searchState.seen_hosts)||
 !searchState.seen_hosts.every(h=>/^[a-f0-9]{16}$/.test(h))||
 (searchState.recheck_hosts!==undefined&&(!Array.isArray(searchState.recheck_hosts)||searchState.recheck_hosts.length>80||!searchState.recheck_hosts.every(h=>/^[a-f0-9]{16}$/.test(h)))))){
 searchState=null;searchMessage('מצב החיפוש השמור אינו תקין. אפשר לפתוח סבב חדש.',true);
}
renderSearch();
const directOption=element('option','צ׳אט ישיר עם מקור');directOption.value='direct';$('quality').append(directOption);
const freshPriorFiltered=filtered;
filtered=function(){
 const rows=freshPriorFiltered();
 if($('quality').value!=='direct')return rows;
 return rows.filter(g=>directMessaging(g.primary)).sort((a,b)=>(Date.parse(firstAdded[b.id])||0)-(Date.parse(firstAdded[a.id])||0)||a.id.localeCompare(b.id));
};
const directView=element('button','צ׳אטים ישירים — החדשים בראש','secondary');directView.id='directView';
directView.onclick=()=>{
 $('channel').value='messaging';$('quality').value='direct';$('search').value='';$('follow').value='all';$('newOnly').checked=false;$('fit').checked=true;render();
 $('cards').scrollIntoView?.({behavior:'smooth',block:'start'});
};
$('searchStart').parentNode.append(directView);
