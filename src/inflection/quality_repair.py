"""Checkpointed warning resolution: local evidence -> calculations -> corrected runs.

No raw downloads, archive deletions, paid models, original decision rewrites or
claims that later recovered evidence was known to the actual system earlier.
"""
from __future__ import annotations
from collections import Counter
from concurrent.futures import ThreadPoolExecutor,wait,FIRST_COMPLETED
from threading import current_thread
from contextlib import contextmanager
from datetime import date,datetime,time,timedelta,timezone
import argparse,hashlib,json,os,shutil,subprocess,sys,time as clock
from pathlib import Path
from types import SimpleNamespace
import psycopg
from .asof import IST
from .packet_rebuild import storage_guard,storage_reserve_bytes
from .timing_audit import save
from . import queue
from .financial import pipeline as F
from .packets import pipeline as P,contents as PC
from .triage import pipeline as T,screen,rules as TR
from .sources.download import Archive

ROOT=Path(__file__).resolve().parents[2]
JOB=ROOT/'output/process_health/jobs/quality_repair'
VERSION='quality-repair-1'
SPLIT=date(2024,10,28)
TERMINAL={'COMPLETE','FINISHED_WITH_GAPS','SOURCE_UNAVAILABLE','ALLOWANCE_REACHED','STORAGE_LIMIT','FAILED','OCR_UNAVAILABLE'}


def stamp():return datetime.now(timezone.utc).isoformat()


def write(path,payload):save(payload,Path(path))


def append(path,payload):
    with Path(path).open('a') as f:f.write(json.dumps(payload,default=str)+'\n')


def read_lines(path):
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line] if Path(path).exists() else []


@contextmanager
def analysis_lock(conn):
    acquired=conn.execute('SELECT pg_try_advisory_lock(20261029,5)').fetchone()[0]
    try:yield acquired
    finally:
        if acquired:conn.execute('SELECT pg_advisory_unlock(20261029,5)')


def source_pending():
    path=ROOT/'output/process_health/jobs/financial_source_recovery/pending_analysis.json'
    try:return bool(json.loads(path.read_text()))
    except (OSError,ValueError):return False


def producers(job=JOB):
    from .process_health import read_worker_status
    result={}
    for name,path in [('financial_recovery',ROOT/'output/process_health/jobs/financial_source_recovery/status.json'),
                      ('cached_evidence',Path(job)/'evidence_status.json')]:
        if path.exists():
            state=read_worker_status(path).get('state')
            result[name]='FAILED' if state in ('STOPPED','STALE') else state
    return result


