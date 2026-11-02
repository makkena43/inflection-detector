from pathlib import Path
import os,signal,subprocess,time,json
from datetime import datetime,timezone
import psycopg
from psycopg.types.json import Jsonb
from inflection.process_health import read_worker_status
root=Path.cwd();out=root/'output/process_health/jobs'
history=out/'history';history.mkdir(exist_ok=True)
previous={}
for task in ('financials','attachments','ocr','analysis'):
 status=read_worker_status(out/f'{task}.json');previous[task]=status
 (history/f"{task}-{status['pid']}-before-hardening.json").write_text(json.dumps(status,indent=2))
 if status['state']!='RUNNING':continue
 pid=status['pid'];command=subprocess.check_output(['ps','-p',str(pid),'-o','command='],text=True).strip()
 if f'-m inflection.repair_jobs {task} ' not in command:raise SystemExit(f'Unexpected process for {task}')
 if os.getpgid(pid)==pid:os.killpg(pid,signal.SIGTERM)
 else:os.kill(pid,signal.SIGTERM)
 print('Stopped old worker for backend update:',task,pid,flush=True)
with psycopg.connect('postgresql:///inflection',autocommit=True) as conn:
 # A terminated client can leave its current query finishing briefly. Wait for actual lock release.
 for task in previous:
  key=('references','financials','attachments','ocr','evidence','analysis').index(task)
  deadline=time.monotonic()+150
  while not conn.execute('SELECT pg_try_advisory_lock(20261029,%s)',(key,)).fetchone()[0]:
   if time.monotonic()>deadline:raise SystemExit('Previous database session still active: '+task)
   time.sleep(1)
  conn.execute('SELECT pg_advisory_unlock(20261029,%s)',(key,))
 audited=json.loads((root/'output/process_health/zip_membership_audit.json').read_text())
 corrected=[]
 for record in audited:
  if record['audit']!='ZIP_PARTIAL':continue
  with conn.transaction():
   current=conn.execute('''SELECT p.pipeline_state,p.processing_issues,v.sha256 FROM document_publications p
        JOIN document_versions v USING(document_version_id) WHERE p.publication_id=%s FOR UPDATE OF p''',
        (record['publication_id'],)).fetchone()
   if not current or current[2]!=record['sha256'] or current[0] not in ('TEXT_READY','PARTIAL_TEXT','OCR_REQUIRED'):
    continue
   if 'ZIP_INCOMPLETE' in current[1]:continue
   issues=current[1]+['ZIP_INCOMPLETE',record['note']]
   conn.execute('''UPDATE document_publications SET pipeline_state='PARTIAL_TEXT',failure_reason=NULL,
       processing_issues=%s,revision=revision+1 WHERE publication_id=%s''',(issues,record['publication_id']))
   conn.execute('''INSERT INTO audit_log(actor,actor_kind,action,target_table,target_id,details)
       VALUES('inflection.processing_integrity','SYSTEM','FLAG_UNREAD_ZIP_MEMBERS','document_publications',%s,%s)''',
       (record['publication_id'],Jsonb(dict(before_state=current[0],after_state='PARTIAL_TEXT',
          previous_issues=current[1],sha256=record['sha256'],unread_members=record['note'],
          basis='Verified archived ZIP contents'))))
   corrected.append(dict(publication_id=record['publication_id'],before=current[0],after='PARTIAL_TEXT'))
 (root/'output/process_health/backend_hardening/corrected_zip_states.json').write_text(json.dumps(corrected,indent=2))
 print('Corrected ZIP completeness records:',len(corrected),flush=True)
manifest={}
for task in ('attachments','ocr','financials','analysis'):
 log=(out/f'{task}.log').open('ab')
 command=[str(root/'.venv/bin/python'),'-u','-m','inflection.repair_jobs',task,
          '--from','2026-08-01','--to','2026-10-28','--budget-mb','1024']
 if task in ('attachments','ocr'):command.append('--cached-only')
 process=subprocess.Popen(command,cwd=root,stdin=subprocess.DEVNULL,stdout=log,stderr=log,
   env=dict(os.environ,INFLECTION_DSN='postgresql:///inflection',INFLECTION_VERIFY_MODEL='local-clf-1'),start_new_session=True)
 log.close();manifest[task]=dict(pid=process.pid,cached_only=task in ('attachments','ocr'),log=str(out/f'{task}.log'))
 print('Resumed updated worker:',task,process.pid,flush=True)
manifest['updated_at']=datetime.now(timezone.utc).isoformat()
(root/'output/process_health/backend_hardening/active_workers.json').write_text(json.dumps(manifest,indent=2))
