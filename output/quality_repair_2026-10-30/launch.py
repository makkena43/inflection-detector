from pathlib import Path
from datetime import datetime,timezone
import json,os,subprocess,sys,shutil
import psycopg
root=Path.cwd();out=root/'output/quality_repair_2026-10-30';job=root/'output/process_health/jobs/quality_repair'
assert '771 passed' in (out/'activation_validation.log').read_text()
assert '35 passed' in (out/'final_safety_validation.log').read_text()
assert not (out/'launch.json').exists()
assert shutil.disk_usage(root).free>8*1024**3+64*1024**2
plan=json.loads((job/'plan.json').read_text());assert plan['version']=='quality-repair-1' and plan['constraints']['raw_download_bytes']==0
with psycopg.connect('postgresql:///inflection',autocommit=True) as c:
 assert c.execute("SELECT pg_try_advisory_lock(hashtextextended('quality-repair',0))").fetchone()[0]
 c.execute("SELECT pg_advisory_unlock(hashtextextended('quality-repair',0))")
env=dict(os.environ,INFLECTION_DSN='postgresql:///inflection',INFLECTION_VERIFY_MODEL='local-clf-1')
workers={}
for name,extra in [('coordinator',[]),('cached_evidence',['--evidence'])]:
 with (job/f'{name}.log').open('ab') as log:
  proc=subprocess.Popen([sys.executable,'-u','-m','inflection.quality_repair',*extra],cwd=root,env=env,stdin=subprocess.DEVNULL,stdout=log,stderr=log,start_new_session=True)
 workers[name]=dict(pid=proc.pid,log=str(job/f'{name}.log'))
record=dict(started_at=datetime.now(timezone.utc).isoformat(),workers=workers,financial_filings=len(plan['financial_publications']),source_documents=len(plan['evidence_publications']),missing_price_issuers=len(plan['price_issuers']),weeks=len(plan['weeks']),source_budget_changed=False,reserve_gib=8,original_decisions_preserved=True,validation=dict(full_suite='771 passed',latest_safety_checks='35 passed'))
(out/'launch.json').write_text(json.dumps(record,indent=2))
manifest_path=root/'output/process_health/backend_hardening/active_workers.json';manifest=json.loads(manifest_path.read_text())
manifest['quality_repair']=dict(**workers['coordinator'],state='STARTING',status=str(job/'status.json'),cached_only=True)
manifest['cached_evidence_repair']=dict(**workers['cached_evidence'],state='STARTING',status=str(job/'evidence_status.json'),cached_only=True)
manifest['updated_at']=record['started_at'];manifest_path.write_text(json.dumps(manifest,indent=2))
print(json.dumps(record,indent=2))
