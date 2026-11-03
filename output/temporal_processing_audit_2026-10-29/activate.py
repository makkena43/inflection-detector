import os,json,hashlib,shutil,signal,subprocess,time
from pathlib import Path
from datetime import datetime,timezone
import psycopg
root=Path.cwd();out=root/'output/temporal_processing_audit_2026-10-29'
c=psycopg.connect('postgresql:///inflection',autocommit=True)
migration='0029_supplementary_timing'
report=dict(started_at=datetime.now(timezone.utc).isoformat())
if not c.execute('SELECT 1 FROM schema_migrations WHERE version=%s',(migration,)).fetchone():
 c.execute("SET lock_timeout='10s'")
 c.execute((root/'db/migrations/0029_supplementary_timing.sql').read_text())
report['migration']=migration
report['history_counts']=dict(c.execute('SELECT source_table,count(*) FROM supplementary_versions GROUP BY source_table').fetchall())
report['history_started_at']=str(c.execute('SELECT min(observed_at) FROM supplementary_versions').fetchone()[0])
runtime=Path.home()/'inflection-jobs/engine/engine.py'
backup=runtime.with_name('engine.py.bak-temporal-processing-20261029')
if not backup.exists():shutil.copy2(runtime,backup)
shutil.copy2(root/'ops/engine.py',runtime)
assert runtime.read_bytes()==(root/'ops/engine.py').read_bytes()
report['engine_sha256']=hashlib.sha256(runtime.read_bytes()).hexdigest();report['backup']=str(backup)
status=root/'output/process_health/jobs/analysis.json'
previous=json.loads(status.read_text());report['previous_analysis']=previous
pid=previous['pid'];cmd=subprocess.check_output(['ps','-p',str(pid),'-o','command='],text=True)
assert 'inflection.repair_jobs analysis' in cmd and os.getpgid(pid)==pid
os.killpg(pid,signal.SIGTERM)
pid=52351;cmd=subprocess.check_output(['ps','-p',str(pid),'-o','command='],text=True)
assert '/inflection-jobs/ui/app.py' in cmd
os.kill(pid,signal.SIGTERM);time.sleep(2)
env=dict(os.environ,INFLECTION_DSN='postgresql:///inflection',INFLECTION_VERIFY_MODEL='local-clf-1')
log=(root/'output/process_health/dashboard_runtime.log').open('ab')
p=subprocess.Popen([str(root/'.venv/bin/python'),str(Path.home()/'inflection-jobs/ui/app.py')],cwd=root,env=env,stdin=subprocess.DEVNULL,stdout=log,stderr=log,start_new_session=True)
report['dashboard_pid']=p.pid
(out/'activation.json').write_text(json.dumps(report,indent=2))
print(json.dumps({k:v for k,v in report.items() if k!='previous_analysis'},indent=2))
