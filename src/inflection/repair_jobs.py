"""Bounded, resumable repair workers. No stock admission rules or paid model calls.

python -m inflection.repair_jobs launch --from 2026-08-01 --to 2026-10-28
Each worker has its own advisory lock, progress JSON and log. Unproven evidence stays unresolved.
"""
from __future__ import annotations
import argparse
from collections import Counter
from datetime import date, datetime, timedelta, time, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time as clock

import psycopg
from .coverage_repair import write_progress
from .process_health import read_worker_status
from .sources.common import IST, WindowStatus
from .sources.download import Archive, DocumentResourceLimit
from .documents import publication_member_sql
from .sources.http import HttpClient, curl_cffi_transport

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT/'output/process_health/jobs'
TASKS = ('references','financials','attachments','ocr','evidence','analysis')
GIB = 1024**3

class StorageLimit(RuntimeError): pass

class BoundedArchive(Archive):
    def __init__(self,root,budget=GIB,reserve=8*GIB):
        super().__init__(root); self.budget=budget; self.reserve=reserve; self.written=0
    def put(self,data,name):
        digest=hashlib.sha256(data).hexdigest()
        if not (self.root/digest[:2]/digest).exists():
            if len(data)>64*1024**2:
                raise DocumentResourceLimit('File exceeds the 64 MB repair storage limit')
            if self.written+len(data)>self.budget or shutil.disk_usage(self.root).free-len(data)<self.reserve:
                raise StorageLimit('Storage limit reached; progress retained, no archive files deleted')
            stored=super().put(data,name); self.written+=len(data); return stored
        return super().put(data,name)

class Job:
    def __init__(self,task,args):
        self.task=task; self.args=args; self.path=OUT/f'{task}.json'
        self.data=dict(task=task,state='RUNNING',pid=os.getpid(),first=str(args.first),last=str(args.last),
                       started_at=datetime.now(timezone.utc).isoformat(),counts={},issues=[])
        self.archive=BoundedArchive(args.archive,args.budget_mb*1024**2)
        self.update(stage='Starting')
    def update(self,**values):
        self.data.update(values)
        if hasattr(self,'archive'):self.data['archive_bytes_added']=self.archive.written
        write_progress(self.path,self.data)
    def issue(self,**values):
        self.data['issues'].append(values); self.update()
    def guard_storage(self):
        if shutil.disk_usage(self.archive.root).free < self.archive.reserve:
            raise StorageLimit('Free-space reserve reached; no further repair writes started')
    def command(self,*argv):
        print('Running:',*map(str,argv),flush=True)
        env=dict(os.environ,INFLECTION_VERIFY_MODEL='local-clf-1')
        env.setdefault('INFLECTION_DSN','postgresql:///inflection')
        subprocess.run([str(x) for x in argv],cwd=ROOT,env=env,check=True)
    def health(self,conn):
        from .process_health import collect,save
        save(collect(conn,self.args.first,self.args.last),OUT.parent)
        from . import timing_audit
        today=datetime.now(IST).date()
        timing_audit.save(timing_audit.collect(conn,today-timedelta(days=30),today),OUT/'timing.json')


def client(bse=False):
    transport=None
    if bse:
        try:transport=curl_cffi_transport()
        except ImportError:pass
    return HttpClient(min_interval=1.5,timeout=30,retries=1,transport=transport)


def references(job,conn):
    from . import companies,corporate_actions
    from .sources import listings
    snapshot=datetime.now(IST).date()
    for exchange,fetch in [('NSE',listings.fetch_nse),('BSE',listings.fetch_bse)]:
        job.update(stage=f'Refresh {exchange} reference lists, including published inactive statuses')
        for result in fetch(client(exchange=='BSE')):
            print(companies.record_list(conn,result,snapshot,job.archive),flush=True)
            if result.status!=WindowStatus.COMPLETE:job.issue(source=result.list_name,status=result.status.value,notes=result.notes)
    job.update(stage='Rebuild dated identities and link source publications')
    # Both reference refresh and derived analysis update publication identities.
    # Serialize their linking passes rather than letting their row locks conflict.
    conn.execute('SELECT pg_advisory_lock(20261029,100)')
    try:
        built=companies.build_from_master(conn)
        print(built,flush=True)
        if built.get('conflicts'):job.issue(stage='identity_conflicts',details=built['conflicts'])
        print(companies.link_publications(conn),flush=True)
    finally:conn.execute('SELECT pg_advisory_unlock(20261029,100)')
    job.update(stage='Fetch and reconcile corporate actions')
    for result in corporate_actions.fetch(conn,client(),job.args.first,job.args.last):
        print(result,flush=True)
        if result['status']!='COMPLETE':job.issue(source='corporate_actions',result=result)
    print(corporate_actions.reconcile(conn),flush=True)


