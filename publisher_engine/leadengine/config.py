from __future__ import annotations
import os
from pathlib import Path
from copy import deepcopy
import yaml
from dotenv import load_dotenv

DEFAULTS = {
    'data_dir': 'data', 'user_agent': 'PublisherContactResearch/1.0',
    'crawl': {'concurrency': 3, 'request_timeout_seconds': 18, 'site_timeout_seconds': 150,
              'delay_seconds': 1.5, 'max_pages_per_site': 8, 'max_page_bytes': 2000000,
              'max_redirects': 5, 'max_sites_per_run': 30, 'revisit_days': 7,
              'verify_mx': True, 'probe_common_paths': True, 'sitemap': True,
              'commoncrawl': False, 'external_candidates_per_site': 4, 'max_public_profiles_per_site':6},
    'search': {'enabled': True, 'queries_per_run': 8, 'results_per_query': 10,
               'contact_queries_per_run': 2, 'prefer_messaging_recovery':True, 'cache_days': 14,
               'providers': ['tavily','brave','firecrawl','serper','searxng'],
               'limits': {'tavily': {'period':'month','units':700},
                          'brave': {'period':'month','units':700},
                          'firecrawl': {'period':'month','units':700},
                          'serper': {'period':'lifetime','units':2000},
                          'searxng': {'period':'month','units':1000},
                          'hunter': {'period':'month','units':20}}},
    'hunter': {'enabled':False,'max_domains_per_run':2},
    'quality': {'ready_threshold':75,'preferred_channels':['whatsapp','telegram','email','contact_form','skype','phone','social'],'max_contact_age_days':30},
    'schedule': {'enabled':True,'timezone':'Asia/Jerusalem','times':['09:00','18:00']},
    'sheets': {'enabled':False,'tab_prefix':'LeadEngine','auto_sync_after_run':False},
    'retention_days':90,
}

def merge(a: dict, b: dict) -> dict:
    for k,v in b.items():
        if isinstance(v,dict) and isinstance(a.get(k),dict): merge(a[k],v)
        else: a[k]=v
    return a

def load_config(path: str | None = None) -> dict:
    load_dotenv()
    path = path or os.getenv('LEADENGINE_CONFIG','config.yaml')
    p=Path(path).resolve()
    cfg=deepcopy(DEFAULTS)
    if p.exists():
        loaded=yaml.safe_load(p.read_text(encoding='utf-8')) or {}
        if not isinstance(loaded,dict): raise ValueError('config.yaml must contain a mapping')
        merge(cfg,loaded)
    cfg['base_dir']=str(p.parent)
    cfg['data_dir']=str((p.parent / cfg['data_dir']).resolve())
    for key,lo,hi in [('concurrency',1,12),('max_pages_per_site',1,30),('max_sites_per_run',1,500),('max_page_bytes',10000,5000000),('max_public_profiles_per_site',0,8)]:
        value=cfg['crawl'][key]
        if not isinstance(value,int) or not lo<=value<=hi: raise ValueError(f'crawl.{key} must be {lo}..{hi}')
    cfg['crawl']['delay_seconds']=max(0.5,float(cfg['crawl']['delay_seconds']))
    cfg['search']['results_per_query']=min(10,max(1,int(cfg['search']['results_per_query'])))
    from zoneinfo import ZoneInfo
    ZoneInfo(cfg['schedule']['timezone'])
    for value in cfg['schedule']['times']:
        from datetime import time
        time.fromisoformat(value)
    Path(cfg['data_dir']).mkdir(parents=True,exist_ok=True)
    load_dotenv(Path(cfg['data_dir'])/'keys.env',override=True)
    return cfg
