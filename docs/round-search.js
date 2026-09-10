'use strict';
// Extension of the existing B219 viewer and scanner. No keys or tokens in source.
const SEARCH_API='https://api.github.com/repos/yamo95/adboostx-leads-bot';
const SEARCH_WORKFLOW='operator-acceptance-b219.yml';
const SEARCH_STORE=STORE+'-search-round-v1';
const DATES_STORE=STORE+'-first-added-v1';
const SEARCH_TARGET=30, SEARCH_MAX_PAGES=13;
let searchToken='', searchRunning=false, searchTimer=null, searchEpoch=0, searchFlight=false;
let searchState=load(SEARCH_STORE,null), firstAdded=load(DATES_STORE,{}), searchFound=[];
if(!firstAdded||typeof firstAdded!=='object'||Array.isArray(firstAdded))firstAdded={};
if(!searchState||searchState.format!==1||!/^[a-f0-9]{32}$/.test(searchState.id)||
 !Array.isArray(searchState.baseline)||!searchState.baseline.every(x=>/^[a-f0-9]{64}$/.test(x))||
 !Number.isInteger(searchState.page)||searchState.page<0||searchState.page>=SEARCH_MAX_PAGES)searchState=null;

function eligibleMessaging(c){
 return ['telegram','whatsapp'].includes(c.channel)&&published(c)&&c.site_fit==='PASS'&&
  !!publicURL(c.source_url)&&!!String(c.evidence||'').trim()&&
  !/do not contact|not accepting ads|no advertising/i.test(String(c.evidence||''));
}
function rememberDates(payloads){
 for(const p of payloads){
  const time=Date.parse(p.summary?.created_at);
  if(!Number.isFinite(time))continue;
  const iso=new Date(time).toISOString();
  for(const c of p.contacts||[]){
   if(!c.channel||typeof c.contact!=='string')continue;
   const id=routeID(c), old=Date.parse(firstAdded[id]);
   if(!Number.isFinite(old)||time<old)firstAdded[id]=iso;
  }
 }
 save(DATES_STORE,firstAdded);
}
async function contactHash(c){return hex(await crypto.subtle.digest('SHA-256',enc.encode(routeID(c))));}
async function baselineHashes(payloads){
 const rows=new Map();for(const p of payloads)for(const c of p.contacts||[])if(c.channel&&typeof c.contact==='string')rows.set(routeID(c),c);
 return [...new Set(await Promise.all([...rows.values()].map(contactHash)))];
}
async function roundFindings(state,payloads){
 const baseline=new Set(state.baseline), found=new Map();
 for(const p of payloads){
  if(p.search_round?.id!==state.id)continue;
  for(const c of p.contacts||[]){
   if(!eligibleMessaging(c)||baseline.has(await contactHash(c)))continue;
   found.set(routeID(c),c);
  }
 }
 return [...found.values()];
}
function saveSearch(){if(!save(SEARCH_STORE,searchState))throw Error('STORAGE');}
function searchMessage(text,error=false){$('searchStatus').textContent=text;$('searchStatus').classList.toggle('error',error);}
function renderSearch(){
 const count=searchFound.length;
 $('searchProgress').value=Math.min(count,SEARCH_TARGET);$('searchCount').textContent=count+' / '+SEARCH_TARGET;
 $('searchPause').disabled=!searchRunning;
 $('searchStart').disabled=searchRunning;
 $('searchResume').hidden=!searchState||['complete','exhausted'].includes(searchState.status);
 $('searchResume').disabled=searchRunning;
 $('searchAuthState').textContent=searchToken?'GitHub מחובר לחלון זה בלבד':'נדרש חיבור GitHub להרצת חיפוש';
 if(searchState?.status==='complete'&&count>=SEARCH_TARGET)searchMessage('היעד הושג: '+count+' קונטקטים חדשים ואיכותיים בטלגרם או בוואטסאפ.');
 if(searchState?.status==='exhausted'&&snaps.size)searchMessage('היעד טרם הושג: נמצאו '+count+' מתוך 30. מוצו מקורות הסבב; הממצאים נשמרו.',true);
}
async function refreshSearchCount(){
 if(!searchState){searchFound=[];renderSearch();return;}
 const id=searchState.id;const rows=await roundFindings(searchState,[...snaps.values()]);
 if(searchState?.id!==id||!privateKey)return;
 searchFound=rows;renderSearch();
}

