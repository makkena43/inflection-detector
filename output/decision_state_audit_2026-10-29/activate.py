import os,json,shutil,subprocess,signal,time,hashlib
from pathlib import Path
from datetime import datetime,timezone
import psycopg
root=Path.cwd();out=root/'output/decision_state_audit_2026-10-29'
report=dict(started_at=datetime.now(timezone.utc).isoformat())
with psycopg.connect('postgresql:///inflection',autocommit=True) as c:
 c.execute("SET lock_timeout='10s'")
 version='0030_financial_checkpoint_history'
 if not c.execute('SELECT 1 FROM schema_migrations WHERE version=%s',(version,)).fetchone():
  c.execute((root/'db/migrations/0030_financial_checkpoint_history.sql').read_text())
 report['migration']=version
 report['financial_checkpoint_versions']=c.execute("SELECT count(*) FROM supplementary_versions WHERE source_table='financial_scans'").fetchone()[0]
runtime=Path.home()/'inflection-jobs/engine/engine.py';backup=runtime.with_name('engine.py.bak-decision-state-20261029')
if not backup.exists():shutil.copy2(runtime,backup)
shutil.copy2(root/'ops/engine.py',runtime)
assert runtime.read_bytes()==(root/'ops/engine.py').read_bytes()
report['engine_sha256']=hashlib.sha256(runtime.read_bytes()).hexdigest();report['backup']=str(backup)
previous=json.loads((root/'output/temporal_processing_audit_2026-10-29/activation.json').read_text())
pid=previous['dashboard_pid'];cmd=subprocess.check_output(['ps','-p',str(pid),'-o','command='],text=True)
assert '/inflection-jobs/ui/app.py' in cmd
os.kill(pid,signal.SIGTERM);time.sleep(2)
log=(root/'output/process_health/dashboard_runtime.log').open('ab')
p=subprocess.Popen([str(root/'.venv/bin/python'),str(Path.home()/'inflection-jobs/ui/app.py')],cwd=root,
 env=dict(os.environ,INFLECTION_DSN='postgresql:///inflection'),stdin=subprocess.DEVNULL,stdout=log,stderr=log,start_new_session=True)
report['dashboard_pid']=p.pid
report['native_ocr_version']='apple-vision-2';report['native_ocr_backend']='UNAVAILABLE_ON_TEST_SOURCE_EVEN_WITH_CPU_FALLBACK'
(out/'activation.json').write_text(json.dumps(report,indent=2))
print(json.dumps(report,indent=2))