def build_plan(conn,observed=None):
    observed=observed or datetime.now(timezone.utc)
    # One fresh reconstruction per week, combining the original run baselines.
    rows=conn.execute('''SELECT s.week_start,i.issuer_id FROM triage_shortlists s
       JOIN triage_shortlist_items i USING(shortlist_id) WHERE s.run_tag IN('base','rerun-3.4')
       AND i.position IS NOT NULL ORDER BY s.week_start,i.issuer_id''').fetchall()
    weeks={}
    for week,issuer in rows:weeks.setdefault(week,set()).add(str(issuer))
    current=observed.astimezone(IST).date();current-=timedelta(days=current.weekday())
    weeks.setdefault(current,set())
    ordered=sorted(weeks,key=lambda w:(w<SPLIT,w))
    source=conn.execute("SELECT source_id FROM sources WHERE name='nse_results_xbrl'").fetchone()
    finances=conn.execute('''SELECT publication_id FROM document_publications WHERE source_id=%s
        AND pipeline_state='TEXT_READY' AND published_at<=%s ORDER BY published_at DESC,publication_id''',
        (source[0],observed),prepare=False).fetchall() if source else []
    latest='''p.packet_version='triage-packet-13' AND NOT EXISTS(SELECT 1 FROM triage_packets child
        WHERE child.supersedes_id=p.packet_id AND child.shortlist_id=p.shortlist_id AND child.issuer_id=p.issuer_id)'''
    docs=conn.execute(f'''SELECT DISTINCT d->>'publication_id' FROM triage_packets p
        CROSS JOIN LATERAL jsonb_array_elements(p.content->'documents') d
        WHERE {latest} AND ((p.content->'manifest'->'missing_evidence') ?
        'Nomination filing attachments do not have complete verified text' OR
        (p.content->'manifest'->'missing_evidence') ? 'trigger passages: none public by the cutoff for the trigger events')
        AND d->>'publication_id' IS NOT NULL''').fetchall()
    prices=conn.execute(f'''SELECT DISTINCT p.issuer_id FROM triage_packets p WHERE {latest}
        AND (p.content->'manifest'->'missing_evidence') ? 'price: no prices public by the cutoff' ''').fetchall()
    from .commercial import vocabulary as CV
    return dict(version=VERSION,rules=dict(financial=F.R.RULES_VERSION,commercial=CV.RULES_VERSION,packet=PC.PACKET_VERSION,screen=screen.SCREEN_VERSION,triage=TR.POLICY_VERSION),observed_at=observed.isoformat(),financial_publications=[str(r[0]) for r in finances],
        evidence_publications=sorted(r[0] for r in docs),price_issuers=sorted(str(r[0]) for r in prices),
        weeks=[dict(week=str(w),cohort='recent' if w>=SPLIT else 'archive',original_issuers=sorted(weeks[w])) for w in ordered],
        constraints=dict(raw_download_bytes=0,reserve_gib=storage_reserve_bytes()//1024**3,preserve_original_decisions=True))


def repair_cached_prices(conn,first,last,issuers):
    """Only missing observations from retained exchange rows; never mutate an old close."""
    if not issuers:return 0
    from . import prices
    base=prices._FILL.split('ON CONFLICT',1)[0].replace('WHERE sec IS NOT NULL',
        'WHERE sec IS NOT NULL AND sec IN (SELECT security_id FROM securities WHERE issuer_id=ANY(%(issuers)s::uuid[]))')
    sql=base+' ON CONFLICT (security_id,trade_date,provider,provider_version,adjustment) DO NOTHING'
    total=0
    for exchange in ('NSE','BSE'):
        total+=conn.execute(sql,dict(provider=prices.PROVIDERS[exchange],version=prices.ADAPTER_VERSION,
            exchange=exchange,kind='SYMBOL' if exchange=='NSE' else 'SCRIP_CODE',start=first,end=last,issuers=issuers)).rowcount
    return total


class EvidenceJob:
    """Separate derived-work report: no original OCR/download ledger gets reset."""
    def __init__(self,path,plan):
        self.path=path;self.data=dict(state='RUNNING',pid=os.getpid(),issues=[],counts={},started_at=stamp(),raw_download_bytes=0)
        self.archive=Archive(Path.home()/'inflection-archive')
        self.args=SimpleNamespace(first=min(date.fromisoformat(w['week']) for w in plan['weeks'])-timedelta(days=P.LOOKBACK_DAYS),
            last=datetime.fromisoformat(plan['observed_at']).astimezone(IST).date(),cached_only=True,
            publication_ids=plan['evidence_publications'])
        self.update(stage='Repair retained source text and OCR')
    def update(self,**kwargs):
        self.data.update(kwargs,updated_at=stamp())
        if hasattr(self.archive,'written'):self.data['raw_download_bytes']=self.archive.written
        write(self.path,self.data)
    def guard_storage(self):storage_guard()
    def issue(self,**kwargs):self.data['issues'].append(kwargs);self.update()
    def command(self,*args):
        subprocess.run([str(x) for x in args],cwd=ROOT,env=dict(os.environ,INFLECTION_VERIFY_MODEL='local-clf-1'),check=True)


class CumulativeOCRArchive(Archive):
    """Continue the original OCR allowance without resetting its spend ledger."""
    def __init__(self,root,ledger=None,budget=128*1024**2):
        from .source_recovery import RecoveryArchive
        super().__init__(root)
        self.store=RecoveryArchive(root,ledger=ledger or ROOT/'output/process_health/jobs/ocr.json',
                                   budget=budget,guard=storage_guard)
        self.written=0
    def remaining_allowance(self):return self.store.available()
    def put(self,data,name):
        from .source_recovery import AllowanceReached
        from .sources.download import DocumentResourceLimit,StoredFile
        digest=hashlib.sha256(data).hexdigest()
        if len(data)>64*1024**2:raise DocumentResourceLimit('OCR original exceeds repair file limit')
        try:self.written+=self.store.store(data,digest)
        except AllowanceReached as exc:raise DocumentResourceLimit(str(exc)) from exc
        return StoredFile(digest,self.root/digest[:2]/digest,len(data),name)


def cached_evidence(conn,job,plan,recover=False):
    from . import repair_jobs as R,ingest
    worker=EvidenceJob(job/'evidence_status.json',plan)
    if not conn.execute("SELECT pg_try_advisory_lock(hashtextextended('quality-cached-evidence',0))").fetchone()[0]:
        raise RuntimeError('Cached evidence worker already active')
    ocr_lock=False
    try:
        if recover:
            ocr_lock=conn.execute('SELECT pg_try_advisory_lock(20261029,3)').fetchone()[0]
            if not ocr_lock:raise RuntimeError('Original OCR recovery worker is active')
            worker.archive=CumulativeOCRArchive(worker.archive.root)
            worker.args.cached_only=False
            worker.update(recovery_enabled=True,cumulative_budget_bytes=128*1024**2)
        ids=plan['evidence_publications']
        if ids:
            worker.guard_storage()
            worker.data['counts']['native_text']=dict(ingest.extract_pending(conn,worker.archive,limit=len(ids),publication_ids=ids))
            R.ocr(worker,conn)
        worker.data['remaining_source_states']=[dict(state=s,count=n) for s,n in conn.execute(
            'SELECT pipeline_state,count(*) FROM document_publications WHERE publication_id=ANY(%s::uuid[]) GROUP BY pipeline_state',
            (ids,))] if ids else []
        incomplete=sum(r['count'] for r in worker.data['remaining_source_states'] if r['state']!='TEXT_READY')
        if recover:worker.update(raw_download_bytes=worker.archive.written,remaining_allowance_bytes=worker.archive.remaining_allowance())
        worker.update(state='FINISHED_WITH_GAPS' if incomplete or worker.data['issues'] or any(
            worker.data['counts'].get(k) for k in ('PARTIAL','OCR_REQUIRED','ocr_failed')) else 'COMPLETE',stage='Cached evidence pass finished')
    except Exception as exc:
        worker.update(state='STORAGE_LIMIT' if str(exc).startswith('STORAGE_LIMIT') else 'FAILED',error=str(exc));raise
    finally:
        if ocr_lock:conn.execute('SELECT pg_advisory_unlock(20261029,3)')
        conn.execute("SELECT pg_advisory_unlock(hashtextextended('quality-cached-evidence',0))")


def case_basis(it):
    # Time itself changes freshness, financial availability and valuation. An
    # older pending packet must never stand in for a later weekly decision cut.
    return hashlib.sha256(json.dumps([str(it['issuer_id']),str(it['cutoff']),it['priority'],
        sorted(map(str,it['evaluation_ids'])),sorted(map(str,it['trigger_event_version_ids']))]).encode()).hexdigest()


def historical_case_issue(conn,it):
    if it['priority']!='U0':return None
    known=conn.execute("""SELECT 1 FROM research_cases WHERE issuer_id=%s AND created_at<=%s
       AND updated_at<=%s AND cutoff<=%s AND workflow_state NOT IN('REJECTED','CLOSED') LIMIT 1""",
       (it['issuer_id'],it['cutoff'],it['cutoff'],it['cutoff'])).fetchone()
    return None if known else 'Historical open-case priority has no case-state proof by this cutoff'


def corrected_case(conn,it,day,tag,guard=storage_guard):
    key=f"{tag}/{day}/{it['issuer_id']}";basis=case_basis(it)
    guard()
    with P.packet_snapshot(conn,it['shortlist_id'],it['issuer_id']):
        from .audit import recheck_packet
        content,_=P.packet_for(conn,it);content=recheck_packet(conn,content)
        issue=historical_case_issue(conn,it)
        if issue:
            m=content['manifest'];m['nomination_issues']=sorted(set(m.get('nomination_issues',[])+[issue]))
            m['missing_evidence']=sorted(set(m.get('missing_evidence',[])+[issue]))
            m.update(nomination_status='VERIFICATION_REQUIRED',completeness='PARTIAL')
        guard();stored=P.store_packet(conn,it,content,PC.TOKEN_BUDGET,
            created_by='inflection.quality_repair')
        p=stored['content'];result=screen.triage(p,conn,it['issuer_id'],use_llm=False)
        gaps=p['manifest'].get('missing_evidence') or []
        pending=bool(gaps or result.get('data_gaps'))
        recorded=None
        # Only a source-consistent completed screen advances this audit
        # run's cooldown. Pending data/research never becomes a rejection.
        if not pending:
            recorded=T.record(conn,day,it['label'],result['triage_action'],
                note='Automated screening in separate corrected audit run: '+str(result.get('rationale',''))[:700],
                by='quality-repair local screen',actor_kind='MODEL',packet_hash=PC.content_hash(p))
    row=dict(key=key,week=str(day),run_tag=tag,issuer_id=str(it['issuer_id']),basis=basis,
        packet_id=str(stored['packet_id']),packet_hash=PC.content_hash(p),packet_status=stored['status'],
        status='EVIDENCE_OR_RESEARCH_PENDING' if pending else 'SCREENED',screen=result,
        missing_evidence=gaps,nomination_issues=p['manifest'].get('nomination_issues',[]),recorded=recorded)
    return row


def case_connection(dsn,timeout,it,day,tag,job,guard):
    """One connection per task; globals remain fixed until this week's pool joins."""
    status=Path(job)/'workers'/(current_thread().name+'.json')
    state=dict(state='RUNNING',pid=os.getpid(),thread=current_thread().name,
               issuer_id=str(it['issuer_id']),week=str(day),started_at=stamp())
    try:
        with psycopg.connect(dsn,autocommit=True) as conn:
            conn.execute("SELECT set_config('statement_timeout',%s,false)",(timeout,))
            conn.execute("SET lock_timeout='10s'")
            conn.execute("SET jit=off")
            state.update(database_pid=conn.info.backend_pid);write(status,state)
            row=corrected_case(conn,it,day,tag,guard)
        from .audit import PARSED_DOCUMENTS
        state.update(state='IDLE',packet_id=row['packet_id'],source_parse_cache=PARSED_DOCUMENTS.stats(),updated_at=stamp());write(status,state)
        return row
    except Exception as exc:
        state.update(state='FAILED',error=str(exc),updated_at=stamp());write(status,state);raise


def parallel_cases(conn,items,day,tag,job,guard,workers):
    """At most four in-flight tasks; journal successful peers before any failure."""
    if not 1<=workers<=4:raise ValueError('Packet workers must be between 1 and 4')
    if len({str(it['issuer_id']) for it in items})!=len(items):raise ValueError('Duplicate issuer in parallel packet tasks')
    if workers==1:
        for it in items:yield corrected_case(conn,it,day,tag,guard)
        return
    dsn=conn.info.dsn;timeout=conn.execute('SHOW statement_timeout').fetchone()[0]
    tasks=iter(items)
    with ThreadPoolExecutor(max_workers=workers,thread_name_prefix='packet') as pool:
        pending={}
        def submit():
            it=next(tasks,None)
            if it is not None:pending[pool.submit(case_connection,dsn,timeout,it,day,tag,job,guard)]=it
        for _ in range(workers):submit()
        while pending:
            ready,_=wait(pending,return_when=FIRST_COMPLETED);error=None
            for future in ready:
                pending.pop(future)
                try:yield future.result()
                except Exception as exc:
                    if error is None:error=exc
            if error is not None:
                # Already-running tasks may have committed. Save their receipts
                # before propagating the error; do not schedule any new work.
                for future in pending:future.cancel()
                for future in pending:
                    if future.cancelled():continue
                    try:yield future.result()
                    except Exception:pass
                raise error
            for _ in ready:submit()


def corrected_week(conn,week,plan,job,guard=storage_guard,workers=1):
    tag=f"quality-20261030-{week['cohort']}";day=date.fromisoformat(week['week']);now=datetime.fromisoformat(plan['observed_at'])
    previous={k:os.environ.get(k) for k in ('INFLECTION_RUN_TAG','INFLECTION_RUN_BASE_UNTIL')}
    os.environ['INFLECTION_RUN_TAG']=tag;os.environ.pop('INFLECTION_RUN_BASE_UNTIL',None)
    try:
        guard();built=T.build(conn,day,mode='PUBLIC_INFORMATION_RECONSTRUCTION',now=now)
        cases=read_lines(job/'cases.jsonl');done={r['key']:r for r in cases};seen={r['basis'] for r in cases if r.get('basis') and r.get('run_tag')==tag}
        outcomes=[];original=set(week['original_issuers']);items=P._items(conn,day)
        current={str(it['issuer_id']):it for it in items}
        sid=built['shortlist_id']
        queued={str(r[0]):dict(slot=r[1],priority=r[2],reason=r[3],note=r[4]) for r in conn.execute(
            'SELECT issuer_id,slot,priority_class,reason,note FROM triage_shortlist_items WHERE shortlist_id=%s',(sid,))}
        for issuer in original-current.keys():
            outcomes.append(dict(issuer_id=issuer,status='NOT_SHORTLISTED_UNDER_CURRENT_EVIDENCE',
                queue=queued.get(issuer),reason='No current cutoff-eligible nomination' if issuer not in queued else queued[issuer]['reason']))
        tasks=[];selected={}
        for it in items:
            key=f"{tag}/{day}/{it['issuer_id']}";basis=case_basis(it)
            if key in done:selected[str(it['issuer_id'])]=done[key];continue
            if str(it['issuer_id']) not in original and basis in seen:
                selected[str(it['issuer_id'])]=dict(issuer_id=str(it['issuer_id']),status='EXISTING_PENDING_CASE',basis=basis);continue
            tasks.append(it);seen.add(basis)
        results={}
        for row in parallel_cases(conn,tasks,day,tag,job,guard,workers):
            append(job/'cases.jsonl',row);results[row['issuer_id']]=row
        selected.update(results)
        outcomes.extend(selected[str(it['issuer_id'])] for it in items)
        # Allocation accounts for every queue row, including data-repair/watch
        # items outside the shortlist; this report does not erase those rows.
        report=dict(week=str(day),run_tag=tag,cutoff=built['cutoff'],summary=built['summary'],outcomes=outcomes,
                    original_nominations=len(original),corrected_shortlisted=len(items))
        write(job/'weeks'/f"{week['cohort']}-{day}.json",report);return report
    finally:
        for key,value in previous.items():
            if value is None:os.environ.pop(key,None)
            else:os.environ[key]=value


def commercial_refresh(conn,plan):
    from .commercial import pipeline as C
    if not conn.execute('SELECT pg_try_advisory_lock(20261029,101)').fetchone()[0]:return None
    try:
        first=min(date.fromisoformat(w['week']) for w in plan['weeks'])-timedelta(days=P.LOOKBACK_DAYS);last=datetime.fromisoformat(plan['observed_at']).date()
        scanned=dict(C.scan(conn,first,last))
        verifier=Path.home()/'inflection-jobs/engine/month_local.py'
        if not verifier.exists():raise RuntimeError('Configured local source verifier is unavailable')
        subprocess.run([sys.executable,str(verifier),f'{first}:{last}'],cwd=ROOT,
            env=dict(os.environ,INFLECTION_DSN=conn.info.dsn,INFLECTION_VERIFY_MODEL='local-clf-1'),check=True)
        return scanned
    finally:conn.execute('SELECT pg_advisory_unlock(20261029,101)')


def finish_source_analysis(conn,job):
    """Drain retained recovery work even if its producer stopped at its allowance."""
    if any(state not in TERMINAL for state in producers(job).values()):return False
    peer=ROOT/'output/process_health/jobs/financial_source_recovery'
    pending=peer/'pending_analysis.json';status=peer/'status.json'
    if not pending.exists() or not json.loads(pending.read_text()):return True
    if not status.exists() or json.loads(status.read_text()).get('state') not in TERMINAL:return False
    if not conn.execute('SELECT pg_try_advisory_lock(20261029,1)').fetchone()[0]:return False
    try:
        with analysis_lock(conn) as acquired:
            if not acquired:return False
            ids=json.loads(pending.read_text())
            from .source_recovery import refresh_packets
            for start in range(0,len(ids),20):
                storage_guard();batch=ids[start:start+20]
                scan=dict(F.scan(conn,publication_ids=batch));results=refresh_packets(conn,batch,peer)
                append(peer/'processing.jsonl',dict(publication_ids=batch,scan=scan,packet_checks=len(results),
                    packet_errors=[r for r in results if r.get('error')],processed_by=VERSION))
                write(pending,ids[start+20:])
            state=json.loads(status.read_text());state.update(pending_analysis=0,analysis_completed_by=VERSION,updated_at=stamp());write(status,state)
            return True
    finally:conn.execute('SELECT pg_advisory_unlock(20261029,1)')


def recover_remaining_sources(conn):
    """One bounded recovery continuation before the final calculation sweep."""
    from . import source_recovery as recovery
    path=recovery.JOB/'status.json'
    if not path.exists():return dict(state='NO_RECOVERY_JOB')
    status=json.loads(path.read_text())
    spent=json.loads(recovery.LEDGER.read_text())['archive_bytes_added']
    if status.get('state')=='SOURCE_UNAVAILABLE' and spent<recovery.BUDGET:
        return recovery.run_resilient(conn,recovery.JOB,retry_pending=True,source_retries=3)
    return dict(state=status.get('state'),financial_allowance_used=spent)


def run(conn,job=JOB,workers=1,prune_old=False):
    job=Path(job);job.mkdir(parents=True,exist_ok=True);state_path=job/'status.json'
    if not conn.execute("SELECT pg_try_advisory_lock(hashtextextended('quality-repair',0))").fetchone()[0]:raise RuntimeError('Coordinated repair already active')
    state=json.loads(state_path.read_text()) if state_path.exists() else {}
    state.pop('error',None)
    def update(**kwargs):state.update(kwargs,pid=os.getpid(),updated_at=stamp());write(state_path,state)
    try:
        if (job/'plan.json').exists():plan=json.loads((job/'plan.json').read_text())
        else:
            update(state='RUNNING',stage='Identify affected inputs and reconstruction weeks')
            plan=build_plan(conn);write(job/'plan.json',plan)
        from .commercial import vocabulary as CV
        active=dict(financial=F.R.RULES_VERSION,commercial=CV.RULES_VERSION,packet=PC.PACKET_VERSION,screen=screen.SCREEN_VERSION,triage=TR.POLICY_VERSION)
        if plan['version']!=VERSION or plan.get('rules')!=active:raise ValueError('Repair plan rules changed; use a new versioned repair job')
        update(state='RUNNING',packet_workers=workers,packet_worker_jit=False,source_parse_cache_max_mib=64,
               prune_old_packets=prune_old,reserve_gib=storage_reserve_bytes()//1024**3,
               resume_when_free_bytes=storage_reserve_bytes()+512*1024**2,free_bytes=shutil.disk_usage(ROOT).free,
               version=VERSION,financial_total=len(plan['financial_publications']),weeks_total=len(plan['weeks']),raw_download_bytes=0)
        completed={r['key'] for r in read_lines(job/'stages.jsonl')}
        def stage_done(key,**values):append(job/'stages.jsonl',dict(key=key,at=stamp(),**values));completed.add(key)
        # The first pass fixes stale calculations using retained figures while
        # raw recovery and cached OCR continue independently. The second pass
        # drains the producer's final changes before freezing corrected runs.
        for sweep in ('initial','final'):
            if sweep=='final':
                while any(v not in TERMINAL for v in producers(job).values()):
                    update(stage='Waiting for bounded source and cached-evidence workers',waiting_for=producers(job));clock.sleep(10)
                if 'bounded-source-continuation' not in completed:
                    update(stage='Recover remaining permitted originals with bounded network backoff')
                    source_report=recover_remaining_sources(conn)
                    stage_done('bounded-source-continuation',source_state=source_report.get('state'))
                key='commercial'
                if key not in completed:
                    while True:
                        storage_guard()
                        with analysis_lock(conn) as acquired:
                            if acquired:
                                update(stage='Resolve recovered commercial source evidence');result=commercial_refresh(conn,plan)
                                if result is not None:stage_done(key,counts=result);break
                        clock.sleep(2)
            pubs=plan['financial_publications']
            for start in range(0,len(pubs),20):
                key=f'financial/{sweep}/{start}'
                if key in completed:continue
                while True:
                    storage_guard()
                    if source_pending() and producers(job).get('financial_recovery') not in TERMINAL:
                        update(stage='Allow recovered-source analysis to drain');clock.sleep(5);continue
                    with analysis_lock(conn) as acquired:
                        if acquired:
                            update(stage=f'Recalculate financial inputs: {sweep}',financial_position=start,financial_sweep=sweep)
                            result=dict(F.scan(conn,publication_ids=pubs[start:start+20]));stage_done(key,counts=result);break
                    clock.sleep(2)
                clock.sleep(.05)
        while not finish_source_analysis(conn,job):
            update(stage='Wait for source and OCR recovery, then drain final analysis');clock.sleep(5)
        if 'post-recovery-commercial' not in completed:
            while True:
                storage_guard()
                with analysis_lock(conn) as acquired:
                    if acquired:
                        update(stage='Resolve final recovered text before weekly packets')
                        result=commercial_refresh(conn,plan)
                        if result is not None:
                            stage_done('post-recovery-commercial',counts=result);break
                clock.sleep(2)
        # Restore missing price observations from already-retained exchange rows.
        first=min(date.fromisoformat(w['week']) for w in plan['weeks'])-timedelta(days=400)
        end=datetime.fromisoformat(plan['observed_at']).astimezone(IST).date();month=date(first.year,first.month,1)
        while month<=end:
            next_month=date(month.year+1,1,1) if month.month==12 else date(month.year,month.month+1,1)
            key=f'prices/{month}'
            if key not in completed:
                storage_guard();update(stage=f'Restore retained exchange prices: {month}')
                with conn.transaction():rows=repair_cached_prices(conn,month,min(end,next_month-timedelta(days=1)),plan['price_issuers'])
                stage_done(key,rows=rows)
            month=next_month
        def retain_completed_packets():
            if not prune_old:return
            from . import packet_retention
            acquired=conn.execute("SELECT pg_try_advisory_lock(hashtextextended('packet-retention',0))").fetchone()[0]
            if not acquired:
                update(retention_deferred='Separate cleanup worker is active');return
            update(stage='Clear old completed packet contents; preserve latest and decision evidence')
            try:result=packet_retention.run(conn,job/'retention',apply=True,quality_job=job)
            finally:conn.execute("SELECT pg_advisory_unlock(hashtextextended('packet-retention',0))")
            update(last_retention_removed=result['removed_payloads'],last_retention_at=stamp())
        retain_completed_packets()
        for index,week in enumerate(plan['weeks']):
            key=f"week/{week['cohort']}/{week['week']}"
            if key in completed:continue
            storage_guard();update(stage='Rebuild corrected shortlists, packets and screens',week=week['week'],cohort=week['cohort'],week_position=index)
            report=corrected_week(conn,week,plan,job,workers=workers)
            stage_done(key,summary=report['summary'])
            retain_completed_packets()
        cases=read_lines(job/'cases.jsonl');warnings=Counter(reason for case in cases for reason in case['missing_evidence'])
        summary=dict(cases=len(cases),case_statuses=dict(Counter(c['status'] for c in cases)),warnings=dict(warnings),
            source_states=producers(job),original_decisions_unchanged=True,raw_download_bytes=0,completed_at=stamp())
        write(job/'summary.json',summary)
        update(state='FINISHED_WITH_GAPS' if warnings or any(c['status']!='SCREENED' for c in cases) else 'COMPLETE',stage='Corrected reconstruction finished',summary=summary)
    except Exception as exc:
        update(state='STORAGE_LIMIT' if str(exc).startswith('STORAGE_LIMIT') else 'FAILED',error=str(exc));raise
    finally:conn.execute("SELECT pg_advisory_unlock(hashtextextended('quality-repair',0))")
    return state


def run_when_space_available(conn,job=JOB,check_interval=60,workers=1,prune_old=False):
    """Pause writes on transient space pressure and resume the same checkpoints.

    The configured reserve remains enforced. After a pause, require an extra
    512 MiB of headroom before retrying, to avoid rapid restart/stop cycles.
    """
    job=Path(job);job.mkdir(parents=True,exist_ok=True)
    lock='quality-repair-supervisor'
    if not conn.execute('SELECT pg_try_advisory_lock(hashtextextended(%s,0))',(lock,)).fetchone()[0]:
        raise RuntimeError('Another repair supervisor is active')
    try:
        while True:
            try:
                if prune_old:return run(conn,job,workers=workers,prune_old=True)
                return run(conn,job) if workers==1 else run(conn,job,workers=workers)
            except RuntimeError as exc:
                if not str(exc).startswith('STORAGE_LIMIT'):raise
                path=job/'status.json';state=json.loads(path.read_text()) if path.exists() else {}
                state.update(state='WAITING_FOR_STORAGE',pid=os.getpid(),error=str(exc),
                    paused_stage=state.get('stage'),resume_when_free_bytes=storage_reserve_bytes()+512*1024**2,
                    next_check_seconds=check_interval,updated_at=stamp())
                write(path,state);append(job/'storage_pauses.jsonl',dict(event='PAUSED',at=stamp(),stage=state.get('paused_stage')))
                while True:
                    free=shutil.disk_usage(ROOT).free
                    state.update(free_bytes=free,updated_at=stamp());write(path,state)
                    if free>=state['resume_when_free_bytes']:break
                    clock.sleep(check_interval)
                state.update(state='RUNNING',storage_resume_count=state.get('storage_resume_count',0)+1,
                    stage='Resume repair from saved checkpoints',updated_at=stamp())
                state.pop('error',None);write(path,state)
                append(job/'storage_pauses.jsonl',dict(event='RESUMING',at=stamp(),free_bytes=free))
    finally:conn.execute('SELECT pg_advisory_unlock(hashtextextended(%s,0))',(lock,))


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--job',type=Path,default=JOB);ap.add_argument('--evidence',action='store_true')
    ap.add_argument('--recover-evidence',action='store_true',help='Use only the unspent original OCR recovery allowance')
    ap.add_argument('--statement-timeout-seconds',type=int,default=90,help='Bound each repair query; historical weekly reconstruction may need more time')
    ap.add_argument('--workers',type=int,default=1,help='Parallel packet workers within each chronological week (1-4)')
    ap.add_argument('--prune-old-packets',action='store_true',help='Owner-authorized removal of older completed draft payloads after each week')
    ap.add_argument('--reserve-gib',type=int,default=8,help='Minimum free disk space; only lower with owner authorization')
    args=ap.parse_args()
    if not 5<=args.reserve_gib<=1024:ap.error('--reserve-gib must be between 5 and 1024')
    os.environ['INFLECTION_REPAIR_RESERVE_GIB']=str(args.reserve_gib)
    if not 1<=args.workers<=4:ap.error('--workers must be between 1 and 4')
    if args.recover_evidence and not args.evidence:ap.error('--recover-evidence requires --evidence')
    if not 1<=args.statement_timeout_seconds<=900:ap.error('--statement-timeout-seconds must be between 1 and 900')
    with psycopg.connect(os.environ.get('INFLECTION_DSN','postgresql:///inflection'),autocommit=True) as conn:
        conn.execute("SELECT set_config('statement_timeout',%s,false)",(f'{args.statement_timeout_seconds}s',))
        conn.execute("SET lock_timeout='10s'")
        if args.evidence:
            while not (args.job/'plan.json').exists():clock.sleep(2)
            cached_evidence(conn,args.job,json.loads((args.job/'plan.json').read_text()),recover=args.recover_evidence)
        else:print(json.dumps(run_when_space_available(conn,args.job,workers=args.workers,prune_old=args.prune_old_packets),indent=2),flush=True)

if __name__=='__main__':main()