def financials(job,conn):
    from . import financials as F
    from .sources.xbrl import NSEResultsListing
    # Wait for the concurrent identity refresh, but do not mistake a failed refresh for success.
    while True:
        try:reference=read_worker_status(OUT/'references.json')
        except (OSError,ValueError):reference={}
        if reference.get('state') not in (None,'RUNNING','STARTING'):break
        job.update(stage='Waiting for reference-list refresh'); clock.sleep(15)
    if reference.get('state')!='COMPLETE':job.issue(source='references',status=reference.get('state'))
    first=date(2021,1,1); last=job.args.last
    lo=datetime.combine(first,time(),IST); hi=datetime.combine(last+timedelta(days=1),time(),IST)
    done={(r[0],r[1]) for r in conn.execute("""SELECT DISTINCT r.reconciliation_result->>'symbol',r.segment
       FROM ingestion_runs r JOIN sources s USING(source_id) WHERE s.name=%s AND coverage_status='COMPLETE'
       AND window_start<=%s AND window_end>=%s AND r.finished_at>=%s""",(F.SOURCE,lo,hi,hi))}
    listing=NSEResultsListing(client()); counts=Counter()
    for symbol,issuer,index in F.current_symbols(conn):
        if (symbol,index) in done:counts['already_complete']+=1;continue
        job.guard_storage()
        job.update(stage=f'Discover original results and prior periods: {symbol}',counts=dict(counts))
        result=listing.list_symbol(symbol,index)
        status,found,new=F.record_listing(conn,result,issuer,first,last)
        counts[status]+=1;counts['filings_new']+=new
        if result.status in (WindowStatus.BLOCKED,WindowStatus.FAILED):
            job.update(state='SOURCE_UNAVAILABLE');job.issue(source=symbol,status=status,notes=result.notes);return
        if result.status!=WindowStatus.COMPLETE:job.issue(source=symbol,status=status,notes=result.notes)
        if new or sum(counts[s] for s in ('COMPLETE','PARTIAL','EMPTY_UNVERIFIED'))%20==0:
            job.update(stage='Load original results and missing comparables',counts=dict(counts))
            loaded=F.load_pending(conn,job.archive,client(),limit=200,retry_failed=True,reparse_failed=True,
                                  start=first,end=last)
            counts.update({f'load:{k}':v for k,v in loaded.items()})
            if loaded['BLOCKED'] or loaded['FAILED']:
                job.update(state='SOURCE_UNAVAILABLE',counts=dict(counts));return
    job.update(counts=dict(counts),stage='Load remaining discovered results')
    while True:
        loaded=F.load_pending(conn,job.archive,client(),limit=200,retry_failed=False,start=first,end=last)
        if not loaded:break
        counts.update({f'load:{k}':v for k,v in loaded.items()});job.update(counts=dict(counts))
        if loaded['BLOCKED'] or loaded['FAILED']:
            job.update(state='SOURCE_UNAVAILABLE');return


