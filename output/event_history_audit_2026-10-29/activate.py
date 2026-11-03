from pathlib import Path
import os,sys,json,shutil,hashlib,subprocess,signal,time,urllib.request
from datetime import datetime,timezone
root=Path('/Users/makkenasrinivas/PycharmProjects/inflection-detector')
out=root/'output/event_history_audit_2026-10-29'
log=(out/'final_validation.log').read_text()
assert '639 passed' in log and 'failed' not in log,log[-3000:]
old=json.loads((root/'output/critical_input_audit_2026-10-29/activation.json').read_text())
analysis_state=json.loads((root/'output/process_health/jobs/analysis.json').read_text())
assert analysis_state['state'] not in ('RUNNING','STARTING'),analysis_state
runtime=Path.home()/'inflection-jobs/engine/engine.py'
backup=runtime.with_name(runtime.name+'.bak-event-history-20261029')
assert not backup.exists(),'Backup exists; inspect prior activation before retrying'
shutil.copy2(runtime,backup);shutil.copy2(root/'ops/engine.py',runtime)
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
assert sha(runtime)==sha(root/'ops/engine.py')
pid=old['dashboard_pid']
cmd=subprocess.check_output(['ps','-p',str(pid),'-o','command='],text=True).strip()
app=Path.home()/'inflection-jobs/ui/app.py'
assert str(app) in cmd,cmd
os.kill(pid,signal.SIGTERM)
for _ in range(50):
    result=subprocess.run(['ps','-p',str(pid),'-o','stat='],capture_output=True,text=True)
    if result.returncode!=0 or result.stdout.strip().startswith('Z'):break
    time.sleep(.1)
else:raise RuntimeError('Previous backend has not stopped')
env=dict(os.environ,INFLECTION_DSN='postgresql:///inflection',INFLECTION_VERIFY_MODEL='local-clf-1')
with (root/'output/process_health/dashboard_runtime.log').open('ab') as f:
    dashboard=subprocess.Popen([sys.executable,str(app)],cwd=app.parent,env=env,stdin=subprocess.DEVNULL,
                               stdout=f,stderr=f,start_new_session=True)
for _ in range(30):
    try:
        with urllib.request.urlopen('http://127.0.0.1:8765/',timeout=2) as response:
            assert response.status==200;break
    except OSError:time.sleep(.2)
else:raise RuntimeError('Backend health check failed')
with (root/'output/process_health/jobs/analysis.log').open('ab') as f:
    worker=subprocess.Popen([sys.executable,'-u','-m','inflection.repair_jobs','analysis','--from','2024-10-29','--to','2026-10-29'],
         cwd=root,env=env,stdin=subprocess.DEVNULL,stdout=f,stderr=f,start_new_session=True)
record=dict(activated_at=datetime.now(timezone.utc).isoformat(),commercial_rules='commercial-24',financial_rules='financial-7',
            packet_version='triage-packet-10',screen_version='local-screen-7',orderbook_series='orderbook-series-6',
            audit_version='detection-audit-4',engine_sha256=sha(runtime),backup=str(backup),dashboard_pid=dashboard.pid,
            analysis_pid=worker.pid,previous_analysis=analysis_state)
(out/'activation.json').write_text(json.dumps(record,indent=2))
manifest_path=root/'output/process_health/backend_hardening/active_workers.json'
manifest=json.loads(manifest_path.read_text())
manifest['analysis'].update(pid=worker.pid,state='RUNNING')
manifest['updated_at']=record['activated_at'];manifest_path.write_text(json.dumps(manifest,indent=2))
print(json.dumps(record,indent=2))
