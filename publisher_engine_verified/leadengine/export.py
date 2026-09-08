from __future__ import annotations
import csv,json,io
from pathlib import Path
from datetime import datetime,timezone,timedelta

def endpoint_key(kind,value):
    # Normalize only comparison: keep published casing in source evidence.
    return (kind,value.casefold() if kind=='telegram' else value)

LEAD_FIELDS=['domain','url','final_url','classification','effective_classification','category','relevance','contact_state','priority','best_kind','best_contact','best_score','best_source','best_verification','reasons','last_scan','manual_decision','manual_reason','compliance_review','discovery_source']
CONTACT_FIELDS=['domain','kind','value','contact_url','purpose','score','tier','verification','association','source_url','evidence','method','observed_at','last_seen','shared_across_domains','notes']

def effective_contacts(db,cfg):
    cutoff=(datetime.now(timezone.utc)-timedelta(days=cfg['quality']['max_contact_age_days'])).isoformat()
    rows=db.rows('SELECT c.* FROM contacts c JOIN sites s ON s.domain=c.domain WHERE c.active=1 AND s.suppressed=0 AND s.alias_of IS NULL AND c.last_seen>=? ORDER BY c.score DESC',(cutoff,))
    shared={}
    for r in rows:shared.setdefault(endpoint_key(r['kind'],r['value']),set()).add(r['domain'])
    for r in rows:r['shared_across_domains']=len(shared[endpoint_key(r['kind'],r['value'])])
    return rows

def lead_rows(db,cfg):
    rows=db.rows('SELECT * FROM sites WHERE suppressed=0 AND alias_of IS NULL ORDER BY priority DESC,domain')
    cutoff=(datetime.now(timezone.utc)-timedelta(days=cfg['quality']['max_contact_age_days'])).isoformat()
    for r in rows:
        r['effective_classification']=r['manual_decision'] or r['classification']
        best=json.loads(r['best_contact']) if r.get('best_contact') else {}
        if (r.get('last_scan') or '')<cutoff and best:
            best={};r['contact_state']='STALE';r['priority']=0
        if r['effective_classification']!='PASS' and r['contact_state']=='READY':r['contact_state']='REVIEW_SITE'
        for k,field in [('best_kind','kind'),('best_contact','value'),('best_score','score'),('best_source','source_url'),('best_verification','verification')]:r[k]=best.get(field,'')
    return rows

def safe_cell(value):
    if value is None:return ''
    if isinstance(value,(dict,list)):value=json.dumps(value,ensure_ascii=False)
    if isinstance(value,str):
        # Protect Excel / LibreOffice consumers from formula injection, including phones beginning with +.
        value=value.replace('\x00','')
        if value.lstrip().startswith(('=','+','-','@')) or value.startswith(('\t','\r','\n')):return "'"+value
    return value

def csv_text(rows,fields):
    buf=io.StringIO(newline='');w=csv.DictWriter(buf,fieldnames=fields,extrasaction='ignore');w.writeheader()
    for r in rows:w.writerow({k:safe_cell(r.get(k,'')) for k in fields})
    return '\ufeff'+buf.getvalue()


def contact_clusters(contacts):
    """One row per shared public endpoint; not proof of common legal ownership."""
    groups={}
    for r in contacts:
        if r['kind'] not in {'telegram','whatsapp','email'}:continue
        if r.get('purpose') in {'bot','community','community_invite','seo_service','legal_only','social_profile'}:continue
        key=endpoint_key(r['kind'],r['value'])
        group=groups.setdefault(key,{'kind':r['kind'],'contact':r['value'],'domains':set(),'source_urls':set()})
        group['domains'].add(r['domain']);group['source_urls'].add(r['source_url'])
    return [{'kind':v['kind'],'contact':v['contact'],'domain_count':len(v['domains']),
             'domains':' | '.join(sorted(v['domains'])),'source_urls':' | '.join(sorted(v['source_urls'])),
             'action':'Shared route: review once before outreach. Common ownership NOT established.'}
            for _,v in sorted(groups.items()) if len(v['domains'])>1]

def write_exports(db,cfg):
    out=Path(cfg['data_dir'])/'exports';out.mkdir(exist_ok=True)
    leads=lead_rows(db,cfg);contacts=effective_contacts(db,cfg)
    (out/'leads.csv').write_text(csv_text(leads,LEAD_FIELDS),encoding='utf-8')
    (out/'contacts.csv').write_text(csv_text(contacts,CONTACT_FIELDS),encoding='utf-8')
    (out/'ready.csv').write_text(csv_text([x for x in leads if x['effective_classification']=='PASS' and x['contact_state']=='READY'],LEAD_FIELDS),encoding='utf-8')
    clusters=contact_clusters(contacts)
    (out/'contact_clusters.csv').write_text(csv_text(clusters,['kind','contact','domain_count','domains','source_urls','action']),encoding='utf-8')
    (out/'results.json').write_text(json.dumps({'leads':leads,'contacts':contacts,'shared_contact_clusters':clusters},ensure_ascii=False,indent=2),encoding='utf-8')
    return out
