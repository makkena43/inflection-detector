import os,subprocess,json,signal,shutil,hashlib,time
from datetime import datetime,timezone
from pathlib import Path
from inflection.process_health import read_worker_status
root=Path.cwd();out=root/'output/critical_input_audit_2026-10-29';jobs=root/'output/process_health/jobs'
report=dict(activated_at=datetime.now(timezone.utc).isoformat(),financial_rules='financial-6',commercial_rules='commercial-23',
 packet_version='triage-packet-9',screen_version='local-screen-6',orderbook_series='orderbook-series-5')
runtime=Path.home()/'inflection-jobs/engine/engine.py';backup=runtime.with_name('engine.py.bak-critical-inputs-20261029')
if not backup.exists():shutil.copy2(runtime,backup)
shutil.copy2(root/'ops/engine.py',runtime)
assert runtime.read_bytes()==(root/'ops/engine.py').read_bytes()
report['engine_sha256']=hashlib.sha256(runtime.read_bytes()).hexdigest();report['backup']=str(backup)
old=json.loads((root/'output/decision_state_audit_2026-10-29/activation.json').read_text())
pid=old['dashboard_pid'];cmd=subprocess.check_output(['ps','-p',str(pid),'-o','command='],text=True)
assert '/inflection-jobs/ui/app.py' in cmd
os.kill(pid,signal.SIGTERM);time.sleep(2)
env=dict(os.environ,INFLECTION_DSN='postgresql:///inflection',INFLECTION_VERIFY_MODEL='local-clf-1')
log=(root/'output/process_health/dashboard_runtime.log').open('ab')
p=subprocess.Popen([str(root/'.venv/bin/python'),str(Path.home()/'inflection-jobs/ui/app.py')],cwd=root,env=env,
 stdin=subprocess.DEVNULL,stdout=log,stderr=log,start_new_session=True)
report['dashboard_pid']=p.pid
s=read_worker_status(jobs/'analysis.json');report['previous_analysis']=s
if s['state'] not in ('RUNNING','STARTING'):
 log=(jobs/'analysis.log').open('ab')
 p=subprocess.Popen([str(root/'.venv/bin/python'),'-u','-m','inflection.repair_jobs','analysis','--from','2024-10-29','--to','2026-10-29'],
  cwd=root,env=env,stdout=log,stderr=log,stdin=subprocess.DEVNULL,start_new_session=True)
 report['analysis_pid']=p.pid
 manifest=root/'output/process_health/backend_hardening/active_workers.json';m=json.loads(manifest.read_text())
 m['analysis'].update(pid=p.pid,state='RUNNING');m['updated_at']=datetime.now(timezone.utc).isoformat();manifest.write_text(json.dumps(m,indent=2)+'\n')
else:report['analysis_pid']=s['pid']
(out/'activation.json').write_text(json.dumps(report,indent=2));print(json.dumps({k:v for k,v in report.items() if k!='previous_analysis'},indent=2))
