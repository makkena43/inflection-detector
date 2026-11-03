import os,signal,shutil,hashlib,json,subprocess,time
from pathlib import Path
from datetime import datetime,timezone
root=Path.cwd(); out=root/'output/orderbook_processing_audit_2026-10-29'
runtime=Path.home()/'inflection-jobs/engine/engine.py'
backup=runtime.with_name('engine.py.bak-orderbook-processing-20261029')
if not backup.exists():shutil.copy2(runtime,backup)
shutil.copy2(root/'ops/engine.py',runtime)
assert runtime.read_bytes()==(root/'ops/engine.py').read_bytes()
report=dict(engine_sha256=hashlib.sha256(runtime.read_bytes()).hexdigest(),backup=str(backup))
status=root/'output/process_health/jobs/analysis.json'
report['previous_analysis']=json.loads(status.read_text())
pid=report['previous_analysis']['pid']
cmd=subprocess.check_output(['ps','-p',str(pid),'-o','command='],text=True)
assert 'inflection.repair_jobs analysis' in cmd
assert os.getpgid(pid)==pid
os.killpg(pid,signal.SIGTERM)
# Backend restart loads shared readers without editing the dashboard or opening it.
pid=70311
cmd=subprocess.check_output(['ps','-p',str(pid),'-o','command='],text=True)
assert '/inflection-jobs/ui/app.py' in cmd
os.kill(pid,signal.SIGTERM)
time.sleep(2)
log=(root/'output/process_health/dashboard_runtime.log').open('ab')
p=subprocess.Popen([str(root/'.venv/bin/python'),str(Path.home()/'inflection-jobs/ui/app.py')],cwd=root,stdout=log,stderr=log,stdin=subprocess.DEVNULL,start_new_session=True,env=dict(os.environ,INFLECTION_DSN='postgresql:///inflection'))
report['dashboard_pid']=p.pid
(out/'activation.json').write_text(json.dumps(report,indent=2))
print(json.dumps(dict(engine_sha256=report['engine_sha256'],dashboard_pid=p.pid,analysis_stopped=report['previous_analysis']['pid'])))