// First-added uses the first report containing the route, NOT the latest crawl
// time and NOT the day this device happened to load the viewer.
const searchPriorRebuild=rebuild;
rebuild=function(){rememberDates([...snaps.values()]);searchPriorRebuild();void refreshSearchCount();};
const searchPriorRender=render;
render=function(){
 searchPriorRender();
 visible.forEach((g,i)=>{
  const card=$('cards').children[i];if(!card)return;
  g.added_at=firstAdded[g.id]||'';
  const text=g.added_at?'נוסף למערכת: '+date(g.added_at):'תאריך הוספה לא זמין';
  const added=element('p',text,'small lead-added');
  added.setAttribute('title','התיעוד הראשון של הקונטקט בדוחות המערכת, לפי שעון ישראל. אינו תאריך הסריקה האחרונה.');
  card.append(added);
 });
};
for(const id of ['search','channel','quality','follow','fit','newOnly']){
 const event=id==='search'?'input':'change';$(id).removeEventListener(event,searchPriorRender);$(id).addEventListener(event,render);
}
csv=function(){
 const fields=['channel','contact','domains','role','quality','site_fit','added_at','observed_at','source_url','via','evidence'];
 const quote=v=>'"'+String(v??'').replace(/\0/g,'').replace(/^[\s]*[=+@-]/,"'$&").replace(/"/g,'""')+'"';
 const lines=[fields.join(',')];
 for(const g of visible){const c={...g.primary,added_at:firstAdded[g.id]||'',domains:[...new Set(g.associations.map(c=>c.domain))].join(' | ')};lines.push(fields.map(f=>quote(c[f])).join(','));}
 const u=URL.createObjectURL(new Blob(['\ufeff'+lines.join('\r\n')],{type:'text/csv;charset=utf-8'}));
 const a=element('a');a.href=u;a.download='AdMaven_contacts.csv';a.click();setTimeout(()=>URL.revokeObjectURL(u),5000);
};$('csv').onclick=csv;

async function historyIndex(){
 const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),20000);
 try{
  const r=await fetch(BASE+'private-b219-results/history.json',{cache:'no-store',credentials:'omit',referrerPolicy:'no-referrer',signal:controller.signal});
  if(r.status===404)return null;
  if(!r.ok)throw Error('HISTORY_HTTP_'+r.status);
  const text=await r.text();if(text.length>2000000)throw Error('HISTORY_SIZE');
  const h=JSON.parse(text);if(h.key_id!==KEY_ID||!Array.isArray(h.runs))throw Error('HISTORY_FORMAT');return h;
 }finally{clearTimeout(timer);}
}
// Preserve all prior ciphertext paths for dates/novelty even when the recent
// index rolls over its 60-report window. Never start a round on partial history.
refresh=async function(){
 if(busy||!privateKey)return false;
 busy=true;$('refresh').disabled=true;setStatus(T.loading);
 const epoch=generation;let errors=0;
 try{
  const [index,history]=await Promise.all([jsonFile(INDEX,1000000),historyIndex()]);
  if(index.key_id!==KEY_ID||!Array.isArray(index.runs))throw Error('INDEX');
  const entries=new Map();for(const e of [...(history?.runs||[]),...index.runs]){
   if(!e||!/^private-b219-results\/runs\/\d+-\d+\.json$/.test(e.path))throw Error('PATH');entries.set(e.path,e);
  }
  if(entries.size>2000)throw Error('HISTORY_LIMIT');
  for(const entry of entries.values()){
   if(epoch!==generation)return false;
   try{
    if(!reports.has(entry.path)){
     const envelope=await jsonFile(entry.path),p=await unseal(envelope);
     if(epoch!==generation)return false;
     if(!entry.path.includes('/'+p.summary.run_id+'-'))throw Error('REPORT_ID');
     reports.set(entry.path,envelope);snaps.set(p.summary.run_id+'|'+p.summary.created_at,p);
    }
   }catch{errors++;}
  }
  if(epoch!==generation)return false;
  rebuild();await refreshSearchCount();setStatus(errors?T.network:T.ready,!!errors);return errors===0&&entries.size>0;
 }catch{if(epoch===generation)setStatus(T.network,true);return false;}
 finally{if(epoch===generation){busy=false;$('refresh').disabled=false;}}
};$('refresh').onclick=refresh;

