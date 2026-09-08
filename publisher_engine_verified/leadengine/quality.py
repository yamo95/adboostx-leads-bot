from __future__ import annotations
import asyncio
from datetime import datetime,timezone,timedelta
import dns.asyncresolver,dns.resolver,dns.exception
from .urls import hostname,within_site
from .parse import CONTACT_TERMS

class MailDNS:
    def __init__(self):self.cache={};self.sem=asyncio.Semaphore(5)
    async def check(self,email):
        domain=email.rsplit('@',1)[1]
        if domain in self.cache:return self.cache[domain]
        async with self.sem:
            try:
                answer=await dns.asyncresolver.resolve(domain,'MX',lifetime=5)
                if any(str(r.exchange)=='.' for r in answer):result='null_mx_no_mail'
                else:result='mx_present_mailbox_unverified'
            except dns.resolver.NXDOMAIN:result='domain_not_found'
            except dns.resolver.NoAnswer:
                # MX absence alone does not prove invalid mail delivery: RFC 5321 implicit MX.
                result='no_mail_route'
                for typ in ['A','AAAA']:
                    try:
                        await dns.asyncresolver.resolve(domain,typ,lifetime=3)
                        result='implicit_mx_mailbox_unverified';break
                    except dns.resolver.NXDOMAIN:break
                    except (dns.exception.DNSException,OSError):pass
            except (dns.exception.DNSException,OSError):result='dns_inconclusive'
            self.cache[domain]=result;return result

async def score_contacts(contacts,site_url,cfg,dns_check=None):
    dns_check=dns_check or MailDNS()
    for c in contacts:
        if not within_site(c.source_url,site_url) and c.association!='linked_profile_business_contact':
            c.association='external_source_unconfirmed'
        score=30 if c.association=='first_party_published' else 10
        score+=15 if c.method in {'mailto','explicit_telegram','explicit_whatsapp','html_form','explicit_skype'} else 8
        score+=25 if c.purpose=='business' else 17 if c.purpose=='contact' else 12 if c.purpose=='support' else 0
        if CONTACT_TERMS.search(c.source_url):score+=8
        if c.kind=='email':
            own=within_site('https://'+c.value.rsplit('@',1)[1],site_url)
            if own:score+=7
            elif c.purpose not in {'contact','business','support'}:
                c.notes.append('Third-party mailbox without explicit contact context.');score=min(score,49)
            c.verification=await dns_check.check(c.value) if cfg['crawl']['verify_mx'] else 'syntax_only_mailbox_unverified'
            if c.verification=='mx_present_mailbox_unverified':score+=8
            if c.verification in {'null_mx_no_mail','domain_not_found','no_mail_route'}:score=0
            if c.verification in {'dns_inconclusive','syntax_only_mailbox_unverified'}:score=min(score,69)
            c.notes.append('DNS is not proof that the mailbox exists, is read, or will accept a message.')
        elif c.kind=='whatsapp':score+=12
        elif c.kind=='telegram':
            score+=9
            if c.verification!='public_contact_profile_observed':score=min(score,69)
        elif c.kind=='contact_form':
            score+=5;c.verification='form_observed_not_submitted'
        elif c.kind=='phone':score=min(score,60)
        if c.purpose in {'community','community_invite','bot','social_profile'}:score=min(score,40)
        if c.purpose=='unknown':score=min(score,59)
        if c.purpose in {'legal_only','seo_service'}:score=min(score,15)
        if c.verification in {'published_short_link_unresolved','display_link_mismatch'}:score=min(score,49)
        if c.association!='first_party_published':score=min(score,49)
        c.score=min(100,max(0,score))
        c.tier=('EXCLUDED' if c.purpose in {'legal_only','seo_service'} or c.score==0 else 'COMMUNITY' if c.purpose in {'community','community_invite','bot','social_profile'} else 'READY' if c.score>=cfg['quality']['ready_threshold'] else 'REVIEW')
    order=cfg['quality']['preferred_channels']
    # Business applicability before channel preference; a channel must not outrank a real business email.
    contacts.sort(key=lambda x:({'READY':0,'REVIEW':1,'COMMUNITY':2,'EXCLUDED':3}.get(x.tier,4),
        0 if x.purpose=='business' else 1,
        order.index(x.kind) if x.kind in order else 99,-x.score))
    return contacts
