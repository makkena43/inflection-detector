from pathlib import Path
from datetime import datetime, timezone
import json, os, signal, subprocess, sys, time, hashlib
import psycopg
from inflection.repair_jobs import TASKS
from inflection.commercial.vocabulary import RULES_VERSION
from inflection.triage.screen import SCREEN_VERSION
root=Path.cwd();out=root/'output/company_quality_audit_2026-10-29'
installed=Path.home()/'inflection-jobs/engine/engine.py';maintained=root/'ops/engine.py'
backup=installed.with_name('engine.py.bak-audit-repairs-20261029')
if not backup.exists():backup.write_bytes(installed.read_bytes())
installed.write_bytes(maintained.read_bytes())
assert installed.read_bytes()==maintained.read_bytes()
state_path=root/'output/process_health/jobs/analysis.json'
state=json.loads(state_path.read_text())
(out/'analysis_before_two_year_repair.json').write_text(json.dumps(state,indent=2))
pid=state.get('pid')
command=subprocess.run(['ps','-p',str(pid),'-o','command='],capture_output=True,text=True).stdout
if 'inflection.repair_jobs analysis ' in command:os.kill(pid,signal.SIGTERM)
with psycopg.connect('postgresql:///inflection',autocommit=True) as c:
 for attempt in range(30):
  if c.execute('SELECT pg_try_advisory_lock(20261029,%s)',(TASKS.index('analysis'),)).fetchone()[0]:
   c.execute('SELECT pg_advisory_unlock(20261029,%s)',(TASKS.index('analysis'),));break
  time.sleep(1)
 else:raise RuntimeError('Previous analysis worker still holds its task lock')
log_path=root/'output/process_health/jobs/analysis.log'
with log_path.open('ab') as log:
 child=subprocess.Popen([sys.executable,'-u','-m','inflection.repair_jobs','analysis','--from','2024-10-29',
                         '--to','2026-10-28'],cwd=root,
      env=dict(os.environ,INFLECTION_DSN='postgresql:///inflection',INFLECTION_VERIFY_MODEL='local-clf-1'),
      stdin=subprocess.DEVNULL,stdout=log,stderr=log,start_new_session=True)
manifest=dict(engine=str(installed),backup=str(backup),sha256=hashlib.sha256(maintained.read_bytes()).hexdigest(),
              rules_version=RULES_VERSION,screen_version=SCREEN_VERSION,analysis_pid=child.pid,
              first='2024-10-29',last='2026-10-28',new_raw_downloads=False,
              deployed_at=datetime.now(timezone.utc).isoformat())
(out/'repair_deployment.json').write_text(json.dumps(manifest,indent=2)+'\n')
print(json.dumps(manifest,indent=2))
