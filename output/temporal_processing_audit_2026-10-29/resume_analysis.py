import json,os,subprocess
from pathlib import Path
from datetime import datetime,timezone
import psycopg
root=Path.cwd();out=root/'output/temporal_processing_audit_2026-10-29'
with psycopg.connect('postgresql:///inflection',autocommit=True) as c:
    assert c.execute('SELECT pg_try_advisory_lock(20261029,5)').fetchone()[0], 'Previous analysis session still releasing its lock'
log=(root/'output/process_health/jobs/analysis.log').open('ab')
p=subprocess.Popen([str(root/'.venv/bin/python'),'-u','-m','inflection.repair_jobs','analysis','--from','2024-10-29','--to','2026-10-29'],cwd=root,env=dict(os.environ,INFLECTION_DSN='postgresql:///inflection',INFLECTION_VERIFY_MODEL='local-clf-1'),stdout=log,stderr=log,stdin=subprocess.DEVNULL,start_new_session=True)
manifest=root/'output/process_health/backend_hardening/active_workers.json'
m=json.loads(manifest.read_text());m['analysis'].update(pid=p.pid,state='RUNNING');m['updated_at']=datetime.now(timezone.utc).isoformat();manifest.write_text(json.dumps(m,indent=2)+'\n')
a=json.loads((out/'activation.json').read_text());a['analysis_pid']=p.pid;(out/'activation.json').write_text(json.dumps(a,indent=2))
print('Resumed analysis:',p.pid)