def attachments(job,conn):
    from . import ingest
    if getattr(job.args,'cached_only',False):
        counts=Counter()
        while True:
            job.guard_storage()
            extracted=ingest.extract_pending(conn,job.archive,limit=100,start=job.args.first,end=job.args.last)
            if not extracted:break
            counts.update({f'text:{k}':v for k,v in extracted.items()});job.update(counts=dict(counts))
        job.issue(stage='raw_downloads_deferred',status='CACHED_ONLY',detail='Additional raw downloads remain deferred under the archive limit')
        job.update(state='FINISHED_WITH_GAPS',stage='Cached downloads processed; additional raw downloads remain deferred')
        return
    clients={ex:client(ex=='BSE') for ex in ('NSE','BSE')}; active=set(clients);counts=Counter()
    while active:
        for exchange in tuple(sorted(active)):
            job.guard_storage()
            # Flush already downloaded files before asking for more archive space.
            counts.update({f'text:{k}':v for k,v in ingest.extract_pending(conn,job.archive,limit=100,
                start=job.args.first,end=job.args.last).items()})
            job.update(stage=f'Download and extract {exchange} attachments across all companies',counts=dict(counts))
            try:
                outcome=ingest.download_pending(conn,job.archive,clients[exchange],exchange,limit=20,
                    retry_failed=True,start=job.args.first,end=job.args.last,stop_on_unavailable=True)
            except StorageLimit:
                counts.update({f'text:{k}':v for k,v in ingest.extract_pending(conn,job.archive,limit=100,
                    start=job.args.first,end=job.args.last).items()})
                job.update(counts=dict(counts))
                raise
            counts.update({f'download:{k}':v for k,v in outcome.items()})
            extracted=ingest.extract_pending(conn,job.archive,limit=100,start=job.args.first,end=job.args.last)
            counts.update({f'text:{k}':v for k,v in extracted.items()})
            if outcome['BLOCKED'] or outcome['FAILED']:
                job.issue(source=exchange,status='SOURCE_UNAVAILABLE',counts=dict(outcome));active.remove(exchange)
            elif not outcome:active.remove(exchange)
            job.update(counts=dict(counts),archive_bytes_added=job.archive.written)
    if job.data['issues']:job.update(state='SOURCE_UNAVAILABLE')


def ocr(job,conn):
    from . import ingest
    from .text_extraction import classify_pages
    config=ROOT/'output/process_health/ocr_runtime.json'
    method='apple-vision';version='apple-vision-2'; binary=ROOT/'output/process_health/vision_ocr_v2'
    if config.exists():
        from .ocr_cpu import VERSION
        settings=json.loads(config.read_text())
        method='tesseract-cpu';version=VERSION+'-'+settings['model_sha256'][:12]
        binary=[sys.executable,'-m','inflection.ocr_cpu','--config',str(config)]
    elif not binary.exists():
        job.update(stage='Compile local OCR using macOS Vision')
        job.command('/usr/bin/swiftc','-module-cache-path',ROOT/'output/process_health/swift-cache',
                    Path(__file__).parent/'native/vision_ocr.swift','-o',binary)
    counts=Counter();seen=set();deferred=set();unavailable=set();clients={}
    def producer_state():
        try:return read_worker_status(ROOT/'output/process_health/jobs/attachments.json').get('state')
        except (OSError,ValueError):return None
    while True:
        before=producer_state()
        _ocr_pass(job,conn,version,binary,counts,seen,deferred,unavailable,clients,method)
        if job.data.get('state')=='OCR_UNAVAILABLE':return
        after=producer_state()
        if after not in ('RUNNING','STARTING'):
            if before in ('RUNNING','STARTING'):continue  # Drain the producer's final batch once.
            break
        job.update(stage='Waiting for new scanned filings from the attachment worker',counts=dict(counts))
        clock.sleep(60)


