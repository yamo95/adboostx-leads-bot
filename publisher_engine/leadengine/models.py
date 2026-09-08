from __future__ import annotations
from dataclasses import dataclass,field,asdict
from datetime import datetime,timezone

def now() -> str: return datetime.now(timezone.utc).isoformat(timespec='seconds')

@dataclass
class Page:
    url: str
    final_url: str=''
    status: int=0
    state: str='error'
    html: str=''
    error: str=''
    fetched_at: str=field(default_factory=now)
    redirected: list[str]=field(default_factory=list)
    content_hash: str=''

@dataclass
class Contact:
    kind: str
    value: str
    source_url: str
    evidence: str
    method: str
    purpose: str='unknown'
    association: str='first_party_published'
    verification: str='published_not_verified'
    score: int=0
    tier: str='REVIEW'
    observed_at: str=field(default_factory=now)
    contact_url: str=''
    notes: list[str]=field(default_factory=list)
    def dict(self) -> dict: return asdict(self)
