"""Resumable append-only rebuild of packets affected by packet-process fixes.

Uses local data only; retains original shortlist decisions and packet history.
"""
from __future__ import annotations
import argparse
from collections import Counter
from datetime import datetime,timezone
import json
import os
from pathlib import Path
import shutil
import time

import psycopg
from .packets import pipeline as P,contents as C
from .coverage_repair import write_progress
from .queue import LABEL
from .financial.pipeline import _SYMBOL

ROOT=Path(__file__).resolve().parents[2]
DEFAULT_JOB=ROOT/'output/process_health/jobs/packet_rebuild'
RESERVE=8*1024**3


def targets(conn):
    # Leaf selection preserves the deployed history; lock and recheck each head
    # again before publishing, since another repair may finish in the meantime.
    return [dict(packet_id=str(pid),shortlist_id=str(sid),issuer_id=str(issuer),
                 cutoff=cutoff.isoformat(),run_tag=tag,mode=mode)
        for pid,sid,issuer,cutoff,tag,mode in conn.execute('''
        SELECT p.packet_id,p.shortlist_id,p.issuer_id,p.cutoff,s.run_tag,p.mode
        FROM triage_packets p JOIN triage_shortlists s USING(shortlist_id)
        WHERE p.packet_version<>%s AND NOT EXISTS (
          SELECT 1 FROM triage_packets child WHERE child.supersedes_id=p.packet_id
          AND child.shortlist_id=p.shortlist_id AND child.issuer_id=p.issuer_id)
        ORDER BY p.cutoff DESC,s.run_tag,p.issuer_id''',(C.PACKET_VERSION,)).fetchall()]


def rebuild(conn,target,guard=lambda:None):
    sid=target['shortlist_id'];issuer=target['issuer_id']
    with P.packet_snapshot(conn,sid,issuer):
        latest=P._latest(conn,sid,issuer)
        if latest is None:raise ValueError('Original packet is unavailable')
        old=latest[2];manifest=old['manifest']
        if manifest.get('mode')=='ACTUAL_SYSTEM_REPLAY':
            return dict(status='PENDING',reason='Actual-system replay remains frozen; needs a separate reconstruction run')
        if manifest.get('packet_version')==C.PACKET_VERSION:
            return dict(status='ALREADY_CURRENT',packet_id=str(latest[0]))
        row=conn.execute(f'''SELECT s.shortlist_id,s.week_start,s.cutoff,s.mode,s.policy_version,s.policy->>'hash',
              i.issuer_id,i.slot,i.position,i.priority_class,i.corroborated,i.waiting_since,i.stale,i.reason,i.note,
              i.evaluation_ids,i.trigger_event_version_ids,{LABEL.format(col='i.issuer_id')},iss.legal_name,
              {_SYMBOL.format(col='i.issuer_id')} IS NOT NULL
            FROM triage_shortlists s JOIN triage_shortlist_items i USING(shortlist_id)
            JOIN issuers iss USING(issuer_id) WHERE i.shortlist_id=%s AND i.issuer_id=%s''',(sid,issuer)).fetchone()
        if row is None:raise ValueError('Original shortlist item is unavailable')
        keys=('shortlist_id','week_start','cutoff','mode','policy_version','policy_hash','issuer_id','slot','position',
              'priority','corroborated','waiting_since','stale','reason','note','evaluation_ids',
              'trigger_event_version_ids','label','name','has_symbol')
        it=dict(zip(keys,row))
        if manifest.get('repair'):
            # A source-repaired packet may already carry corrected references.
            # Do not replace those with obsolete nominations from its shortlist.
            it['evaluation_ids']=manifest['evaluation_ids']
            it['trigger_event_version_ids']=[e['version_id'] for e in old.get('events',[]) if e.get('version_id')]
            it['reason']=old.get('why_now',{}).get('reason',it['reason'])
        previous_tag=os.environ.get('INFLECTION_RUN_TAG')
        try:
            os.environ['INFLECTION_RUN_TAG']=target['run_tag']
            content,_=P.packet_for(conn,it,int(manifest.get('token_budget') or C.TOKEN_BUDGET))
        finally:
            if previous_tag is None:os.environ.pop('INFLECTION_RUN_TAG',None)
            else:os.environ['INFLECTION_RUN_TAG']=previous_tag
        # The original decision context is frozen, including inherited run history.
        content['why_now']['prior_triage']=old.get('why_now',{}).get('prior_triage')
        if manifest.get('repair'):content['manifest']['repair']=manifest['repair']
        guard()  # Check again immediately before appending the rebuilt data.
        stored=P.store_packet(conn,it,content,int(manifest.get('token_budget') or C.TOKEN_BUDGET),
                              created_by='inflection.packet_rebuild')
        return dict(status=stored['status'],original_packet_id=str(latest[0]),packet_id=str(stored['packet_id']),
                    completeness=stored['content']['manifest']['completeness'],
                    nomination_issues=stored['content']['manifest'].get('nomination_issues',[]),
                    missing_evidence=stored['content']['manifest'].get('missing_evidence',[]))