def _ocr_pass(job,conn,version,binary,counts,seen,deferred,unavailable,clients,method='apple-vision'):
    from . import ingest
    from .text_extraction import classify_pages
    rows=conn.execute(f"""SELECT DISTINCT v.document_version_id,v.sha256,v.storage_key,p.attachment_url,s.name,v.byte_size
       FROM document_publications p JOIN sources s USING(source_id)
       JOIN document_versions root ON root.document_version_id=p.document_version_id
       JOIN document_versions v ON {publication_member_sql('root','v')}
       WHERE coalesce(p.published_at,(p.published_date+1)::timestamp AT TIME ZONE 'Asia/Kolkata'-interval '1 microsecond')>=%s
       AND coalesce(p.published_at,(p.published_date+1)::timestamp AT TIME ZONE 'Asia/Kolkata'-interval '1 microsecond')<%s
       AND p.pipeline_state IN('OCR_REQUIRED','PARTIAL_TEXT')
       AND (%s::uuid[] IS NULL OR p.publication_id=ANY(%s::uuid[]))
       AND v.media_type='application/pdf' AND s.name=ANY(%s)
       AND NOT EXISTS(SELECT 1 FROM text_artifacts a WHERE a.document_version_id=v.document_version_id AND a.status='COMPLETE')
       AND NOT EXISTS(SELECT 1 FROM text_artifacts a WHERE a.document_version_id=v.document_version_id AND a.extraction_version=%s)
       ORDER BY v.document_version_id""",(datetime.combine(job.args.first,time(),IST),
       datetime.combine(job.args.last+timedelta(days=1),time(),IST),getattr(job.args,'publication_ids',None),
       getattr(job.args,'publication_ids',None),[s['name'] for s in ingest.SOURCES.values()],version)).fetchall()
    # Drain retained files before spending any recovery budget on missing originals.
    rows.sort(key=lambda row:(not (job.archive.root/row[2]).exists(),row[5] or 0,str(row[0])))
    for vid,sha,key,url,source,size in rows:
        if vid in seen:continue
        job.guard_storage()
        path=job.archive.root/key
        job.update(stage=f'OCR archived PDF {vid}',counts=dict(counts))
        if not path.exists():
            if (vid,url) in deferred:continue
            if getattr(job.args,'cached_only',False) or source in unavailable:
                deferred.add((vid,url))
                if not any(i.get('document_version_id')==str(vid) and i.get('status')=='ARCHIVE_NOT_CACHED' for i in job.data['issues']):
                    counts['archive_not_cached']+=1
                    job.issue(document_version_id=str(vid),status='ARCHIVE_NOT_CACHED')
                continue
            if hasattr(job.archive,'remaining_allowance') and size and size>job.archive.remaining_allowance():
                deferred.add((vid,url));counts['budget_deferred']+=1
                job.issue(document_version_id=str(vid),status='CUMULATIVE_ALLOWANCE_INSUFFICIENT')
                continue
            from .sources.download import download
            ex='BSE' if source=='bse_announcements' else 'NSE'
            if source not in clients:clients[source]=client(ex=='BSE')
            recovered=download(url,job.archive,clients[source],referer=ingest.SOURCES[ex]['referer'])
            if not path.exists():
                counts['original_bytes_unavailable']+=1;job.issue(document_version_id=str(vid),status='ORIGINAL_BYTES_UNAVAILABLE',download_status=recovered.status.value)
                deferred.add((vid,url))
                if recovered.status.value in ('BLOCKED','FAILED'):unavailable.add(source)
                continue
        seen.add(vid)
        if hashlib.sha256(path.read_bytes()).hexdigest()!=sha:
            job.issue(document_version_id=str(vid),status='ARCHIVE_HASH_MISMATCH');continue
        try:
            command=list(binary) if isinstance(binary,(list,tuple)) else [str(binary)]
            result=subprocess.run([*command,str(path)],capture_output=True,text=True,timeout=900,check=True)
            data=json.loads(result.stdout)
            if not isinstance(data.get('pages'),list) or any(not isinstance(p,str) for p in data['pages']):
                raise ValueError('OCR returned invalid page text')
            pages=[p.replace('\x00','') for p in data['pages']]
            if (type(data.get('pages_expected')) is not int or data['pages_expected']<=0
                or len(pages)!=data['pages_expected']):
                raise ValueError('OCR page count does not match the source PDF')
            if not isinstance(data.get('low_confidence_pages'),list) or any(
                type(n) is not int or not 1<=n<=len(pages) for n in data['low_confidence_pages']):
                raise ValueError('OCR returned invalid confidence page references')
            status,issues=classify_pages(pages,data['pages_expected'])
            if data['low_confidence_pages']:
                from .text_extraction import ExtractionStatus
                if status==ExtractionStatus.COMPLETE:status=ExtractionStatus.PARTIAL
                issues.append('OCR low-confidence pages: '+str(data['low_confidence_pages']))
            if data.get('page_quality'):
                issues.extend('OCR page '+str(q['page'])+': '+', '.join(q['issues'])
                              for q in data['page_quality'] if q.get('issues'))
            with conn.transaction():
                aid=conn.execute("""INSERT INTO text_artifacts(document_version_id,extraction_method,extraction_version,status,
                  pages_expected,pages_processed,pages_with_text,text_sha256,quality_issues,missing_pages,created_by)
                  VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'inflection.repair_jobs')
                  RETURNING text_artifact_id""",(vid,method,version,status.value,data['pages_expected'],len(pages),sum(bool(p.strip()) for p in pages),
                  hashlib.sha256('\f'.join(pages).encode()).hexdigest(),issues,[i+1 for i,p in enumerate(pages) if not p.strip()])).fetchone()[0]
                with conn.cursor() as cur:
                    cur.executemany('INSERT INTO text_pages(text_artifact_id,page_no,body) VALUES(%s,%s,%s)',
                                    [(aid,i+1,p) for i,p in enumerate(pages) if p.strip()])
                # A document is ready only when every PDF member has complete text.
                conn.execute(f"""UPDATE document_publications p SET
                  pipeline_state=CASE WHEN 'ZIP_INCOMPLETE'=ANY(p.processing_issues) THEN 'PARTIAL_TEXT' ELSE 'TEXT_READY' END,
                  failure_reason=NULL,revision=revision+1
                  FROM document_versions root,document_versions target WHERE p.document_version_id=root.document_version_id
                  AND target.document_version_id=%s AND {publication_member_sql('root','target')}
                  AND p.pipeline_state IN('OCR_REQUIRED','PARTIAL_TEXT') AND NOT EXISTS(
                    SELECT 1 FROM document_versions member WHERE {publication_member_sql('root','member')} AND member.media_type='application/pdf'
                    AND NOT EXISTS(SELECT 1 FROM text_artifacts a WHERE a.document_version_id=member.document_version_id AND a.status='COMPLETE'))""",(vid,))
            counts[status.value]+=1
            job.data['issues']=[i for i in job.data['issues'] if not (
                i.get('document_version_id')==str(vid) and i.get('status') in ('ARCHIVE_NOT_CACHED','ORIGINAL_BYTES_UNAVAILABLE'))]
        except (subprocess.SubprocessError,ValueError) as exc:
            diagnostic=getattr(exc,'stderr','') or ''
            if isinstance(diagnostic,bytes):diagnostic=diagnostic.decode('utf-8','replace')
            counts['ocr_failed']+=1
            job.issue(document_version_id=str(vid),status='OCR_FAILED',error=str(exc)[:300],stderr=diagnostic[:1500])
            if 'e5rtError' in diagnostic or 'e5rt_execution_stream_operation' in diagnostic:
                job.update(state='OCR_UNAVAILABLE',stage='Local OCR compute backend unavailable, including CPU fallback',counts=dict(counts))
                return
        job.update(counts=dict(counts))


