"""Recover purged financial originals within the original, cumulative allowance.

The owner regularly removes raw documents. Missing bytes require recovery for a
parser upgrade or fresh source verification; absence alone is not a bad figure.
"""
from __future__ import annotations
from collections import Counter
from datetime import datetime,timezone,timedelta
import argparse,hashlib,json,os,time,urllib.request
from pathlib import Path
from urllib.parse import urlsplit
import psycopg
from . import financials
from .financial import pipeline as F
from .sources.download import Archive
from .sources.xbrl import MAX_BYTES,parse_results_xbrl,listed_period
from .timing_audit import save as _save_json
from .packet_rebuild import storage_guard

ROOT=Path(__file__).resolve().parents[2]
JOB=ROOT/'output/process_health/jobs/financial_source_recovery'
LEDGER=ROOT/'output/process_health/jobs/financials.json'
BUDGET=128*1024**2


def write_json(path,payload):
    _save_json(payload,path)


class AllowanceReached(RuntimeError):pass


class RecoveryArchive:
    """Called under the financial-worker lock; reserve spend before writing bytes."""
    def __init__(self,root,ledger=LEDGER,budget=BUDGET,guard=storage_guard):
        self.archive=Archive(root);self.ledger=Path(ledger);self.budget=budget;self.guard=guard
    def available(self,digest=None):
        data=json.loads(self.ledger.read_text())
        reserved=data.get('source_recovery_reservations',{}).get(digest,{})
        outstanding=reserved.get('bytes',0) if not reserved.get('stored') else 0
        return max(0,self.budget-data['archive_bytes_added'])+outstanding
    def store(self,body,digest):
        if hashlib.sha256(body).hexdigest()!=digest:raise ValueError('SOURCE_HASH_MISMATCH')
        path=self.archive.root/digest[:2]/digest
        if path.exists():
            if hashlib.sha256(path.read_bytes()).hexdigest()!=digest:raise ValueError('LOCAL_HASH_MISMATCH')
            data=json.loads(self.ledger.read_text())
            reservation=data.get('source_recovery_reservations',{}).get(digest)
            if reservation and not reservation.get('stored'):
                reservation['stored']=True;write_json(self.ledger,data)
            return 0
        self.guard();data=json.loads(self.ledger.read_text());reservations=data.setdefault('source_recovery_reservations',{})
        if digest not in reservations or reservations[digest].get('stored'):
            if data['archive_bytes_added']+len(body)>self.budget:raise AllowanceReached('Original financial allowance reached')
            data['archive_bytes_added']+=len(body);reservations[digest]=dict(bytes=len(body),stored=False)
            write_json(self.ledger,data)
        elif reservations[digest]['bytes']!=len(body):raise ValueError('Reservation does not match verified source length')
        self.guard();self.archive.put(body,'recovered.xml')
        reservations[digest]['stored']=True;write_json(self.ledger,data);return len(body)


def download(entry,capacity):
    url=entry['url'];parsed=urlsplit(url)
    if parsed.scheme!='https' or parsed.hostname!='nsearchives.nseindia.com':raise ValueError('Unexpected financial-source URL')
    bound=min(MAX_BYTES,capacity)
    if bound<=0:raise AllowanceReached('Original financial allowance reached')
    req=urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0','Accept':'application/xml,text/xml'})
    with urllib.request.urlopen(req,timeout=20) as response:
        if urlsplit(response.geturl()).hostname!='nsearchives.nseindia.com':raise ValueError('Unexpected source redirect')
        body=response.read(bound+1)
    if len(body)>bound:
        if bound==MAX_BYTES:raise ValueError('SOURCE_RESOURCE_LIMIT')
        raise AllowanceReached('Response exceeds remaining allowance')
    return body


