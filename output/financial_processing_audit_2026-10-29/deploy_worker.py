from pathlib import Path
from datetime import datetime,timezone
import json,os,signal,subprocess,sys,time
import psycopg
from inflection.repair_jobs import TASKS
from inflection.financial.rules import RULES_VERSION
root=Path.cwd();folder=root/'output/financial_processing_audit_2026-10-29'
state_path=root/'output/process_health/jobs/analysis.json'
state=json.loads(state_path.read_text());pid=state['pid']
(folder/'analysis_before_refresh.json').write_text(json.dumps(state,indent=2)+'\n')
command=subprocess.run(['ps','-p',str(pid),'-o','command='],capture_output=True,text=True).stdout
if 'inflection.repair_jobs analysis ' in command:
 if os.getpgid(pid)==pid:os.killpg(pid,signal.SIGTERM)
 else:os.kill(pid,signal.SIGTERM)
with psycopg.connect('postgresql:///inflection',autocommit=True) as c:
 assert c.execute("SELECT 1 FROM schema_migrations WHERE version='0027_financial_scan_inputs'").fetchone()
 for attempt in range(30):
  if c.execute('SELECT pg_try_advisory_lock(20261029,%s)',(TASKS.index('analysis'),)).fetchone()[0]:
   c.execute('SELECT pg_advisory_unlock(20261029,%s)',(TASKS.index('analysis'),));break
  time.sleep(1)
 else:raise RuntimeError('Previous analysis worker still owns its lock')
args=[sys.executable,'-u','-m','inflection.repair_jobs','analysis','--from',state['first'],'--to',state['last']]
with (root/'output/process_health/jobs/analysis.log').open('ab') as log:
 child=subprocess.Popen(args,cwd=root,env=dict(os.environ,INFLECTION_DSN='postgresql:///inflection',
      INFLECTION_VERIFY_MODEL='local-clf-1'),stdin=subprocess.DEVNULL,stdout=log,stderr=log,start_new_session=True)
manifest=dict(financial_rules=RULES_VERSION,analysis_pid=child.pid,first=state['first'],last=state['last'],
              native_download_worker_unchanged=True,new_raw_downloads_started=False,
              deployed_at=datetime.now(timezone.utc).isoformat())
(folder/'deployment.json').write_text(json.dumps(manifest,indent=2)+'\n');print(json.dumps(manifest,indent=2))
