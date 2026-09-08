"""Optional service-account sync. Only dedicated engine-owned tabs are overwritten."""
from __future__ import annotations
import os,re,json
from .export import lead_rows,effective_contacts,LEAD_FIELDS,CONTACT_FIELDS

def raw_cell(value):
    """Sheets RAW input is literal, so preserve +phones without CSV apostrophes."""
    if value is None:return ''
    if isinstance(value,(dict,list)):return json.dumps(value,ensure_ascii=False)
    return value.replace('\x00','') if isinstance(value,str) else value

def column_label(number):
    """One-based spreadsheet column label without optional dependencies."""
    if number<1:raise ValueError('Column number must be positive')
    label=''
    while number:
        number,remainder=divmod(number-1,26)
        label=chr(65+remainder)+label
    return label

def sync_sheets(db,cfg):
    try:
        from google.oauth2 import service_account
        from google.auth.transport.requests import AuthorizedSession
    except ImportError as e:raise RuntimeError('Install requirements-sheets.txt first') from e
    sheet_id=os.getenv('GOOGLE_SHEET_ID','');credentials=os.getenv('GOOGLE_APPLICATION_CREDENTIALS','')
    if not re.fullmatch(r'[A-Za-z0-9_-]{15,200}',sheet_id) or not credentials:raise ValueError('Configure GOOGLE_SHEET_ID and GOOGLE_APPLICATION_CREDENTIALS')
    prefix=cfg['sheets']['tab_prefix']
    if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{2,30}',prefix):raise ValueError('Invalid tab prefix')
    creds=service_account.Credentials.from_service_account_file(credentials,scopes=['https://www.googleapis.com/auth/spreadsheets'])
    base='https://sheets.googleapis.com/v4/spreadsheets/'+sheet_id
    with AuthorizedSession(creds) as session:
        r=session.get(base,params={'fields':'sheets.properties'},timeout=30);r.raise_for_status()
        props={s['properties']['title']:s['properties'] for s in r.json().get('sheets',[])}
        items=[(prefix+'_Leads',lead_rows(db,cfg),LEAD_FIELDS),(prefix+'_Contacts',effective_contacts(db,cfg),CONTACT_FIELDS)]
        requests=[]
        for name,rows,fields in items:
            if name not in props:requests.append({'addSheet':{'properties':{'title':name,'gridProperties':{'rowCount':max(100,len(rows)+1),'columnCount':len(fields)}}}})
            else:
                gp=props[name].get('gridProperties',{})
                if len(rows)+1>gp.get('rowCount',1000) or len(fields)>gp.get('columnCount',26):
                    requests.append({'updateSheetProperties':{'properties':{'sheetId':props[name]['sheetId'],'gridProperties':{'rowCount':max(len(rows)+1,gp.get('rowCount',1000)),'columnCount':max(len(fields),gp.get('columnCount',26))}},'fields':'gridProperties.rowCount,gridProperties.columnCount'}})
        if requests:
            r=session.post(base+':batchUpdate',json={'requests':requests},timeout=30);r.raise_for_status()
        for name,rows,fields in items:
            # RAW avoids formula evaluation. Chunk writes and clear trailing OLD rows only after all new writes succeed.
            values=[fields]+[[raw_cell(row.get(k,'')) for k in fields] for row in rows]
            for start in range(0,len(values),500):
                target=f"'{name}'!A{start+1}"
                r=session.put(base+'/values/'+target,params={'valueInputOption':'RAW'},json={'values':values[start:start+500]},timeout=30);r.raise_for_status()
            old_count=props.get(name,{}).get('gridProperties',{}).get('rowCount',0)
            if old_count>len(values):
                r=session.post(base+'/values/'+f"'{name}'!A{len(values)+1}:{column_label(len(fields))}{old_count}"+':clear',json={},timeout=30);r.raise_for_status()
    db.event('Synced Google Sheets engine-owned tabs (service-account API)')
    return {'leads':len(items[0][1]),'contacts':len(items[1][1])}