def storage_reserve_bytes():
    value=int(os.environ.get('INFLECTION_REPAIR_RESERVE_GIB',str(RESERVE//1024**3)))
    if not 5<=value<=1024:raise ValueError('Repair reserve must be between 5 and 1024 GiB')
    return value*1024**3


def storage_guard(root=ROOT):
    # Leave working space for PostgreSQL WAL, temporary pages and other workers.
    reserve=storage_reserve_bytes()
    if shutil.disk_usage(root).free < reserve+64*1024**2:
        raise RuntimeError(f'STORAGE_LIMIT: {reserve//1024**3} GiB reserve plus database working allowance reached')


def run(conn,job=DEFAULT_JOB,limit=None,guard=storage_guard):
    job=Path(job);job.mkdir(parents=True,exist_ok=True)
    lock=f'packet-rebuild:{C.PACKET_VERSION}'
    if not conn.execute('SELECT pg_try_advisory_lock(hashtextextended(%s,0))',(lock,)).fetchone()[0]:
        raise RuntimeError('Packet rebuild already running')
    try:
        plan=job/'targets.json';journal=job/'results.jsonl';state_path=job/'status.json'
        if plan.exists():
            planned=json.loads(plan.read_text())
            if planned['packet_version']!=C.PACKET_VERSION:raise ValueError('Job belongs to a different packet version')
        else:
            planned=dict(packet_version=C.PACKET_VERSION,created_at=datetime.now(timezone.utc).isoformat(),targets=targets(conn))
            write_progress(plan,planned)
        results={}
        if journal.exists():
            for line in journal.read_text().splitlines():
                if line.strip():
                    item=json.loads(line);results[item['target_packet_id']]=item
        counts=Counter(r['status'] for r in results.values())
        state=dict(state='RUNNING',pid=os.getpid(),packet_version=C.PACKET_VERSION,total=len(planned['targets']),
                   completed=len(results),counts=dict(counts),archive_bytes_added=0,raw_downloads=False,
                   started_at=datetime.now(timezone.utc).isoformat(),remaining=len(planned['targets'])-len(results))
        def update(**kwargs):
            state.update(kwargs,counts=dict(counts),completed=len(results),remaining=len(planned['targets'])-len(results),
                         updated_at=datetime.now(timezone.utc).isoformat());write_progress(state_path,state)
        update();processed=0;consecutive_errors=0
        try:
            for target in planned['targets']:
                if target['packet_id'] in results:continue
                if limit is not None and processed>=limit:
                    update(state='PAUSED',stage='Requested batch limit reached');return state
                guard()
                update(current=target,stage='Rebuild original cutoff with current packet safeguards')
                try:
                    result=rebuild(conn,target,guard)
                    consecutive_errors=0
                except (ValueError,psycopg.Error) as exc:
                    result=dict(status='PENDING',reason=str(exc)[:2000]);consecutive_errors+=1
                item=dict(target_packet_id=target['packet_id'],**result)
                with journal.open('a') as f:f.write(json.dumps(item,default=str)+'\n')
                results[target['packet_id']]=item;counts[item['status']]+=1;processed+=1
                update()
                if consecutive_errors>=10:raise RuntimeError('Ten consecutive packet failures; inspect pending reasons before retrying')
                time.sleep(.02)
            gaps=sum(bool(r.get('missing_evidence')) or r['status']=='PENDING' for r in results.values())
            update(state='FINISHED_WITH_GAPS' if gaps else 'COMPLETE',packets_with_gaps=gaps,stage='Impacted packet rebuild pass finished')
        except Exception as exc:
            update(state='STORAGE_LIMIT' if str(exc).startswith('STORAGE_LIMIT') else 'FAILED',error=str(exc))
            if state['state']=='FAILED':raise
        return state
    finally:conn.execute('SELECT pg_advisory_unlock(hashtextextended(%s,0))',(lock,))


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--job',type=Path,default=DEFAULT_JOB)
    ap.add_argument('--limit',type=int);args=ap.parse_args()
    if args.limit is not None and args.limit<1:ap.error('--limit must be positive')
    if C.PACKET_VERSION!='triage-packet-13':ap.error('Use the active packet policy with valuation enabled')
    with psycopg.connect(os.environ.get('INFLECTION_DSN','postgresql:///inflection'),autocommit=True) as conn:
        conn.execute("SET statement_timeout='60s'");conn.execute("SET lock_timeout='10s'")
        print(json.dumps(run(conn,args.job,args.limit),indent=2,default=str),flush=True)

if __name__=='__main__':main()
