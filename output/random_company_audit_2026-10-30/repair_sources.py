from pathlib import Path
from datetime import datetime,timezone
import hashlib,json,os,shutil,urllib.request
import psycopg
from inflection import financials
from inflection.financial import pipeline as F
from inflection.packets import pipeline as P
from inflection.sources.download import Archive
from inflection.packet_rebuild import storage_guard
from inflection.coverage_repair import write_progress
root=Path.cwd();out=root/'output/random_company_audit_2026-10-30';archive=Archive(Path.home()/'inflection-archive')
assert '750 passed' in (out/'full_validation.log').read_text()
assert not (out/'source_repair.json').exists()
prior=json.loads((out/'source_repair_status.json').read_text()) if (out/'source_repair_status.json').exists() else {}
report=dict(prior,started_at=prior.get('started_at',datetime.now(timezone.utc).isoformat()),state='RUNNING',pid=os.getpid(),restored=prior.get('restored',[]),archive_bytes_added=prior.get('archive_bytes_added',0))
report.pop('error',None)
write_progress(out/'source_repair_status.json',report)
ledger_path=root/'output/process_health/jobs/financials.json'
with psycopg.connect('postgresql:///inflection',autocommit=True) as c:
 c.execute("SET statement_timeout='60s'");c.execute("SET lock_timeout='10s'")
 locks=[]
 try:
  for lock in (1,5):
   assert c.execute('SELECT pg_try_advisory_lock(20261029,%s)',(lock,)).fetchone()[0],'Related source worker is active; do not duplicate it'
   locks.append(lock)
  ledger=json.loads(ledger_path.read_text());assert ledger['state'] not in ('RUNNING','STARTING')
  manifest=json.loads((root/'output/process_health/backend_hardening/active_workers.json').read_text())
  budget=manifest['financials']['budget_mb']*1024**2;assert budget==128*1024**2
  report['financial_archive_bytes_before']=prior.get('financial_archive_bytes_before',ledger['archive_bytes_added'])
  for sample in json.loads((out/'sample.json').read_text()):
   source=sample['xml']
   if not source:continue
   storage_guard();path=archive.root/source['storage_key']
   if path.is_file():continue
   req=urllib.request.Request(source['source_url'],headers={'User-Agent':'Mozilla/5.0'})
   with urllib.request.urlopen(req,timeout=15) as response:body=response.read(2*1024**2+1)
   assert len(body)<=2*1024**2 and hashlib.sha256(body).hexdigest()==source['sha256']
   assert ledger['archive_bytes_added']+len(body)<=budget,'Existing financial allowance is exhausted'
   storage_guard()
   # Reserve this spend in the original allowance before persisting raw bytes.
   # A crash can conservatively overcount, but must never reset the cap.
   ledger['archive_bytes_added']+=len(body)
   item=dict(publication_id=source['publication_id'],bytes=len(body),sha256=source['sha256'])
   ledger.setdefault('audit_source_recoveries',[]).append(item)
   write_progress(ledger_path,ledger)
   stored=archive.put(body,source['source_url'].rsplit('/',1)[-1]);assert stored.sha256==source['sha256']
   report['restored'].append(item);report['archive_bytes_added']+=len(body)
   write_progress(out/'source_repair_status.json',report)
  report['financial_archive_bytes_after']=ledger['archive_bytes_added']
  print('Source copies restored:',len(report['restored']),'new raw bytes',report['archive_bytes_added'],flush=True)
  report['stage']='Reparse successful cached filings';write_progress(out/'source_repair_status.json',report)
  if prior.get('reparsed') is not None and (out/'cached_reparse.json').exists():
   result=json.loads((out/'cached_reparse.json').read_text())
  else:
   result=financials.reparse_cached(c,archive,guard=storage_guard)
   write_progress(out/'cached_reparse.json',result)
  report.update(reparsed=len(result['reparsed']),source_recovery_pending=len(result['pending']))
  write_progress(out/'source_repair_status.json',report)
  print('Successful local files reparsed:',report['reparsed'],'pending source recovery:',report['source_recovery_pending'],flush=True)
  ids=[r['publication_id'] for r in result['reparsed']]
  if 'financial_scan' not in report:
   report['financial_scan']=dict(F.scan(c,publication_ids=ids)) if ids else {}
   write_progress(out/'source_repair_status.json',report)
  # Rebuild only already-generated current packets whose issuer/cutoff can see
  # these changed filings. The existing wider worker will handle its older heads.
  targets=c.execute('''SELECT DISTINCT s.week_start,s.run_tag,p.issuer_id,
      coalesce((SELECT h.value FROM securities sec JOIN identifier_history h USING(security_id)
         WHERE sec.issuer_id=p.issuer_id AND h.exchange='NSE' AND h.kind='SYMBOL' AND h.valid_to IS NULL
         ORDER BY h.valid_from DESC,h.value LIMIT 1),
         (SELECT sec.isin FROM securities sec WHERE sec.issuer_id=p.issuer_id ORDER BY sec.isin LIMIT 1))
      FROM triage_packets p JOIN triage_shortlists s USING(shortlist_id)
      WHERE p.packet_version='triage-packet-13' AND p.mode<>'ACTUAL_SYSTEM_REPLAY'
        AND NOT EXISTS(SELECT 1 FROM triage_packets child WHERE child.supersedes_id=p.packet_id
         AND child.shortlist_id=p.shortlist_id AND child.issuer_id=p.issuer_id)
        AND EXISTS(SELECT 1 FROM document_publications pub WHERE pub.publication_id=ANY(%s::uuid[])
          AND pub.issuer_id=p.issuer_id AND pub.published_at<=p.cutoff)
      ORDER BY s.week_start DESC,s.run_tag,p.issuer_id''',(ids,)).fetchall() if ids else []
  report['affected_current_packets']=len(targets);report.setdefault('packet_refreshes',[])
  done={(r['week'],r['run_tag'],r['issuer_id']) for r in report['packet_refreshes'] if not r['result'].get('error')}
  for week,tag,issuer,label in targets:
   if (str(week),tag,str(issuer)) in done:continue
   report['stage']=f"Refresh affected packets: {len(report['packet_refreshes'])}/{len(targets)}"
   if not label:
    report.setdefault('pending_packet_refreshes',[]).append(dict(week=str(week),issuer_id=str(issuer),reason='Missing issuer label'));continue
   storage_guard();old_tag=os.environ.get('INFLECTION_RUN_TAG')
   try:
    os.environ['INFLECTION_RUN_TAG']=tag
    refreshed=P.assemble(c,week,label)
   finally:
    if old_tag is None:os.environ.pop('INFLECTION_RUN_TAG',None)
    else:os.environ['INFLECTION_RUN_TAG']=old_tag
   if refreshed.get('error'):
    report.setdefault('pending_packet_refreshes',[]).append(dict(week=str(week),issuer_id=str(issuer),reason=refreshed['error']))
   report['packet_refreshes'].append(dict(week=str(week),run_tag=tag,issuer_id=str(issuer),result=refreshed))
   write_progress(out/'source_repair_status.json',report)
  report['state']='FINISHED_WITH_GAPS' if result['pending'] else 'COMPLETE'
  report['finished_at']=datetime.now(timezone.utc).isoformat()
  write_progress(out/'source_repair.json',report);write_progress(out/'source_repair_status.json',report)
  print(json.dumps({k:v for k,v in report.items() if k not in ('packet_refreshes','restored')},indent=2),flush=True)
 except Exception as exc:
  report.update(state='FAILED',error=str(exc));write_progress(out/'source_repair_status.json',report);raise
 finally:
  for lock in reversed(locks):c.execute('SELECT pg_advisory_unlock(20261029,%s)',(lock,))
