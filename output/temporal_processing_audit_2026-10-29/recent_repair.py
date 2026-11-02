"""One bounded run for recent filings across all companies; no recurring schedule."""
import os,json,subprocess,sys
from datetime import datetime,timedelta
from pathlib import Path
from inflection.asof import IST
from inflection.coverage_repair import write_progress
from inflection.process_health import read_worker_status
root=Path.cwd();out=root/'output/temporal_processing_audit_2026-10-29';jobs=root/'output/process_health/jobs'
today=datetime.now(IST).date();first=today-timedelta(days=2)
status=jobs/'attachments.json'
old=read_worker_status(status)
if old.get('state') in ('RUNNING','STARTING'):raise RuntimeError('Existing attachment repair is active; leave it running')
(out/'previous_attachments.json').write_text(json.dumps(old,indent=2))
report=dict(task='attachments',state='RUNNING',pid=os.getpid(),first=str(first),last=str(today),
            stage='Refresh recent listing windows before bounded attachment repair',archive_bytes_added=0,
            budget_mb=256,started_at=datetime.now(IST).isoformat())
write_progress(status,report)
env=dict(os.environ,INFLECTION_DSN='postgresql:///inflection',INFLECTION_VERIFY_MODEL='local-clf-1')
try:
    listings=[]
    for exchange,segment in [('nse','equities'),('nse','sme'),('bse',None)]:
        command=[sys.executable,'-u','-m','inflection.ingest',exchange,str(first),'--to',str(today),'--interval','3']
        if segment:command+=['--segment',segment]
        r=subprocess.run(command,cwd=root,env=env,timeout=600)
        listings.append(dict(exchange=exchange,segment=segment,exit_code=r.returncode))
    (out/'recent_listings.json').write_text(json.dumps(listings,indent=2))
    log=(jobs/'attachments.log').open('ab')
    p=subprocess.Popen([sys.executable,'-u','-m','inflection.repair_jobs','attachments','--from',str(first),
        '--to',str(today),'--budget-mb','256'],cwd=root,env=env,stdout=log,stderr=log,
        stdin=subprocess.DEVNULL,start_new_session=True)
    manifest=root/'output/process_health/backend_hardening/active_workers.json'
    m=json.loads(manifest.read_text());m['attachments'].update(pid=p.pid,state='RUNNING',cached_only=False,
         first=str(first),last=str(today),budget_mb=256)
    financial=read_worker_status(jobs/'financials.json');m['financials']['state']=financial['state']
    m['updated_at']=datetime.now(IST).isoformat();write_progress(manifest,m)
    write_progress(out/'recent_repair.json',dict(listings=listings,attachment_pid=p.pid,
        first=str(first),last=str(today),budget_mb=256))
    print('Recent attachment repair started:',p.pid,flush=True)
except BaseException as exc:
    report.update(state='FAILED',error=str(exc));write_progress(status,report);raise