def evidence(job,conn):
    """Make evidence-only limitations actionable; never relabel a snapshot as an original filing."""
    from .financial.rules import RULES_VERSION
    queries={
      'snapshot_disclosures':("""SELECT issuer_id,period_end,scope,count(*) facts FROM financial_facts
         WHERE provider='bse_results_snapshot' AND provider_version='bse-results-snapshot-1' AND available_at<recorded_at
         GROUP BY 1,2,3 ORDER BY 1,2,3""",()),
      'unknown_financial_facts':("SELECT fact_id,issuer_id,provider,publication_id,scope,available_at FROM financial_facts_asof WHERE scope='UNKNOWN' OR available_at IS NULL",()),
      'unlinked_publications':("""SELECT publication_id,source_id,published_at,raw_metadata->>'_symbol' symbol,source_url FROM document_publications
         WHERE issuer_id IS NULL AND published_at>=%s AND published_at<%s""",(datetime.combine(job.args.first,time(),IST),datetime.combine(job.args.last+timedelta(days=1),time(),IST))),
      'missing_comparables':("SELECT publication_id,issuer_id,period_type,period_end,scope FROM financial_scans WHERE status='NO_COMPARABLE' AND rules_version=%s",(RULES_VERSION,)),
      'corporate_action_conflicts':("""SELECT action_id,security_id,provider,kind,ex_date,details
         FROM corporate_actions WHERE kind IN ('SPLIT','BONUS') AND NOT reconciled
         AND ex_date BETWEEN %s AND %s""",(job.args.first,job.args.last)),
    }
    for name,(sql,args) in queries.items():
        job.update(stage=f'Inventory required source evidence: {name}')
        cur=conn.execute(sql,args);columns=[d.name for d in cur.description];n=0
        target=OUT/f'{name}.jsonl';tmp=target.with_suffix('.tmp')
        with tmp.open('w') as f:
            for row in cur:
                f.write(json.dumps(dict(zip(columns,row)),default=str)+'\n');n+=1
        tmp.replace(target);job.data['counts'][name]=n;job.update()
    job.update(state='EVIDENCE_REQUIRED',stage='Evidence inventory prepared; original dates, scopes and identities require source proof')


