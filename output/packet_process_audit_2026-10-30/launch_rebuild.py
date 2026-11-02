from pathlib import Path
from datetime import datetime,timezone
import json,os,shutil,subprocess,sys
import psycopg
from inflection.packets import pipeline as P
root=Path.cwd();out=root/'output/packet_process_audit_2026-10-30';job=root/'output/process_health/jobs/packet_rebuild'
check=[]
with psycopg.connect('postgresql:///inflection',autocommit=True) as c:
 for sample in json.loads((out/'rebuild_sample_before.json').read_text()):
  t=sample['target'];after=c.execute('SELECT to_jsonb(i) FROM triage_shortlist_items i WHERE shortlist_id=%s AND issuer_id=%s',(t['shortlist_id'],t['issuer_id'])).fetchone()[0]
  assert after==sample['shortlist_item'],'Original shortlist or decision changed'
  row=P._latest(c,t['shortlist_id'],t['issuer_id']);p=row[2]
  assert p['manifest']['packet_version']=='triage-packet-13'
  assert str(c.execute('SELECT supersedes_id FROM triage_packets WHERE packet_id=%s',(row[0],)).fetchone()[0])==t['packet_id']
  assert datetime.fromisoformat(p['manifest']['cutoff'].replace('Z','+00:00'))==datetime.fromisoformat(t['cutoff'])
  check.append(dict(original_packet_id=t['packet_id'],new_packet_id=str(row[0]),decision_unchanged=True,
    packet_version=p['manifest']['packet_version'],completeness=p['manifest']['completeness'],nomination_issues=p['manifest'].get('nomination_issues')))
(out/'rebuild_sample_verified.json').write_text(json.dumps(check,indent=2))
assert shutil.disk_usage(root).free>8*1024**3+64*1024**2
assert json.loads((job/'status.json').read_text())['state']=='PAUSED'
assert not (out/'rebuild_launch.json').exists()
env=dict(os.environ,INFLECTION_DSN='postgresql:///inflection')
with (job/'worker.log').open('ab') as f:
 worker=subprocess.Popen([sys.executable,'-u','-m','inflection.packet_rebuild'],cwd=root,env=env,stdin=subprocess.DEVNULL,stdout=f,stderr=f,start_new_session=True)
record=dict(started_at=datetime.now(timezone.utc).isoformat(),pid=worker.pid,total=43807,initial_sample_updated=3,
 job=str(job),source_downloads=False,archive_budgets_changed=False,free_space_reserve_gib=8,tests='42 passed')
(out/'rebuild_launch.json').write_text(json.dumps(record,indent=2))
manifest_path=root/'output/process_health/backend_hardening/active_workers.json';manifest=json.loads(manifest_path.read_text())
manifest['packet_rebuild']=dict(pid=worker.pid,state='RUNNING',log=str(job/'worker.log'),status=str(job/'status.json'),cached_only=True)
manifest['updated_at']=record['started_at'];manifest_path.write_text(json.dumps(manifest,indent=2))
print(json.dumps(dict(sample_verified=check,launch=record),indent=2))
