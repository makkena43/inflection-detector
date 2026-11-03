"""Repair safety: bounded storage, source backoff, explicit evidence requirements."""
from collections import Counter
from datetime import date
from types import SimpleNamespace

import pytest
from inflection import repair_jobs as R


def test_archive_reuses_bytes_and_stops_before_storage_budget(tmp_path):
    archive=R.BoundedArchive(tmp_path,budget=4,reserve=0)
    a=archive.put(b'1234','a.pdf')
    assert archive.written==4
    assert archive.put(b'1234','copy.pdf').sha256==a.sha256 and archive.written==4
    with pytest.raises(R.StorageLimit):archive.put(b'x','next.pdf')
    assert a.path.read_bytes()==b'1234'


def test_archive_reserves_free_space_before_writing(tmp_path,monkeypatch):
    monkeypatch.setattr(R.shutil,'disk_usage',lambda _:SimpleNamespace(free=10))
    archive=R.BoundedArchive(tmp_path,budget=100,reserve=9)
    with pytest.raises(R.StorageLimit):archive.put(b'1234','a.pdf')
    assert not list(tmp_path.iterdir()) and archive.written==0


class FakeJob:
    def __init__(self):
        self.args=SimpleNamespace(first=date(2026,8,1),last=date(2026,10,28))
        self.archive=SimpleNamespace(written=0)
        self.data={'counts':{},'issues':[],'state':'RUNNING'}
    def update(self,**kwargs):self.data.update(kwargs)
    def issue(self,**kwargs):self.data['issues'].append(kwargs)
    def guard_storage(self):pass


def test_attachment_worker_stops_each_blocked_source_without_retry_loop(monkeypatch):
    from inflection import ingest
    calls=[]
    def download(*args,**kwargs):
        calls.append((args[3],kwargs))
        return Counter(BLOCKED=1)
    monkeypatch.setattr(ingest,'download_pending',download)
    monkeypatch.setattr(ingest,'extract_pending',lambda *a,**k:Counter())
    monkeypatch.setattr(R,'client',lambda *a:None)
    job=FakeJob();R.attachments(job,None)
    assert {ex for ex,_ in calls}=={'NSE','BSE'} and len(calls)==2
    assert all(k['start']==job.args.first and k['end']==job.args.last for _,k in calls)
    assert job.data['state']=='SOURCE_UNAVAILABLE'
    assert len(job.data['issues'])==2


@pytest.mark.parametrize('low_confidence',[True,False])
def test_ocr_preserves_native_artifact_and_blocks_low_confidence_completion(db,tmp_path,monkeypatch,low_confidence):
    import json
    from inflection import ingest
    from inflection.sources.download import Archive
    from test_ingest import nse_row,nse_window
    from test_sources import client
    from pdf_fixtures import make_pdf
    body=make_pdf(tmp_path/'blank.pdf',['']).read_bytes()
    ingest.record_window(db,nse_window([nse_row(1,'https://h/scan.pdf')]))
    c,_=client({'scan.pdf':[(200,body)]});archive=Archive(tmp_path/'archive')
    ingest.download_pending(db,archive,c);ingest.extract_pending(db,archive)
    binary=tmp_path/'output/process_health/vision_ocr_v2';binary.parent.mkdir(parents=True);binary.write_bytes(b'fake')
    monkeypatch.setattr(R,'ROOT',tmp_path)
    data={'pages':['Recovered evidence'],'pages_expected':1,'low_confidence_pages':[1] if low_confidence else []}
    monkeypatch.setattr(R.subprocess,'run',lambda *a,**k:SimpleNamespace(stdout=json.dumps(data)))
    job=FakeJob();job.archive=archive
    R.ocr(job,db)
    state=db.execute('SELECT pipeline_state FROM document_publications').fetchone()[0]
    assert state==('OCR_REQUIRED' if low_confidence else 'TEXT_READY')
    statuses=dict(db.execute('SELECT extraction_method,status FROM text_artifacts'))
    assert statuses['pdfplumber']=='OCR_REQUIRED'
    assert statuses['apple-vision']==('PARTIAL' if low_confidence else 'COMPLETE')
    R.ocr(job,db)
    assert db.execute('SELECT count(*) FROM text_artifacts').fetchone()[0]==2


def test_saved_running_status_does_not_hide_a_stopped_worker(tmp_path,monkeypatch):
    import json
    from inflection import process_health as H
    path=tmp_path/'worker.json';path.write_text(json.dumps({'state':'RUNNING','pid':12345}))
    def missing(*args):raise ProcessLookupError()
    monkeypatch.setattr(H.os,'kill',missing)
    assert H.read_worker_status(path)['state']=='STOPPED'
    assert json.loads(path.read_text())['state']=='RUNNING'  # audit checkpoint stays intact


