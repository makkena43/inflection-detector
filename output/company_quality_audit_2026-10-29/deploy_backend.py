from pathlib import Path
import os,json,subprocess,sys,signal,time,hashlib
from datetime import datetime,timezone
import psycopg
root=Path.cwd();installed=Path.home()/'inflection-jobs/engine/engine.py';source=root/'ops/engine.py'
backup=installed.with_name(installed.name+'.bak-company-audit-20261029')
if not backup.exists():backup.write_bytes(installed.read_bytes())
installed.write_bytes(source.read_bytes())
assert installed.read_bytes()==source.read_bytes()
status_path=root/'output/process_health/jobs/analysis.json'
status=json.loads(status_path.read_text());pid=status.get('pid')
command=subprocess.run(['ps','-p',str(pid),'-o','command='],capture_output=True,text=True).stdout
if 'inflection.repair_jobs analysis ' in command:
 os.kill(pid,signal.SIGTERM)
with psycopg.connect('postgresql:///inflection',autocommit=True) as c:
 from inflection.repair_jobs import TASKS
 for attempt in range(30):
  if c.execute('SELECT pg_try_advisory_lock(20261029,%s)',(TASKS.index('analysis'),)).fetchone()[0]:
   c.execute('SELECT pg_advisory_unlock(20261029,%s)',(TASKS.index('analysis'),));break
  time.sleep(1)
 else:raise RuntimeError('Prior analysis worker still holds its lock')
log_path=root/'output/process_health/jobs/analysis.log'
with log_path.open('ab') as log:
 args=[sys.executable,'-u','-m','inflection.repair_jobs','analysis','--from',status['first'],'--to',status['last']]
 env=dict(os.environ,INFLECTION_DSN='postgresql:///inflection',INFLECTION_VERIFY_MODEL='local-clf-1')
 child=subprocess.Popen(args,cwd=root,env=env,stdin=subprocess.DEVNULL,stdout=log,stderr=log,start_new_session=True)
from inflection.commercial.vocabulary import RULES_VERSION
manifest=dict(installed_engine=str(installed),backup=str(backup),sha256=hashlib.sha256(source.read_bytes()).hexdigest(),analysis_pid=child.pid,commercial_rules=RULES_VERSION,screen_version='local-screen-3',deployed_at=datetime.now(timezone.utc).isoformat())
(root/'output/company_quality_audit_2026-10-29/deployment.json').write_text(json.dumps(manifest,indent=2)+'\n')
print(json.dumps(manifest,indent=2))