async function githubSearch(path,method='GET',payload=null){
 if(!searchToken)throw Error('AUTH_REQUIRED');
 if(!path.startsWith('/actions/workflows/'+SEARCH_WORKFLOW))throw Error('API_PATH');
 const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),25000);
 try{
  const r=await fetch(SEARCH_API+path,{method,headers:{Accept:'application/vnd.github+json',Authorization:'Bearer '+searchToken,'Content-Type':'application/json'},
   credentials:'omit',redirect:'error',referrerPolicy:'no-referrer',cache:'no-store',signal:controller.signal,
   ...(payload?{body:JSON.stringify(payload)}:{})});
  if(!r.ok){const error=Error('GITHUB_'+r.status);error.definite=true;throw error;}
  return r.status===204?null:await r.json();
 }finally{clearTimeout(timer);}
}
async function connectSearch(){
 const input=$('searchToken');const candidate=input.value.trim();input.value='';
 if(!candidate){searchMessage('הדבק הרשאת GitHub מוגבלת להרצות במאגר הזה.',true);return;}
 searchToken=candidate;
 try{
  const w=await githubSearch('/actions/workflows/'+SEARCH_WORKFLOW);
  if(w.state!=='active')throw Error('WORKFLOW_INACTIVE');
  searchMessage('החיבור נקרא בהצלחה. לחץ על חיפוש נוסף; הרשאת הפעלה תיבדק בשליחת הבקשה.');
 }catch(e){searchToken='';searchMessage('החיבור נכשל ('+e.message+'). נדרשת הרשאת Actions: Read and write למאגר adboostx-leads-bot.',true);}
 renderSearch();
}
function pauseSearch(message='הסבב הושהה. סריקה שכבר נשלחה לענן עשויה להסתיים; לא תישלח סריקה נוספת.'){
 searchRunning=false;searchEpoch++;clearTimeout(searchTimer);searchTimer=null;
 if(searchState&&!['complete','exhausted'].includes(searchState.status)){searchState.status='paused';try{saveSearch();}catch{}}
 searchMessage(message);renderSearch();
}
const searchPriorLock=lock;
lock=function(){pauseSearch();searchToken='';$('searchToken').value='';searchFound=[];searchPriorLock();renderSearch();};$('lock').onclick=lock;
const searchPriorForget=$('forget').onclick;
$('forget').onclick=function(){searchPriorForget();if(!load(VAULT,null)&&!privateKey){searchToken='';}};