def plan(conn,archive):
    source=conn.execute('SELECT source_id FROM sources WHERE name=%s',(financials.SOURCE,)).fetchone()
    if source is None:return []
    # Prefer filings tied to recent shortlisted companies, then newest sources.
    since=datetime.now(timezone.utc).date()-timedelta(days=100)
    current={str(x[0]) for x in conn.execute('''SELECT DISTINCT i.issuer_id FROM triage_shortlist_items i
        JOIN triage_shortlists s USING(shortlist_id) WHERE s.week_start>=%s AND i.position IS NOT NULL''',(since,))}
    rows=conn.execute('''SELECT p.publication_id,p.issuer_id,p.published_at,p.source_url,v.sha256,v.byte_size,v.storage_key
       FROM document_publications p JOIN document_versions v USING(document_version_id)
       WHERE p.source_id=%s AND p.pipeline_state='TEXT_READY' AND p.published_at<=clock_timestamp()
       ORDER BY p.published_at DESC,p.publication_id''',(source[0],),prepare=False).fetchall()
    grouped={}
    for pid,issuer,at,url,digest,size,key in rows:
        if (archive/digest[:2]/digest).is_file():continue
        if key!=f'{digest[:2]}/{digest}':continue
        entry=grouped.setdefault(digest,dict(sha256=digest,url=url,size=size,publication_ids=[],published_at=at.isoformat(),
            current_issuer=str(issuer) in current))
        entry['publication_ids'].append(str(pid));entry['current_issuer']|=str(issuer) in current
    return sorted(grouped.values(),key=lambda x:(not x['current_issuer'],-datetime.fromisoformat(x['published_at']).timestamp(),x['sha256']))


def process_body(conn,entry,body,guard=storage_guard):
    """Parse verified memory bytes immediately, so regular raw cleanup cannot race parsing."""
    if hashlib.sha256(body).hexdigest()!=entry['sha256']:raise ValueError('SOURCE_HASH_MISMATCH')
    updated=[]
    for pid in entry['publication_ids']:
        guard()
        with conn.transaction():
            row=conn.execute('''SELECT p.issuer_id,p.published_at,p.raw_metadata,p.document_version_id,v.sha256
                FROM document_publications p JOIN document_versions v USING(document_version_id)
                JOIN sources s USING(source_id) WHERE p.publication_id=%s AND s.name=%s
                AND p.pipeline_state='TEXT_READY' AND p.published_at<=clock_timestamp() FOR UPDATE OF p''',
                (pid,financials.SOURCE)).fetchone()
            if row is None or row[4]!=entry['sha256'] or row[0] is None:raise ValueError('SOURCE_METADATA_CHANGED_OR_UNKNOWN')
            issuer,at,raw,vid,_=row
            if conn.execute('SELECT 1 FROM financial_facts WHERE publication_id=%s AND provider=%s AND provider_version=%s LIMIT 1',
                (pid,financials.PROVIDER,financials.ADAPTER_VERSION)).fetchone():
                updated.append(pid);continue
            parsed=parse_results_xbrl(body,listed_period(raw))
            if not parsed.figures:raise ValueError('PARSER_NO_FIGURES: '+str(parsed.issues[:3]))
            guard();financials._store_figures(conn,issuer,at,pid,vid,parsed);updated.append(pid)
    return updated