def test_ocr_does_not_complete_a_zip_with_an_unread_workbook(db,tmp_path,monkeypatch):
    import json
    from inflection import ingest
    from inflection.sources.download import Archive
    from test_ingest import nse_row,nse_window
    from test_sources import client,zip_of
    from pdf_fixtures import make_pdf
    raw=zip_of({'scan.pdf':make_pdf(tmp_path/'blank.pdf',['']).read_bytes(),'unread.xlsx':b'workbook'})
    ingest.record_window(db,nse_window([nse_row(1,'https://h/mixed.zip')]))
    archive=Archive(tmp_path/'archive');c,_=client({'mixed.zip':[(200,raw)]})
    ingest.download_pending(db,archive,c);ingest.extract_pending(db,archive)
    assert db.execute('SELECT pipeline_state FROM document_publications').fetchone()[0]=='OCR_REQUIRED'
    binary=tmp_path/'output/process_health/vision_ocr_v2';binary.parent.mkdir(parents=True);binary.write_bytes(b'fake')
    monkeypatch.setattr(R,'ROOT',tmp_path)
    data={'pages':['Recovered text'],'pages_expected':1,'low_confidence_pages':[]}
    monkeypatch.setattr(R.subprocess,'run',lambda *a,**k:SimpleNamespace(stdout=json.dumps(data)))
    job=FakeJob();job.archive=archive;R.ocr(job,db)
    state,issues=db.execute('SELECT pipeline_state,processing_issues FROM document_publications').fetchone()
    assert state=='PARTIAL_TEXT' and 'ZIP_INCOMPLETE' in issues


def test_archive_budget_stop_still_extracts_downloads_already_saved(monkeypatch):
    from inflection import ingest
    calls=[]
    def extracted(*a,**k):
        calls.append('extract')
        return Counter(TEXT_READY=1)
    def stopped(*a,**k):
        calls.append('download')
        raise R.StorageLimit('archive budget reached')
    monkeypatch.setattr(ingest,'extract_pending',extracted)
    monkeypatch.setattr(ingest,'download_pending',stopped)
    monkeypatch.setattr(R,'client',lambda *a:None)
    job=FakeJob()
    with pytest.raises(R.StorageLimit):R.attachments(job,None)
    assert calls==['extract','download','extract']
    assert job.data['counts']['text:TEXT_READY']==2


def test_cached_ocr_rechecks_filings_that_arrive_from_a_running_producer(db,tmp_path,monkeypatch):
    import json,os
    from inflection import ingest
    from inflection.sources.download import Archive
    from test_ingest import nse_row,nse_window
    from test_sources import client
    from pdf_fixtures import make_pdf
    raw=make_pdf(tmp_path/'scan.pdf',['']).read_bytes()
    ingest.record_window(db,nse_window([nse_row(1,'https://h/scan.pdf')]))
    archive=Archive(tmp_path/'archive');c,_=client({'scan.pdf':[(200,raw)]})
    ingest.download_pending(db,archive,c);ingest.extract_pending(db,archive)
    path=next(archive.root.glob('*/*'));path.unlink()
    binary=tmp_path/'output/process_health/vision_ocr_v2';binary.parent.mkdir(parents=True);binary.write_bytes(b'fake')
    producer=tmp_path/'output/process_health/jobs/attachments.json';producer.parent.mkdir()
    producer.write_text(json.dumps({'state':'RUNNING','pid':os.getpid()}))
    monkeypatch.setattr(R,'ROOT',tmp_path)
    def incoming(*args):
        path.write_bytes(raw)
        producer.write_text(json.dumps({'state':'COMPLETE','pid':os.getpid()}))
    monkeypatch.setattr(R.clock,'sleep',incoming)
    monkeypatch.setattr(R,'client',lambda *a:pytest.fail('Cached-only OCR attempted network access'))
    result={'pages':['Recovered cached evidence'],'pages_expected':1,'low_confidence_pages':[]}
    monkeypatch.setattr(R.subprocess,'run',lambda *a,**k:SimpleNamespace(stdout=json.dumps(result)))
    job=FakeJob();job.archive=archive;job.args.cached_only=True
    R.ocr(job,db)
    assert job.data['counts']['COMPLETE']==1
    assert job.data['issues']==[]
    assert db.execute('SELECT pipeline_state FROM document_publications').fetchone()[0]=='TEXT_READY'


