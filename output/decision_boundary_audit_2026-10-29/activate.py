from pathlib import Path
import os,sys,json,subprocess,signal,time,urllib.request
from datetime import datetime,timezone
from inflection.triage.screen import SCREEN_VERSION
root=Path('/Users/makkenasrinivas/PycharmProjects/inflection-detector')
out=root/'output/decision_boundary_audit_2026-10-29'
log=(out/'final_validation.log').read_text()
assert '652 passed' in log and 'failed' not in log,log[-2000:]
assert SCREEN_VERSION=='local-screen-8'
previous=json.loads((root/'output/event_history_audit_2026-10-29/activation.json').read_text())
pid=previous['dashboard_pid'];app=Path.home()/'inflection-jobs/ui/app.py'
cmd=subprocess.check_output(['ps','-p',str(pid),'-o','command='],text=True)
assert str(app) in cmd,cmd
os.kill(pid,signal.SIGTERM)
for _ in range(50):
    p=subprocess.run(['ps','-p',str(pid),'-o','stat='],capture_output=True,text=True)
    if p.returncode!=0 or p.stdout.strip().startswith('Z'):break
    time.sleep(.1)
else:raise RuntimeError('Backend has not stopped')
env=dict(os.environ,INFLECTION_DSN='postgresql:///inflection',INFLECTION_VERIFY_MODEL='local-clf-1')
with (root/'output/process_health/dashboard_runtime.log').open('ab') as f:
    process=subprocess.Popen([sys.executable,str(app)],cwd=app.parent,env=env,stdin=subprocess.DEVNULL,
                             stdout=f,stderr=f,start_new_session=True)
for _ in range(30):
    try:
        with urllib.request.urlopen('http://127.0.0.1:8765/',timeout=2) as response:
            assert response.status==200;break
    except OSError:time.sleep(.2)
else:raise RuntimeError('Backend health check failed')
state=json.loads((root/'output/process_health/jobs/analysis.json').read_text())
record=dict(activated_at=datetime.now(timezone.utc).isoformat(),screen_version=SCREEN_VERSION,
            tests='652 passed',backend_http=200,dashboard_pid=process.pid,analysis=state)
(out/'activation.json').write_text(json.dumps(record,indent=2));print(json.dumps(record,indent=2))
