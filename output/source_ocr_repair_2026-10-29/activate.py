"""Activate validated OCR and start one bounded recovery campaign."""
from pathlib import Path
from datetime import datetime,timezone
import hashlib,json,os,signal,subprocess,sys,time,urllib.request
root=Path('/Users/makkenasrinivas/PycharmProjects/inflection-detector');out=root/'output/source_ocr_repair_2026-10-29'
log=(out/'final_validation.log').read_text();assert '663 passed' in log and 'failed' not in log,log[-1800:]
assert not (out/'activation.json').exists(),'Already activated; inspect before launching duplicate workers'
jobs=root/'output/process_health/jobs';previous=json.loads((jobs/'analysis.json').read_text())
(out/'analysis_before_activation.json').write_text(json.dumps(previous,indent=2))
old_backend=json.loads((root/'output/decision_boundary_audit_2026-10-29/activation.json').read_text())['dashboard_pid']

def stop(pid,expected):
    p=subprocess.run(['ps','-p',str(pid),'-o','command='],capture_output=True,text=True)
    if p.returncode:return
    assert expected in p.stdout,p.stdout
    os.kill(pid,signal.SIGTERM)
    for _ in range(100):
        p=subprocess.run(['ps','-p',str(pid),'-o','stat='],capture_output=True,text=True)
        if p.returncode or p.stdout.strip().startswith('Z'):return
        time.sleep(.1)
    raise RuntimeError('Worker has not stopped; do not duplicate it')

stop(previous['pid'],'inflection.repair_jobs analysis')
previous.update(state='STOPPED',stage='Restarted under OCR quality safeguards')
(jobs/'analysis.json').write_text(json.dumps(previous,indent=2))
stop(old_backend,'inflection-jobs/ui/app.py')
env=dict(os.environ,INFLECTION_DSN='postgresql:///inflection',INFLECTION_VERIFY_MODEL='local-clf-1')
manifest={}
def launch(name,args,log):
    log=Path(log)
    with log.open('ab') as stream:
        p=subprocess.Popen([sys.executable,'-u',*args],cwd=root,env=env,stdin=subprocess.DEVNULL,
                           stdout=stream,stderr=stream,start_new_session=True)
    manifest[name]=dict(pid=p.pid,log=str(log));return p.pid

app=Path.home()/'inflection-jobs/ui/app.py'
backend=launch('backend',[str(app)],root/'output/process_health/dashboard_runtime.log')
for _ in range(30):
    try:
        with urllib.request.urlopen('http://127.0.0.1:8765/',timeout=2) as r:
            assert r.status==200;break
    except OSError:time.sleep(.2)
else:raise RuntimeError('Backend health check failed')
for name,source,segment,first,last in [
    ('bse_listings','bse','equity','2024-10-29','2026-10-28'),
    ('nse_main_listings','nse','equities','2026-10-26','2026-10-28'),
    ('nse_sme_listings','nse','sme','2025-04-01','2026-10-28')]:
    target=out/name;target.mkdir(exist_ok=True)
    launch(name,['-m','inflection.coverage_repair','--source',source,'--segment',segment,
                '--from',first,'--to',last,'--output',str(target)],target/'worker.log')
# Exactly one 512 MiB raw-data allowance for this campaign, split between workers.
for task,budget,first,last in [('attachments',256,'2026-08-01','2026-10-29'),
                              ('financials',128,'2024-10-29','2026-10-29'),
                              ('ocr',128,'2024-10-29','2026-10-29')]:
    launch(task,['-m','inflection.repair_jobs',task,'--from',first,'--to',last,'--budget-mb',str(budget)],jobs/(task+'.log'))
# Ensure every producer has written its new checkpoint before the consumer snapshots them.
for _ in range(100):
    ready=True
    for task in ('attachments','financials','ocr'):
        try:state=json.loads((jobs/(task+'.json')).read_text())
        except (OSError,ValueError):ready=False;continue
        if state.get('pid')!=manifest[task]['pid']:ready=False
    if ready:break
    time.sleep(.1)
else:raise RuntimeError('Producer checkpoint initialization did not finish')
launch('analysis',['-m','inflection.repair_jobs','analysis','--from','2024-10-29','--to','2026-10-29'],jobs/'analysis.log')
record=dict(activated_at=datetime.now(timezone.utc).isoformat(),workers=manifest,tests='663 passed',
    raw_archive_allowance_mib=512,free_space_reserve_gib=8,commercial_rules='commercial-25',financial_rules='financial-8',
    packet_version='triage-packet-11',screen_version='local-screen-9',backend_http=200,
    ocr_runtime=json.loads((root/'output/process_health/ocr_runtime.json').read_text()))
(out/'activation.json').write_text(json.dumps(record,indent=2))
manifest_path=root/'output/process_health/backend_hardening/active_workers.json'
active=json.loads(manifest_path.read_text())
for task in ('attachments','financials','ocr','analysis'):
    active[task]=dict(manifest[task],state='RUNNING',first='2026-08-01' if task=='attachments' else '2024-10-29',last='2026-10-29',cached_only=False)
    if task!='analysis':active[task]['budget_mb']=256 if task=='attachments' else 128
active['updated_at']=record['activated_at'];manifest_path.write_text(json.dumps(active,indent=2))
print(json.dumps(record,indent=2))