def refresh_packets(conn,ids,job):
    """Append fresh reads only where changed sources can affect a current packet."""
    from .packets import pipeline as P
    from .queue import LABEL
    if not ids:return []
    rows=conn.execute(f'''SELECT DISTINCT s.week_start,s.run_tag,p.issuer_id,{LABEL.format(col='p.issuer_id')}
      FROM triage_packets p JOIN triage_shortlists s USING(shortlist_id)
      WHERE p.packet_version='triage-packet-13' AND p.mode<>'ACTUAL_SYSTEM_REPLAY'
        AND NOT EXISTS(SELECT 1 FROM triage_packets child WHERE child.supersedes_id=p.packet_id
          AND child.shortlist_id=p.shortlist_id AND child.issuer_id=p.issuer_id)
        AND EXISTS(SELECT 1 FROM document_publications pub WHERE pub.publication_id=ANY(%s::uuid[])
          AND pub.issuer_id=p.issuer_id AND pub.published_at<=p.cutoff)
      ORDER BY s.week_start DESC,s.run_tag,p.issuer_id''',(ids,)).fetchall()
    results=[]
    for week,tag,issuer,label in rows:
        storage_guard()
        if not label:results.append(dict(issuer_id=str(issuer),error='Missing issuer label'));continue
        old=os.environ.get('INFLECTION_RUN_TAG')
        try:
            os.environ['INFLECTION_RUN_TAG']=tag;result=P.assemble(conn,week,label)
        finally:
            if old is None:os.environ.pop('INFLECTION_RUN_TAG',None)
            else:os.environ['INFLECTION_RUN_TAG']=old
        results.append(dict(week=str(week),run_tag=tag,issuer_id=str(issuer),counts=result.get('counts',{}),error=result.get('error')))
    with (job/'packet_refreshes.jsonl').open('a') as f:
        for r in results:f.write(json.dumps(r)+'\n')
    return results


def retryable_connection_failure(receipt):
    reason=(receipt.get('reason') or '').lower()
    return receipt.get('status')=='PENDING' and any(term in reason for term in (
        'timed out','nodename nor servname','temporary failure','connection reset',
        'connection refused','network is unreachable','dns','http error 502','http error 503','http error 504'))


def run(conn,job=JOB,archive=None,retry_pending=False):
    job=Path(job);job.mkdir(parents=True,exist_ok=True);archive=Path(archive or Path.home()/'inflection-archive')
    if not conn.execute('SELECT pg_try_advisory_lock(20261029,1)').fetchone()[0]:raise RuntimeError('Financial source worker already active')
    store=RecoveryArchive(archive,ledger=LEDGER,budget=BUDGET);state={};results={};queue=[]
    def save(**kwargs):
        state.update(kwargs,updated_at=datetime.now(timezone.utc).isoformat(),completed=len(results),
          counts=dict(Counter(r['status'] for r in results.values())),remaining=state.get('total',0)-len(results),financial_allowance_used=json.loads(LEDGER.read_text())['archive_bytes_added'])
        write_json(job/'status.json',state)
    def drain():
        if not queue:return
        if not conn.execute('SELECT pg_try_advisory_lock(20261029,5)').fetchone()[0]:return
        try:
            storage_guard();save(stage='Re-evaluate recovered financial evidence')
            scan=dict(F.scan(conn,publication_ids=queue));refresh=refresh_packets(conn,queue,job)
            with (job/'processing.jsonl').open('a') as f:f.write(json.dumps(dict(publication_ids=queue,scan=scan,packet_checks=len(refresh),packet_errors=[r for r in refresh if r.get('error')]))+'\n')
            queue.clear();write_json(job/'pending_analysis.json',queue)
        finally:conn.execute('SELECT pg_advisory_unlock(20261029,5)')
    try:
        path=job/'plan.json'
        if path.exists():entries=json.loads(path.read_text())
        else:storage_guard();entries=plan(conn,archive);write_json(path,entries)
        journal=job/'receipts.jsonl'
        if journal.exists():
            for line in journal.read_text().splitlines():
                if line:receipt=json.loads(line);results[receipt['sha256']]=receipt
        if retry_pending:
            results={key:receipt for key,receipt in results.items() if not retryable_connection_failure(receipt)}
        pending=job/'pending_analysis.json'
        if pending.exists():queue.extend(json.loads(pending.read_text()))
        # Recover a commit interrupted before its analysis checkpoint.
        analyzed=set()
        if (job/'processing.jsonl').exists():
            for line in (job/'processing.jsonl').read_text().splitlines():analyzed.update(json.loads(line)['publication_ids'])
        queue[:]=sorted(set(queue)|{pid for r in results.values() for pid in r.get('updated_publications',[]) if pid not in analyzed})
        state=dict(state='RUNNING',pid=os.getpid(),total=len(entries),raw_allowance_bytes=BUDGET,
                   retention_policy='Owner regularly clears raw documents; keep derived facts and verification receipts',archive_budgets_changed=False,retrying_connection_failures=retry_pending)
        save(stage='Recover recent financial originals within the original allowance');failures=0;budget_skipped=False
        drain()
        for entry in entries:
            if entry['sha256'] in results:continue
            storage_guard();capacity=store.available(entry['sha256'])
            if capacity<1024:save(state='ALLOWANCE_REACHED');break
            if entry.get('size') and entry['size']>capacity:budget_skipped=True;continue
            save(current=entry['publication_ids'],stage='Download and verify original disclosure')
            try:
                local=archive/entry['sha256'][:2]/entry['sha256']
                body=local.read_bytes() if local.is_file() else download(entry,capacity)
                written=store.store(body,entry['sha256'])
                updated=process_body(conn,entry,body)
                receipt=dict(sha256=entry['sha256'],publication_ids=entry['publication_ids'],status='VERIFIED',
                    new_archive_bytes=written,updated_publications=updated,verified_at=datetime.now(timezone.utc).isoformat())
                queue.extend(updated);write_json(pending,sorted(set(queue)));failures=0
            except AllowanceReached:
                save(state='ALLOWANCE_REACHED');break
            except (ValueError,OSError) as exc:
                receipt=dict(sha256=entry['sha256'],publication_ids=entry['publication_ids'],status='PENDING',reason=str(exc)[:1000]);failures+=1
            with journal.open('a') as f:f.write(json.dumps(receipt)+'\n')
            results[entry['sha256']]=receipt;save()
            if len(queue)>=20:drain()
            if failures>=8:save(state='SOURCE_UNAVAILABLE');break
            time.sleep(1)
        else:save(state='ALLOWANCE_REACHED' if budget_skipped else 'FINISHED_WITH_GAPS' if any(r['status']=='PENDING' for r in results.values()) or len(results)<len(entries) else 'COMPLETE')
        drain();save(pending_analysis=len(queue))
    except Exception as exc:
        save(state='STORAGE_LIMIT' if str(exc).startswith('STORAGE_LIMIT') else 'FAILED',error=str(exc));raise
    finally:conn.execute('SELECT pg_advisory_unlock(20261029,1)')
    return state


