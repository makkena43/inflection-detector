from pathlib import Path
from datetime import datetime,timezone
import hashlib,json,os,signal,shutil,subprocess,sys,time,urllib.request
import psycopg
root=Path('/Users/makkenasrinivas/PycharmProjects/inflection-detector');out=root/'output/packet_process_audit_2026-10-30'
log=(out/'final_import_validation.log').read_text();assert '730 passed' in log and 'failed' not in log,log[-1500:]
assert len(json.loads((out/'read_smoke.json').read_text()))==3
assert not (out/'activation.json').exists(),'Already activated'
assert shutil.disk_usage(root).free>8*1024**3,'Free-space reserve reached'
jobs=root/'output/process_health/jobs';before={t:json.loads((jobs/f'{t}.json').read_text()) for t in ('attachments','financials','ocr','analysis')}
(out/'workers_before_activation.json').write_text(json.dumps(before,indent=2))
pid=before['analysis']['pid'];p=subprocess.run(['ps','-p',str(pid),'-o','command='],capture_output=True,text=True)
if p.returncode==0:
 assert 'inflection.repair_jobs analysis' in p.stdout,p.stdout
 group=int(subprocess.check_output(['ps','-p',str(pid),'-o','pgid='],text=True).strip());assert group==pid
 os.killpg(group,signal.SIGTERM)
with psycopg.connect('postgresql:///inflection',autocommit=True) as c:
 for _ in range(100):
  available=c.execute('SELECT pg_try_advisory_lock(20261029,5),pg_try_advisory_lock(20261029,101)').fetchone()
  c.execute('SELECT pg_advisory_unlock_all()')
  if all(available):break
  time.sleep(.1)
 else:raise RuntimeError('Analysis locks remain held; worker not duplicated')
old=json.loads((root/'output/source_handover_audit_2026-10-29/activation.json').read_text());pid=old['dashboard_pid']
p=subprocess.check_output(['ps','-p',str(pid),'-o','command='],text=True);assert 'inflection-jobs/ui/app.py' in p,p
os.kill(pid,signal.SIGTERM)
for _ in range(50):
 p=subprocess.run(['ps','-p',str(pid),'-o','stat='],capture_output=True,text=True)
 if p.returncode or p.stdout.strip().startswith('Z'):break
 time.sleep(.1)
else:raise RuntimeError('Backend did not stop')
runtime=Path.home()/'inflection-jobs';copies=[]
for source,target in [('engine.py','engine/engine.py'),('triage_record.sh','triage_record.sh'),('triage_record_engine.sh','triage_record_engine.sh'),('triage_record_haiku.sh','triage_record_haiku.sh'),('load_reviews.py','load_reviews.py')]:
 src=root/'ops'/source;dest=runtime/target;backup=dest.with_name(dest.name+'.bak-packet-process-20261030')
 assert not backup.exists(),str(backup)
 shutil.copy2(dest,backup);shutil.copy2(src,dest)
 digest=lambda path:hashlib.sha256(path.read_bytes()).hexdigest()
 assert digest(src)==digest(dest)
 copies.append(dict(source=str(src),runtime=str(dest),backup=str(backup),sha256=digest(dest)))
env=dict(os.environ,INFLECTION_DSN='postgresql:///inflection',INFLECTION_VERIFY_MODEL='local-clf-1');app=runtime/'ui/app.py'
with (root/'output/process_health/dashboard_runtime.log').open('ab') as f:
 backend=subprocess.Popen([sys.executable,str(app)],cwd=app.parent,env=env,stdin=subprocess.DEVNULL,stdout=f,stderr=f,start_new_session=True)
for _ in range(40):
 try:
  with urllib.request.urlopen('http://127.0.0.1:8765/',timeout=2) as r:assert r.status==200;break
 except OSError:time.sleep(.2)
else:raise RuntimeError('Backend health check failed')
assert shutil.disk_usage(root).free>8*1024**3,'Free-space reserve reached before analysis'
with (jobs/'analysis.log').open('ab') as f:
 worker=subprocess.Popen([sys.executable,'-u','-m','inflection.repair_jobs','analysis','--from','2024-10-29','--to','2026-10-29'],cwd=root,env=env,stdin=subprocess.DEVNULL,stdout=f,stderr=f,start_new_session=True)
record=dict(activated_at=datetime.now(timezone.utc).isoformat(),financial_rules='financial-10',commercial_rules='commercial-25',tests='730 passed',packet_version='triage-packet-13',screen_version='local-screen-11',replay_version='replay-4',audit_version='detection-audit-6',backend_http=200,dashboard_pid=backend.pid,analysis_pid=worker.pid,source_workers_restarted=False,archive_budget_changed=False,runtime_files=copies)
(out/'activation.json').write_text(json.dumps(record,indent=2))
manifest_path=root/'output/process_health/backend_hardening/active_workers.json';manifest=json.loads(manifest_path.read_text())
for task,state in before.items():manifest[task].update(pid=state['pid'],state=state['state'])
manifest['analysis'].update(pid=worker.pid,state='RUNNING');manifest['updated_at']=record['activated_at'];manifest_path.write_text(json.dumps(manifest,indent=2))
print(json.dumps(record,indent=2))
