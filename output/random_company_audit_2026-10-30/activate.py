from pathlib import Path
from datetime import datetime,timezone
import json,os,signal,subprocess,sys,time,urllib.request
root=Path.cwd();out=root/'output/random_company_audit_2026-10-30'
assert '751 passed' in (out/'activation_validation.log').read_text();assert not (out/'activation.json').exists()
# Move the remaining finite source refresh to a detached, resumable worker.
report=json.loads((out/'source_repair_status.json').read_text());source_worker=None
if report['state']=='RUNNING':
 processes=subprocess.check_output(['ps','-axo','pid=,command='],text=True).splitlines()
 matches=[line.strip().split(None,1) for line in processes if line.strip().endswith(' -u output/random_company_audit_2026-10-30/repair_sources.py')]
 assert len(matches)==1,matches
 old_pid=int(matches[0][0]);os.kill(old_pid,signal.SIGTERM)
 for _ in range(80):
  with __import__('psycopg').connect('postgresql:///inflection',autocommit=True) as c:
   free=c.execute('SELECT pg_try_advisory_lock(20261029,1),pg_try_advisory_lock(20261029,5)').fetchone();c.execute('SELECT pg_advisory_unlock_all()')
  if all(free):break
  time.sleep(.1)
 else:raise RuntimeError('Source refresh locks still held')
 with (out/'repair_background.log').open('ab') as f:
  source_worker=subprocess.Popen([sys.executable,'-u','output/random_company_audit_2026-10-30/repair_sources.py'],cwd=root,
    env=dict(os.environ,INFLECTION_DSN='postgresql:///inflection'),stdin=subprocess.DEVNULL,stdout=f,stderr=f,start_new_session=True)
# Reload only the application backend; preserve the large packet rebuild.
old=json.loads((root/'output/review_consumption_audit_2026-10-30/activation.json').read_text());pid=old['dashboard_pid']
cmd=subprocess.check_output(['ps','-p',str(pid),'-o','command='],text=True);assert 'inflection-jobs/ui/app.py' in cmd,cmd
packet_status=root/'output/process_health/jobs/packet_rebuild/status.json';before=json.loads(packet_status.read_text())
os.kill(pid,signal.SIGTERM)
for _ in range(50):
 p=subprocess.run(['ps','-p',str(pid),'-o','stat='],capture_output=True,text=True)
 if p.returncode or p.stdout.strip().startswith('Z'):break
 time.sleep(.1)
else:raise RuntimeError('Backend did not stop')
app=Path.home()/'inflection-jobs/ui/app.py'
with (root/'output/process_health/dashboard_runtime.log').open('ab') as f:
 backend=subprocess.Popen([sys.executable,str(app)],cwd=app.parent,env=dict(os.environ,INFLECTION_DSN='postgresql:///inflection',INFLECTION_VERIFY_MODEL='local-clf-1'),stdin=subprocess.DEVNULL,stdout=f,stderr=f,start_new_session=True)
for _ in range(40):
 try:
  with urllib.request.urlopen('http://127.0.0.1:8765/',timeout=2) as response:assert response.status==200;break
 except OSError:time.sleep(.2)
else:raise RuntimeError('Backend health check failed')
after=json.loads(packet_status.read_text());assert after['pid']==before['pid'] and after['completed']>=before['completed']
now=datetime.now(timezone.utc).isoformat()
record=dict(activated_at=now,tests='751 passed',financial_parser='nse-results-xbrl-2',dashboard_pid=backend.pid,backend_http=200,
  source_refresh_pid=source_worker.pid if source_worker else None,packet_worker_restarted=False,packet_worker_pid=after['pid'],packet_worker_completed=after['completed'],archive_budgets_changed=False,old_decisions_modified=False)
(out/'activation.json').write_text(json.dumps(record,indent=2))
manifest_path=root/'output/process_health/backend_hardening/active_workers.json';m=json.loads(manifest_path.read_text())
if source_worker:m['financial_parser_refresh']=dict(pid=source_worker.pid,state='RUNNING',cached_only=True,status=str(out/'source_repair_status.json'),log=str(out/'repair_background.log'))
m['updated_at']=now;manifest_path.write_text(json.dumps(m,indent=2));print(json.dumps(record,indent=2))