def test_cached_attachment_mode_drains_saved_files_without_resetting_download_budget(monkeypatch):
    from inflection import ingest
    results=iter([Counter(TEXT_READY=2),Counter()])
    monkeypatch.setattr(ingest,'extract_pending',lambda *a,**k:next(results))
    monkeypatch.setattr(ingest,'download_pending',lambda *a,**k:pytest.fail('Cached attachment mode downloaded more bytes'))
    job=FakeJob();job.args.cached_only=True
    R.attachments(job,None)
    assert job.data['counts']['text:TEXT_READY']==2
    assert job.data['state']=='FINISHED_WITH_GAPS'


@pytest.mark.parametrize('initial_packet_gap',[False,True])
def test_analysis_drains_evidence_when_the_last_producer_finishes_mid_pass(monkeypatch,tmp_path,initial_packet_gap):
    from inflection.commercial import pipeline as C
    from inflection.financial import pipeline as F
    from inflection import companies,orderbook
    states={t:dict(state='COMPLETE',pid=1,updated_at='before') for t in ('references','financials','attachments','ocr')}
    states['financials']['state']='RUNNING'
    monkeypatch.setattr(R,'read_worker_status',lambda p:dict(states[p.stem]))
    monkeypatch.setattr(companies,'link_publications',lambda c:{})
    passes=[]
    monkeypatch.setattr(R,'refresh_cached_financials',lambda *a:passes.append('cached_parser'))
    monkeypatch.setattr(C,'scan',lambda *a:passes.append('commercial') or {})
    monkeypatch.setattr(F,'scan',lambda *a:passes.append('financial') or {})
    monkeypatch.setattr(orderbook,'scan',lambda *a:{})
    from inflection import audit_repair
    packet_results=[dict(refreshed=0,pending=[{'packet_id':'pending'}] if initial_packet_gap else []),dict(refreshed=0,pending=[])]
    monkeypatch.setattr(audit_repair,'refresh_history_conflicts',lambda *a,**k:packet_results.pop(0))
    monkeypatch.setattr(R,'write_progress',lambda *a,**k:None)
    local=tmp_path/'inflection-jobs/engine/month_local.py';local.parent.mkdir(parents=True);local.touch()
    monkeypatch.setattr(R.Path,'home',lambda:tmp_path)
    def no_sleep(seconds):raise AssertionError('A completed producer requires a final drain, not a wait')
    monkeypatch.setattr(R.clock,'sleep',no_sleep)
    class Conn:
        def execute(self,*args):return None
    job=FakeJob();job.command=lambda *args:None
    def health(conn):
        # The final producer commits extra evidence after this pass already scanned it.
        states['financials'].update(state='FINISHED_WITH_GAPS',updated_at='after')
    job.health=health
    R.analysis(job,Conn())
    assert passes==['commercial','cached_parser','financial','financial','commercial','cached_parser','financial','financial']
    assert not job.data['issues']
    assert job.data['stage']=='Available evidence processed; unresolved limitations remain in the health report'


def test_ocr_backend_failure_stops_the_batch_without_creating_text(db,tmp_path,monkeypatch):
    from inflection import ingest
    from inflection.sources.download import Archive
    from test_ingest import nse_row,nse_window
    from test_sources import client
    from pdf_fixtures import make_pdf
    raw=make_pdf(tmp_path/'scan.pdf',['']).read_bytes()
    ingest.record_window(db,nse_window([nse_row(1,'https://h/scan.pdf'),nse_row(2,'https://h/scan2.pdf')]))
    archive=Archive(tmp_path/'archive');c,_=client({'scan.pdf':[(200,raw)],'scan2.pdf':[(200,raw)]})
    ingest.download_pending(db,archive,c);ingest.extract_pending(db,archive)
    binary=tmp_path/'output/process_health/vision_ocr_v2';binary.parent.mkdir(parents=True);binary.write_bytes(b'fake')
    monkeypatch.setattr(R,'ROOT',tmp_path)
    def failed(*a,**k):raise R.subprocess.CalledProcessError(1,a,stderr='OCR failed including CPU fallback: e5rtError compute failed')
    monkeypatch.setattr(R.subprocess,'run',failed)
    job=FakeJob();job.archive=archive
    R.ocr(job,db)
    assert job.data['state']=='OCR_UNAVAILABLE' and job.data['counts']['ocr_failed']==1
    assert 'e5rtError' in job.data['issues'][-1]['stderr']
    assert db.execute("SELECT count(*) FROM text_artifacts WHERE extraction_method='apple-vision'").fetchone()[0]==0
