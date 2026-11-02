from pathlib import Path
from datetime import datetime,timezone
import json,os,signal,subprocess,sys,time,urllib.request
import psycopg
root=Path('/Users/makkenasrinivas/PycharmProjects/inflection-detector');out=root/'output/source_handover_audit_2026-10-29'
log=(out/'final_fresh_validation.log').read_text();assert '693 passed' in log and 'failed' not in log,log[-1500:]
assert (out/'read_smoke.json').exists(),'Bounded live reader check must finish first'
assert not (out/'activation.json').exists(),'Already activated'
old=json.loads((root/'output/corroboration_audit_2026-10-29/activation.json').read_text())
jobs=root/'output/process_health/jobs';previous=json.loads((jobs/'analysis.json').read_text())
(out/'analysis_before_activation.json').write_text(json.dumps(previous,indent=2))
pid=previous['pid']
p=subprocess.run(['ps','-p',str(pid),'-o','command='],capture_output=True,text=True)
if p.returncode==0:
 assert 'inflection.repair_jobs analysis' in p.stdout,p.stdout
 group=int(subprocess.check_output(['ps','-p',str(pid),'-o','pgid='],text=True).strip())
 assert group==pid,'Unexpected process group; do not interrupt other workers'
 os.killpg(group,signal.SIGTERM)
# Let interrupted transactions roll back and source/verifier locks release before resuming.
with psycopg.connect('postgresql:///inflection',autocommit=True) as c:
 for _ in range(100):
  available=c.execute('SELECT pg_try_advisory_lock(20261029,5),pg_try_advisory_lock(20261029,101)').fetchone()
  c.execute('SELECT pg_advisory_unlock_all()')
  if all(available):break
  time.sleep(.1)
 else:raise RuntimeError('Analysis checkpoint locks still held; do not duplicate the worker')
previous.update(state='STOPPED',stage='Resume after completed source-reading handover safeguards')
(jobs/'analysis.json').write_text(json.dumps(previous,indent=2))
pid=old['dashboard_pid']
p=subprocess.check_output(['ps','-p',str(pid),'-o','command='],text=True)
assert 'inflection-jobs/ui/app.py' in p,p
os.kill(pid,signal.SIGTERM)
for _ in range(50):
 p=subprocess.run(['ps','-p',str(pid),'-o','stat='],capture_output=True,text=True)
 if p.returncode or p.stdout.strip().startswith('Z'):break
 time.sleep(.1)
else:raise RuntimeError('Backend did not stop')
env=dict(os.environ,INFLECTION_DSN='postgresql:///inflection',INFLECTION_VERIFY_MODEL='local-clf-1')
app=Path.home()/'inflection-jobs/ui/app.py'
with (root/'output/process_health/dashboard_runtime.log').open('ab') as f:
 backend=subprocess.Popen([sys.executable,str(app)],cwd=app.parent,env=env,stdin=subprocess.DEVNULL,stdout=f,stderr=f,start_new_session=True)
for _ in range(30):
 try:
  with urllib.request.urlopen('http://127.0.0.1:8765/',timeout=2) as r:assert r.status==200;break
 except OSError:time.sleep(.2)
else:raise RuntimeError('Backend health check failed')
with (jobs/'analysis.log').open('ab') as f:
 worker=subprocess.Popen([sys.executable,'-u','-m','inflection.repair_jobs','analysis','--from','2024-10-29','--to','2026-10-29'],
  cwd=root,env=env,stdin=subprocess.DEVNULL,stdout=f,stderr=f,start_new_session=True)
record=dict(activated_at=datetime.now(timezone.utc).isoformat(),financial_rules='financial-10',commercial_rules='commercial-25',
            tests='693 passed',packet_version='triage-packet-12',screen_version='local-screen-10',replay_version='replay-4',audit_version='detection-audit-5',backend_http=200,dashboard_pid=backend.pid,analysis_pid=worker.pid,
            source_workers_restarted=False,archive_budget_changed=False)
(out/'activation.json').write_text(json.dumps(record,indent=2))
manifest_path=root/'output/process_health/backend_hardening/active_workers.json'
manifest=json.loads(manifest_path.read_text());manifest['analysis'].update(pid=worker.pid,state='RUNNING')
manifest['updated_at']=record['activated_at'];manifest_path.write_text(json.dumps(manifest,indent=2))
print(json.dumps(record,indent=2))