def producer_checkpoints():
    states={}
    for task in ('references','financials','attachments','ocr'):
        try:
            state=read_worker_status(OUT/f'{task}.json')
            states[task]={k:state.get(k) for k in ('state','pid','updated_at')}
        except (OSError,ValueError,KeyError):states[task]=dict(state='STARTING')
    return states


def refresh_cached_financials(job,conn):
    """Advance parser generations from local bytes before evaluating financial rules."""
    if not conn.execute('SELECT pg_try_advisory_lock(20261029,1)').fetchone()[0]:
        return dict(state='SOURCE_WORKER_BUSY')
    try:
        from .financials import reparse_cached
        job.update(stage='Reparse cached financial sources under active parser')
        report=reparse_cached(conn,job.archive,guard=job.guard_storage)
        write_progress(OUT/'financial_parser_repair.json',report)
        job.data['counts']['cached_financial_sources_reparsed']=len(report['reparsed'])
        job.data['counts']['financial_source_recovery_pending']=len(report['pending'])
        return report
    finally:conn.execute('SELECT pg_advisory_unlock(20261029,1)')


def analysis(job,conn):
    while True:
        try:reference=read_worker_status(OUT/'references.json')
        except (OSError,ValueError):reference={}
        if reference.get('state') not in (None,'RUNNING','STARTING'):break
        job.update(stage='Waiting for identity refresh before derived analysis');clock.sleep(15)
    while True:
        before=producer_checkpoints()
        from .commercial import pipeline as C
        from .financial import pipeline as F
        from . import companies
        job.guard_storage()
        job.update(stage='Link recovered identities and scan available commercial evidence')
        conn.execute('SELECT pg_advisory_lock(20261029,100)')
        try:print(companies.link_publications(conn),flush=True)
        finally:conn.execute('SELECT pg_advisory_unlock(20261029,100)')
        local=Path.home()/'inflection-jobs/engine/month_local.py'
        if not local.exists():raise RuntimeError('Configured local passage verifier is unavailable')
        conn.execute('SELECT pg_advisory_lock(20261029,101)')
        try:
            print(C.scan(conn,job.args.first,job.args.last),flush=True)
            job.update(stage='Check recovered passages and connect related events')
            job.command(sys.executable,local,f'{job.args.first}:{job.args.last}')
        finally:conn.execute('SELECT pg_advisory_unlock(20261029,101)')
        refresh_cached_financials(job,conn)
        # Repair the newest results before the wider historical scan, after
        # recovered commercial context has been resolved for their mechanisms.
        recent=max(job.args.first,job.args.last-timedelta(days=30))
        job.update(stage='Re-evaluate recent financial decision inputs')
        print(F.scan(conn,recent,job.args.last),flush=True)
        from . import orderbook
        job.update(stage='Refresh source-qualified order book and intake evidence')
        prior=job.args.first-timedelta(days=366)
        print(orderbook.scan(conn,prior,job.args.last),flush=True)
        job.update(stage='Re-evaluate recovered financial evidence')
        print(F.scan(conn,job.args.first,job.args.last),flush=True)
        from .audit_repair import refresh_history_conflicts
        report=refresh_history_conflicts(conn,job.args.first,job.args.last,guard=job.guard_storage,
            progress=lambda current,total:job.update(stage=f'Rebuild source-qualified historical packets: {current}/{total}'))
        write_progress(OUT/'history_packet_repairs.json',report)
        job.data['counts']['historical_packets_refreshed']=report['refreshed']
        job.data['issues']=[i for i in job.data['issues'] if i.get('stage')!='historical_source_packets']
        if report['pending']:
            job.issue(stage='historical_source_packets',status='EVIDENCE_REQUIRED',pending=len(report['pending']))
        job.update(stage='Refresh health report');job.health(conn)
        after=producer_checkpoints()
        running=[task for task,state in after.items() if state['state'] in ('STARTING','RUNNING')]
        if not running:
            if before!=after:
                job.update(stage='Final analysis pass for evidence recovered during the preceding pass')
                continue
            job.update(stage='Refresh the unresolved source-evidence inventory')
            job.command(sys.executable,'-m','inflection.repair_jobs','evidence','--from',job.args.first,'--to',job.args.last)
            break
        job.update(stage='Waiting for additional recovered evidence',waiting_for=running)
        clock.sleep(300)
    job.update(stage='Available evidence processed; unresolved limitations remain in the health report')


