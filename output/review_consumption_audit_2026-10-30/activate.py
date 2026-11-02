from pathlib import Path
from datetime import datetime,timezone
import json,os,signal,subprocess,sys,time,urllib.request
root=Path.cwd();out=root/'output/review_consumption_audit_2026-10-30'
assert '743 passed' in (out/'full_validation.log').read_text()
assert not (out/'activation.json').exists()
previous=json.loads((root/'output/packet_process_audit_2026-10-30/activation.json').read_text());pid=previous['dashboard_pid']
command=subprocess.check_output(['ps','-p',str(pid),'-o','command='],text=True)
assert 'inflection-jobs/ui/app.py' in command,command
packet_job=root/'output/process_health/jobs/packet_rebuild/status.json';before=json.loads(packet_job.read_text())
os.kill(pid,signal.SIGTERM)
for _ in range(50):
 p=subprocess.run(['ps','-p',str(pid),'-o','stat='],capture_output=True,text=True)
 if p.returncode or p.stdout.strip().startswith('Z'):break
 time.sleep(.1)
else:raise RuntimeError('Backend did not stop')
app=Path.home()/'inflection-jobs/ui/app.py';env=dict(os.environ,INFLECTION_DSN='postgresql:///inflection',INFLECTION_VERIFY_MODEL='local-clf-1')
with (root/'output/process_health/dashboard_runtime.log').open('ab') as f:
 backend=subprocess.Popen([sys.executable,str(app)],cwd=app.parent,env=env,stdin=subprocess.DEVNULL,stdout=f,stderr=f,start_new_session=True)
for _ in range(40):
 try:
  with urllib.request.urlopen('http://127.0.0.1:8765/',timeout=2) as response:assert response.status==200;break
 except OSError:time.sleep(.2)
else:raise RuntimeError('Reloaded backend health check failed')
after=json.loads(packet_job.read_text());assert after['pid']==before['pid'] and after['completed']>=before['completed']
manifest_path=root/'output/process_health/backend_hardening/active_workers.json';manifest=json.loads(manifest_path.read_text())
for task in ('analysis','ocr','financials','attachments'):
 report=json.loads((root/f'output/process_health/jobs/{task}.json').read_text())
 if task in manifest:manifest[task].update(pid=report['pid'],state=report['state'])
manifest['packet_rebuild'].update(pid=after['pid'],state=after['state'])
now=datetime.now(timezone.utc).isoformat();manifest['updated_at']=now;manifest_path.write_text(json.dumps(manifest,indent=2))
record=dict(activated_at=now,dashboard_pid=backend.pid,backend_http=200,tests='743 passed',shortlist_policy='triage-2',replay_policy='replay-5',packet_version='triage-packet-13',screen_version='local-screen-11',commercial_rules='commercial-25',financial_rules='financial-10',packet_worker_restarted=False,packet_worker_pid=after['pid'],packet_worker_completed=after['completed'],raw_workers_restarted=False,archive_budgets_changed=False,existing_shortlists_mutated=False)
(out/'activation.json').write_text(json.dumps(record,indent=2));print(json.dumps(record,indent=2))
