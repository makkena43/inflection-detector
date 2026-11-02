"""Owner-authorized removal of unused superseded packet payloads.

Keep latest packets, all recorded decision evidence, replay packets, identities,
hashes and version links. PostgreSQL VACUUM makes old payload space reusable.
"""
from __future__ import annotations
import argparse,json,os,time
from pathlib import Path
from datetime import datetime,timezone
import psycopg
from .packet_rebuild import storage_guard
from .timing_audit import save

ROOT=Path(__file__).resolve().parents[2]
JOB=ROOT/'output/process_health/jobs/packet_retention'
REASON='OWNER_REQUESTED_OLD_PACKET_REMOVAL'


def batch(conn,limit=100,packet_ids=None):
    if not 1<=limit<=1000:raise ValueError('Retention batch must be between 1 and 1000')
    if packet_ids==[]:return []
    receipts=[]
    with conn.transaction():
        conn.execute("SELECT set_config('inflection.packet_retention','owner_authorized',true)")
        rows=conn.execute('''SELECT p.packet_id,p.content_hash,pg_column_size(p.content)+pg_column_size(p.markdown)
            FROM triage_packets p WHERE packet_payload_retirable(p)
            AND (%s::uuid[] IS NULL OR p.packet_id=ANY(%s::uuid[]))
            ORDER BY p.created_at,p.packet_id FOR UPDATE OF p SKIP LOCKED LIMIT %s''',(packet_ids,packet_ids,limit),prepare=False).fetchall()
        for pid,digest,size in rows:
            # Recheck after taking the exclusive row lock; decision writers use
            # key-share locks, so already-bound evidence cannot be compacted.
            at=datetime.now(timezone.utc)
            row=conn.execute('''UPDATE triage_packets p SET payload_purged_at=%s::timestamptz,markdown='',completeness='MINIMAL',
                content=retired_packet_content(p.content,p.content_hash,%s::timestamptz)
                WHERE p.packet_id=%s AND packet_payload_retirable(p)
                RETURNING payload_purged_at,pg_column_size(content)+pg_column_size(markdown)''',(at,at,pid)).fetchone()
            if row is None:continue
            at,retained=row
            conn.execute('''INSERT INTO packet_payload_purges(packet_id,content_hash,original_payload_bytes,
                retained_payload_bytes,purged_at,reason) VALUES(%s,%s,%s,%s,%s,%s)''',
                (pid,digest,size,retained,at,REASON))
            receipts.append(dict(packet_id=str(pid),original_payload_bytes=size,retained_payload_bytes=retained))
    return receipts


def register_completed_weeks(conn,quality_job=ROOT/'output/process_health/jobs/quality_repair',run_tag=None):
    """Only proven completed reconstruction weeks; active weeks stay intact."""
    path=Path(quality_job)/'stages.jsonl'
    if not path.exists():return 0
    rows=[]
    for line in path.read_text().splitlines():
        key=json.loads(line).get('key','')
        if not key.startswith('week/'):continue
        _,cohort,week=key.split('/')
        if cohort not in ('recent','archive'):raise ValueError('Unexpected repair cohort')
        if run_tag is None:
            # the paused quality-repair-1 job wrote quality-20261030-*; every other job uses the current tag
            from .quality_repair import RUN_TAG
            legacy=Path(quality_job).resolve()==(ROOT/'output/process_health/jobs/quality_repair').resolve()
            run_tag='quality-20261030' if legacy else RUN_TAG
        rows.append((week,run_tag+'-'+cohort))
    count=0
    for week,tag in rows:
        count+=conn.execute('''INSERT INTO packet_retention_completed_shortlists(shortlist_id,week_start,run_tag)
            SELECT shortlist_id,week_start,run_tag FROM triage_shortlists
            WHERE week_start=%s::date AND run_tag=%s AND mode='PUBLIC_INFORMATION_RECONSTRUCTION'
            ON CONFLICT DO NOTHING''',(week,tag)).rowcount
    return count


def run(conn,job=JOB,apply=False,quality_job=ROOT/'output/process_health/jobs/quality_repair'):
    job=Path(job);job.mkdir(parents=True,exist_ok=True)
    if not conn.execute("SELECT pg_try_advisory_lock(hashtextextended('packet-retention',0))").fetchone()[0]:
        raise RuntimeError('Packet retention is already active')
    state=dict(state='RUNNING',pid=os.getpid(),apply=apply,removed_payloads=0,reusable_payload_bytes=0)
    def report(**values):
        state.update(values,updated_at=datetime.now(timezone.utc).isoformat());save(state,job/'status.json')
    try:
        if apply:report(completed_weeks_registered=register_completed_weeks(conn,quality_job))
        report(stage='Identify obsolete unreferenced packet payloads')
        targets=conn.execute('''SELECT p.packet_id,pg_column_size(p.content)+pg_column_size(p.markdown)
            FROM triage_packets p WHERE packet_payload_retirable(p)
            ORDER BY p.created_at,p.packet_id''',prepare=False).fetchall()
        report(eligible_packets=len(targets),eligible_payload_bytes=sum(r[1] for r in targets))
        if not apply:report(state='PREVIEW');return state
        for start in range(0,len(targets),100):
            storage_guard()
            report(stage='Remove obsolete packet contents; preserve decision evidence',target_position=start)
            rows=batch(conn,packet_ids=[r[0] for r in targets[start:start+100]])
            with (job/'receipts.jsonl').open('a') as f:
                for row in rows:f.write(json.dumps(row)+'\n')
            report(stage='Remove obsolete packet contents; preserve decision evidence',
                   removed_payloads=state['removed_payloads']+len(rows),
                   reusable_payload_bytes=state['reusable_payload_bytes']+sum(r['original_payload_bytes']-r['retained_payload_bytes'] for r in rows))
            time.sleep(.05)
        report(stage='Vacuum obsolete payload space for reuse')
        conn.execute('VACUUM (ANALYZE) triage_packets')
        report(state='COMPLETE',stage='Obsolete payloads removed; PostgreSQL space reusable')
    except Exception as exc:
        if state['removed_payloads']:
            try:conn.execute('VACUUM (ANALYZE) triage_packets')
            except Exception:pass
        report(state='STORAGE_LIMIT' if str(exc).startswith('STORAGE_LIMIT') else 'FAILED',error=str(exc));raise
    finally:conn.execute("SELECT pg_advisory_unlock(hashtextextended('packet-retention',0))")
    return state


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--apply',action='store_true')
    ap.add_argument('--job',type=Path,default=JOB);args=ap.parse_args()
    with psycopg.connect(os.environ.get('INFLECTION_DSN','postgresql:///inflection'),autocommit=True) as conn:
        conn.execute("SET statement_timeout='120s'");conn.execute("SET lock_timeout='5s'")
        print(json.dumps(run(conn,args.job,args.apply),indent=2),flush=True)

if __name__=='__main__':main()