def run_resilient(conn,job=JOB,retry_pending=False,source_retries=0,retry_delay=60):
    """Bounded connection backoff for a finite repair; never reset the allowance."""
    job=Path(job)
    for attempt in range(source_retries+1):
        state=run(conn,job,retry_pending=retry_pending or attempt>0)
        if state['state']!='SOURCE_UNAVAILABLE' or attempt>=source_retries:return state
        receipts=[json.loads(line) for line in (job/'receipts.jsonl').read_text().splitlines() if line]
        failed=[r for r in receipts if r['status']=='PENDING'][-8:]
        if not failed or not all(retryable_connection_failure(r) for r in failed):return state
        delay=retry_delay*min(2**attempt,5)
        state.update(state='WAITING_FOR_SOURCE',next_retry_seconds=delay,source_retry=attempt+1,updated_at=datetime.now(timezone.utc).isoformat())
        write_json(job/'status.json',state);time.sleep(delay)
    return state


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--job',type=Path,default=JOB)
    ap.add_argument('--retry-pending',action='store_true',help='Retry saved connection failures; retain verified receipts and cumulative spend')
    ap.add_argument('--source-retries',type=int,default=0,help='Bounded retries after transient source outages')
    args=ap.parse_args()
    if not 0<=args.source_retries<=5:ap.error('--source-retries must be between 0 and 5')
    with psycopg.connect(os.environ.get('INFLECTION_DSN','postgresql:///inflection'),autocommit=True) as conn:
        conn.execute("SET statement_timeout='60s'");conn.execute("SET lock_timeout='10s'")
        print(json.dumps(run_resilient(conn,args.job,retry_pending=args.retry_pending,source_retries=args.source_retries),indent=2),flush=True)

if __name__=='__main__':main()
