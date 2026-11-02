"""Repair every filing matched by the general period-scope audit, not a company allowlist."""
from pathlib import Path
from collections import Counter
from datetime import datetime, timezone
import json,os
import psycopg
from inflection.financial import pipeline as F, rules as R
base=Path(__file__).parent
rows=json.loads((base/'initial_findings.json').read_text())
ids=sorted({r['publication_id'] for r in rows if r['status']=='SKIPPED_STANDALONE' and not r['same_period_consolidated']})
report=dict(state='RUNNING',pid=os.getpid(),rules_version=R.RULES_VERSION,total=len(ids),processed=0,counts={},started_at=datetime.now(timezone.utc).isoformat())
def save():
 report['updated_at']=datetime.now(timezone.utc).isoformat()
 tmp=base/'repair_progress.tmp';tmp.write_text(json.dumps(report,indent=2,default=str));tmp.replace(base/'repair_progress.json')
save();counts=Counter()
with psycopg.connect('postgresql:///inflection',autocommit=True,options='-c statement_timeout=120000') as c:
 try:
  for offset in range(0,len(ids),100):
   counts.update(F.scan(c,publication_ids=ids[offset:offset+100]))
   report.update(processed=min(offset+100,len(ids)),counts=dict(counts));save()
   print('Reprocessed',report['processed'],'of',len(ids),flush=True)
  statuses=c.execute('''SELECT status,count(*) FROM financial_scans WHERE rules_version=%s
     AND publication_id=ANY(%s::uuid[]) GROUP BY status ORDER BY status''',(R.RULES_VERSION,ids)).fetchall()
  details=c.execute('''SELECT f.publication_id,f.issuer_id,i.legal_name,f.status,f.scope,f.period_type,f.period_end,
       f.available_at,f.evaluation_id,f.fired,p.source_url,f.input_fingerprint
       FROM financial_scans f JOIN issuers i USING(issuer_id) JOIN document_publications p USING(publication_id)
       WHERE f.rules_version=%s AND f.publication_id=ANY(%s::uuid[]) ORDER BY f.available_at,f.publication_id''',
       (R.RULES_VERSION,ids))
  keys=[d.name for d in details.description]
  data=[dict(zip(keys,r)) for r in details]
  assert len(data)==len(ids),(len(data),len(ids))
  (base/'repaired_filings.json').write_text(json.dumps(data,indent=2,default=str)+'\n')
  report.update(state='FINISHED',statuses=dict(statuses),stored_records=len(data));save()
  print(json.dumps(dict(state=report['state'],stored_records=len(data),statuses=report['statuses'])),flush=True)
 except Exception as exc:
  report.update(state='FAILED',error=str(exc));save();raise