def run_task(args):
    OUT.mkdir(parents=True,exist_ok=True)
    with psycopg.connect(os.environ.get('INFLECTION_DSN','postgresql:///inflection'),autocommit=True) as conn:
        deadline=clock.monotonic()+120
        while not conn.execute('SELECT pg_try_advisory_lock(20261029,%s)',(TASKS.index(args.task),)).fetchone()[0]:
            try:previous=read_worker_status(OUT/f'{args.task}.json')
            except (OSError,ValueError):previous={}
            if previous.get('state') in (None,'RUNNING','STARTING') or clock.monotonic()>=deadline:
                print('Repair worker lock already held:',args.task);return 0
            # A stopped client's database session may still be finishing its query.
            clock.sleep(1)
        job=Job(args.task,args)
        try:
            globals()[args.task](job,conn)
            if job.data['state']=='RUNNING':job.update(state='FINISHED_WITH_GAPS' if job.data['issues'] else 'COMPLETE')
        except StorageLimit as exc:job.update(state='STORAGE_LIMIT',error=str(exc))
        except BaseException as exc:
            job.update(state='FAILED',error=f'{type(exc).__name__}: {exc}');raise
    return 0


def main(argv=None):
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('task',choices=('launch',)+TASKS)
    ap.add_argument('--from',dest='first',type=date.fromisoformat,required=True)
    ap.add_argument('--to',dest='last',type=date.fromisoformat,required=True)
    ap.add_argument('--archive',type=Path,default=Path.home()/'inflection-archive')
    ap.add_argument('--cached-only',action='store_true',help='OCR/attachments: process retained bytes without new downloads')
    ap.add_argument('--budget-mb',type=int,default=1024,help='Maximum new archive bytes per worker; no files are purged')
    args=ap.parse_args(argv)
    if args.first>args.last or args.budget_mb<=0:ap.error('Invalid date bounds or storage budget')
    if args.task!='launch':return run_task(args)
    OUT.mkdir(parents=True,exist_ok=True);manifest={}
    # Worker-side source locks prevent duplicate work even if launch is repeated.
    for task in TASKS:
        log=(OUT/f'{task}.log').open('ab')
        command=[sys.executable,'-u','-m','inflection.repair_jobs',task,'--from',str(args.first),'--to',str(args.last),
                 '--archive',str(args.archive),'--budget-mb',str(args.budget_mb)]
        env=dict(os.environ,INFLECTION_VERIFY_MODEL='local-clf-1')
        env.setdefault('INFLECTION_DSN','postgresql:///inflection')
        if task in ('ocr','attachments') and args.cached_only:command.append('--cached-only')
        process=subprocess.Popen(command,cwd=ROOT,stdout=log,stderr=log,stdin=subprocess.DEVNULL,
             env=env,start_new_session=True)
        log.close();manifest[task]=dict(pid=process.pid,log=str(OUT/f'{task}.log'))
    write_progress(OUT/'launch.json',manifest);print(json.dumps(manifest,indent=2))
    return 0

if __name__=='__main__':raise SystemExit(main())