async function startSearch(resume=false){
 if(searchRunning||searchFlight)return;
 if(!privateKey){searchMessage('פתח קודם את הדוחות.',true);return;}
 if(!searchToken){$('searchAuth').open=true;$('searchToken').focus();searchMessage('נדרש חיבור GitHub להרצה. קובץ הגישה לדוחות אינו הרשאת הרצה.',true);return;}
 searchFlight=true;
 try{
  if(!await refresh())throw Error('INCOMPLETE_BASELINE');
  if(resume&&searchState){
   // Only an explicit Resume may retry a confirmed terminal failure. Dispatch
   // the SAME round/page on current main, not GitHub's old-commit re-run API.
   const state=searchState,version=generation;
   const failed=await findSearchRun();
   if(generation!==version||!privateKey||searchState!==state)throw Error('LOCKED');
   if(failed?.status==='completed'&&['failure','cancelled','timed_out','startup_failure'].includes(failed.conclusion)){
    state.retry_after_run_id=String(failed.id);state.pending=null;saveSearch();
   }
  }
  if(!resume){
   if(searchState&&!['complete','exhausted'].includes(searchState.status)&&!confirm('להתחיל סבב חדש במקום הסבב המושהה? סריקה שכבר נשלחה תוכל להסתיים, אך לא תיספר בסבב החדש.'))return;
   searchState={format:1,id:hex(crypto.getRandomValues(new Uint8Array(16))),started_at:new Date().toISOString(),
    target:SEARCH_TARGET,page:0,pool_hash:'',baseline:await baselineHashes([...snaps.values()]),pending:null,status:'running'};
   searchFound=[];$('searchRunLink').hidden=true;
  }else if(!searchState)throw Error('NO_ROUND');
  if(!privateKey)throw Error('LOCKED');
  searchState.status='running';saveSearch();searchRunning=true;searchEpoch++;
  searchMessage('מתחיל חיפוש. היעד הוא 30 קונטקטים חדשים בטלגרם או בוואטסאפ.');renderSearch();
 }catch(e){searchMessage('לא הופעלה סריקה: '+e.message+'. רענן וחבר מחדש לפי הצורך.',true);return;}
 finally{searchFlight=false;}
 void advanceSearch(searchEpoch);
}
function scheduleSearch(epoch){
 clearTimeout(searchTimer);if(searchRunning&&epoch===searchEpoch)searchTimer=setTimeout(()=>void advanceSearch(epoch),20000);
}
async function findSearchRun(){
 const data=await githubSearch('/actions/workflows/'+SEARCH_WORKFLOW+'/runs?event=workflow_dispatch&branch=main&per_page=100');
 const title='B219 search '+searchState.id+' page '+searchState.page;
 const after=Number(searchState.retry_after_run_id||0);
 if(!Number.isSafeInteger(after)||after<0)throw Error('RETRY_RUN_ID');
 return (data.workflow_runs||[])
  .filter(r=>r.display_title===title&&r.head_branch==='main'&&Number.isSafeInteger(r.id)&&r.id>after)
  .sort((a,b)=>b.id-a.id)[0];
}
async function advanceSearch(epoch){
 if(!searchRunning||epoch!==searchEpoch||searchFlight||!privateKey||!searchToken)return;
 searchFlight=true;
 try{
  await refreshSearchCount();
  if(searchFound.length>=SEARCH_TARGET){searchState.status='complete';searchRunning=false;saveSearch();renderSearch();return;}
  let run=await findSearchRun();
  if(!searchRunning||epoch!==searchEpoch)return;
  if(!run&&!searchState.pending){
   searchState.pending={page:searchState.page,requested_at:new Date().toISOString(),accepted:false};saveSearch();
   try{
    await githubSearch('/actions/workflows/'+SEARCH_WORKFLOW+'/dispatches','POST',{ref:'main',inputs:{batch:'search',round_id:searchState.id,page:String(searchState.page),pool_hash:searchState.pool_hash}});
    searchState.pending.accepted=true;saveSearch();
   }catch(e){if(e.definite){searchState.pending=null;saveSearch();}throw e;}
   searchMessage('הבקשה נשלחה ל־GitHub. ממתין לזיהוי ההרצה; עדיין לא מדובר בתוצאות חדשות.');
   scheduleSearch(epoch);return;
  }
  if(!run){
   if(Date.now()-Date.parse(searchState.pending?.requested_at)>10*60000)throw Error('DISPATCH_NOT_CONFIRMED');
   searchMessage('ממתין לאישור ההרצה ב־GitHub. לא תישלח בקשה כפולה.');scheduleSearch(epoch);return;
  }
  if(!/^\d+$/.test(String(run.id)))throw Error('RUN_ID');
  $('searchRunLink').href='https://github.com/yamo95/adboostx-leads-bot/actions/runs/'+run.id;$('searchRunLink').hidden=false;
  if(run.status!=='completed'){
   if(Date.now()-Date.parse(run.created_at)>70*60000)throw Error('RUN_TIMEOUT');
   searchMessage('החיפוש '+(run.status==='in_progress'?'רץ':'ממתין בתור')+'. נמצאו '+searchFound.length+' / 30; מקטע '+(searchState.page+1)+'.');scheduleSearch(epoch);return;
  }
  if(run.conclusion!=='success')throw Error('SCAN_'+String(run.conclusion).toUpperCase());
  if(!await refresh())throw Error('REPORT_REFRESH_FAILED');
  if(!searchRunning||epoch!==searchEpoch)return;
  const report=[...snaps.values()].find(p=>String(p.summary.run_id)===String(run.id)&&p.search_round?.id===searchState.id&&p.search_round.page===searchState.page);
  if(!report){searchMessage('הסריקה הסתיימה; ממתין לפרסום הדוח המוצפן.');if(Date.now()-Date.parse(run.updated_at)>10*60000)throw Error('REPORT_NOT_PUBLISHED');scheduleSearch(epoch);return;}
  const meta=report.search_round;
  if(meta.target!==SEARCH_TARGET||!Number.isInteger(meta.pool_size)||!/^[a-f0-9]{64}$/.test(meta.pool_hash))throw Error('ROUND_METADATA');
  if(searchState.pool_hash&&searchState.pool_hash!==meta.pool_hash)throw Error('POOL_CHANGED');
  searchState.pool_hash=meta.pool_hash;searchState.pending=null;delete searchState.retry_after_run_id;
  await refreshSearchCount();
  if(searchFound.length>=SEARCH_TARGET){searchState.status='complete';searchRunning=false;}
  else if(!meta.has_more||searchState.page+1>=SEARCH_MAX_PAGES){searchState.status='exhausted';searchRunning=false;}
  else{searchState.page++;searchMessage('נמצאו '+searchFound.length+' / 30. ממשיך למקטע נוסף, ללא ספירה חוזרת של קונטקטים.');}
  saveSearch();renderSearch();if(searchRunning)scheduleSearch(epoch);
 }catch(e){
  pauseSearch('הסבב נעצר לבדיקה ('+e.message+'). התוצאות נשמרו; היעד לא סומן כהושג.');
  $('searchStatus').classList.toggle('error',true);
 }finally{searchFlight=false;}
}
$('searchConnect').onclick=connectSearch;
$('searchStart').onclick=()=>void startSearch(false);
$('searchResume').onclick=()=>void startSearch(true);
$('searchPause').onclick=()=>pauseSearch();
$('searchDisconnect').onclick=()=>{pauseSearch();searchToken='';$('searchToken').value='';renderSearch();};
renderSearch();
if(searchState&&!['complete','exhausted'].includes(searchState.status))searchMessage('נמצא סבב קודם. פתח את הדוחות, חבר GitHub ולחץ על המשך הסבב.');