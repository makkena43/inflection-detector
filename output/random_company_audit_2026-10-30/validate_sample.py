import json,hashlib
from pathlib import Path
from datetime import datetime
import xml.etree.ElementTree as ET
import psycopg
from inflection.audit import recheck_packet
from inflection.triage.screen import triage
from inflection.packets import pipeline as P
out=Path(__file__).parent;samples=json.loads((out/'sample.json').read_text());results=[]
with psycopg.connect('postgresql:///inflection',autocommit=True) as c:
 c.execute("SET statement_timeout='30s'")
 for s in samples:
  with c.transaction():
   c.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
   p=s['packet'];cutoff=datetime.fromisoformat(p['manifest']['cutoff'])
   name=c.execute('SELECT legal_name FROM issuers WHERE issuer_id=%s',(s['issuer_id'],)).fetchone()[0]
   fresh=recheck_packet(c,p);screen=triage(fresh,c,s['issuer_id'])
   facts=P._facts(c,dict(issuer_id=s['issuer_id'],cutoff=cutoff,mode=p['manifest']['mode']))
   pubids=sorted({str(f['publication_id']) for f in facts if f.get('publication_id')})
   provenance=c.execute('SELECT publication_id,published_at,issuer_id,publication_basis,source_url FROM document_publications WHERE publication_id=ANY(%s::uuid[])',(pubids,)).fetchall() if pubids else []
   row=dict(label=s['label'],name=name,week=s['week'],historical_action=s['historical_action'],current_screen=screen,
    packet_version=p['manifest']['packet_version'],cutoff=str(cutoff),financial_changed=fresh.get('financial_recheck',{}).get('changed'),
    fact_count=len(facts),financial_status=fresh.get('financials',{}).get('status'),scope=fresh.get('financials',{}).get('scope'),
    ttm=fresh.get('financials',{}).get('ttm'),nomination_issues=fresh['manifest'].get('nomination_issues'),
    future_fact_dates=[str(f['fact_id']) for f in facts if f.get('available_at') and f['available_at']>cutoff],
    foreign_fact_sources=[str(pid) for pid,at,iss,basis,url in provenance if str(iss)!=s['issuer_id']],
    source_publications=[dict(publication_id=str(pid),published_at=str(at),basis=basis,url=url) for pid,at,iss,basis,url in provenance],
    event_summary=[{k:e.get(k) for k in ('event_id','version_id','event_type','stage','amount','period','relationship','published_at')} for e in fresh.get('events',[])],
    source_recheck=fresh.get('source_recheck'),event_recheck=fresh.get('event_recheck'))
   row['xml_archive_candidates']=s['xml_candidates'];row['xml_archives_available']=s['xml_files_available']
   if s['xml'] and (Path.home()/'inflection-archive'/s['xml']['storage_key']).is_file():
    path=Path.home()/'inflection-archive'/s['xml']['storage_key'];body=path.read_bytes();row['xml_sha_verified']=hashlib.sha256(body).hexdigest()==s['xml']['sha256']
    root=ET.fromstring(body);local=lambda tag:tag.rsplit('}',1)[-1]
    row['raw_xml_units']=[ET.tostring(e,encoding='unicode') for e in root if local(e.tag)=='unit']
    row['raw_xml_critical_facts']=[dict(tag=local(e.tag),text=e.text,attrs=e.attrib) for e in root.iter() if local(e.tag) in ('RevenueFromOperations','ProfitBeforeTax','ProfitLossForPeriod','PaidUpValueOfEquityShareCapital','FaceValueOfEquityShareCapital','DateOfStartOfReportingPeriod','DateOfEndOfReportingPeriod','Symbol','NameOfCompany','NameOfTheCompany')]
    row['stored_xml_facts']=c.execute('SELECT metric,period_type,period_start,period_end,scope,value,scale,currency,value_kind,original_text,missing_reason FROM financial_facts WHERE publication_id=%s ORDER BY metric,period_end',(s['xml']['publication_id'],)).fetchall()
   results.append(row);print(row['label'],name,s['historical_action'],'=>',screen['triage_action'],'facts',len(facts),'financial',row['financial_status'],'changed',row['financial_changed'],flush=True)
   (out/'validation.json').write_text(json.dumps(results,indent=2,default=str))
