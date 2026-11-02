import psycopg,json,urllib.request
from datetime import datetime,timezone
from pathlib import Path
from inflection.temporal import snapshot_sql
from inflection.process_health import read_worker_status
out=Path('output/temporal_processing_audit_2026-10-29')
c=psycopg.connect('postgresql:///inflection',autocommit=True)
now=c.execute('SELECT clock_timestamp()').fetchone()[0]
report=dict(checked_at=str(now))
report['eligible_revenue_period_coverage']=c.execute("""WITH latest AS (
    SELECT issuer_id,max(period_end) FILTER(WHERE period_type='QUARTER') q,
      max(period_end) FILTER(WHERE period_type='ANNUAL') a
    FROM financial_facts_asof WHERE metric='revenue' AND segment IS NULL
      AND scope IN ('CONSOLIDATED','STANDALONE') AND currency='INR' AND value>0
      AND available_at<=%s AND period_end<=(%s AT TIME ZONE 'Asia/Kolkata')::date
    GROUP BY issuer_id)
    SELECT count(*),count(*) FILTER(WHERE q>=(%s AT TIME ZONE 'Asia/Kolkata')::date-185
        OR a>=(%s AT TIME ZONE 'Asia/Kolkata')::date-550) FROM latest""",(now,now,now,now)).fetchone()
report['eligible_revenue_period_coverage_note']='Issuers with any eligible revenue period vs any period inside the age limit; not proof of complete TTM or comparable scope.'
report['history_counts']=dict(c.execute('SELECT source_table,count(*) FROM supplementary_versions GROUP BY source_table').fetchall())
report['history_backdated_to_before_observation']=c.execute("SELECT count(*) FROM supplementary_versions WHERE observed_at<%s",(out.joinpath('activation.json').read_text() and json.loads((out/'activation.json').read_text())['history_started_at'],)).fetchone()[0]
assert report['history_backdated_to_before_observation']==0
for task in ('analysis','financials'):
 s=read_worker_status(Path('output/process_health/jobs')/f'{task}.json')
 report[task]={k:s.get(k) for k in ('state','pid','stage','updated_at')}
with urllib.request.urlopen('http://127.0.0.1:8765/',timeout=10) as r:report['backend_http_status']=r.status
assert report['backend_http_status']==200
(out/'live_verification.json').write_text(json.dumps(report,indent=2,default=str))
print(json.dumps(report,indent=2,default=str))
