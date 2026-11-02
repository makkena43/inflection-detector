from datetime import date,timedelta
from pathlib import Path
import json
import pytest
from inflection import quality_repair as Q
from inflection.triage import pipeline as T
from inflection.packets import pipeline as P,contents as PC
from test_packet_process_audit import setup,save,DAY
from test_packets import CUTOFF


def scenario(db,tmp_path):
    it,p,_,_=setup(db);stored=save(db,it,p)
    plan=dict(observed_at=CUTOFF.isoformat(),weeks=[dict(week=str(DAY),cohort='recent',original_issuers=[str(it['issuer_id'])])],evidence_publications=[],price_issuers=[],financial_publications=[])
    tmp_path.mkdir(parents=True,exist_ok=True)
    return it,stored,plan


def test_corrected_run_preserves_original_decision_and_packet(db,tmp_path):
    it,old,plan=scenario(db,tmp_path)
    T.record(db,DAY,'ABC','WATCH_MILESTONE',packet_hash=PC.content_hash(old['content']))
    original=db.execute('SELECT to_jsonb(i) FROM triage_shortlist_items i WHERE shortlist_id=%s',(it['shortlist_id'],)).fetchone()[0]
    result=Q.corrected_week(db,plan['weeks'][0],plan,tmp_path,guard=lambda:None)
    assert result['run_tag']=='quality-20261030-recent'
    assert db.execute('SELECT to_jsonb(i) FROM triage_shortlist_items i WHERE shortlist_id=%s',(it['shortlist_id'],)).fetchone()[0]==original
    case=Q.read_lines(tmp_path/'cases.jsonl')[0]
    assert case['packet_id']!=str(old['packet_id'])
    packet=db.execute('SELECT content FROM triage_packets WHERE packet_id=%s',(case['packet_id'],)).fetchone()[0]
    assert packet['manifest']['cutoff']==old['content']['manifest']['cutoff']
    assert not packet['manifest']['nomination_issues']
    assert db.execute('SELECT count(*) FROM triage_reviews').fetchone()[0]==0


def test_corrected_week_resume_is_idempotent_and_retains_outcome_report(db,tmp_path):
    _,_,plan=scenario(db,tmp_path)
    first=Q.corrected_week(db,plan['weeks'][0],plan,tmp_path,guard=lambda:None)
    count=db.execute('SELECT count(*) FROM triage_packets').fetchone()[0]
    second=Q.corrected_week(db,plan['weeks'][0],plan,tmp_path,guard=lambda:None)
    assert second['outcomes']==first['outcomes']
    assert db.execute('SELECT count(*) FROM triage_packets').fetchone()[0]==count
    assert len(Q.read_lines(tmp_path/'cases.jsonl'))==1


def test_pending_screen_does_not_consume_assessments_or_record_rejection(db,tmp_path,monkeypatch):
    _,_,plan=scenario(db,tmp_path)
    monkeypatch.setattr(Q.screen,'triage',lambda *a,**k:dict(triage_action='WATCH_MILESTONE',data_gaps=['FINANCIAL_REVIEW_REQUIRED']))
    Q.corrected_week(db,plan['weeks'][0],plan,tmp_path,guard=lambda:None)
    case=Q.read_lines(tmp_path/'cases.jsonl')[0]
    assert case['status']=='EVIDENCE_OR_RESEARCH_PENDING' and case['recorded'] is None
    assert db.execute("SELECT triage_action FROM triage_shortlist_items i JOIN triage_shortlists s USING(shortlist_id) WHERE s.run_tag='quality-20261030-recent'").fetchone()[0] is None


def test_storage_stop_happens_before_a_new_shortlist_is_written(db,tmp_path):
    _,_,plan=scenario(db,tmp_path)
    def stop():raise RuntimeError('STORAGE_LIMIT: test reserve')
    with pytest.raises(RuntimeError,match='STORAGE_LIMIT'):Q.corrected_week(db,plan['weeks'][0],plan,tmp_path,guard=stop)
    assert db.execute('SELECT count(*) FROM triage_shortlists').fetchone()[0]==1


def test_plan_excludes_future_financial_publications_and_prioritizes_recent_weeks(db,tmp_path):
    it,_,_=scenario(db,tmp_path)
    from inflection.financials import ensure_source
    src=ensure_source(db)
    for key,at in [('before',CUTOFF-timedelta(days=1)),('after',CUTOFF+timedelta(days=1))]:
        db.execute('''INSERT INTO document_publications(source_id,external_id,source_url,published_at,publication_basis,pipeline_state,issuer_id)
           VALUES(%s,%s,'https://source/results.xml',%s,'EXCHANGE_TIMESTAMP','DISCOVERED',%s)''',(src,key,at,it['issuer_id']))
        db.execute("UPDATE document_publications SET document_version_id=(SELECT document_version_id FROM document_versions LIMIT 1),ingested_at=now(),pipeline_state='TEXT_READY' WHERE source_id=%s AND external_id=%s",(src,key))
    plan=Q.build_plan(db,CUTOFF)
    assert len(plan['financial_publications'])==1
    assert plan['constraints']['raw_download_bytes']==0 and plan['constraints']['reserve_gib']==8
    assert plan['weeks'][0]['cohort']=='recent'


def test_retained_price_repair_fills_missing_observations_without_overwriting(db):
    from test_triage import _issuer
    from inflection import prices
    issuer=_issuer(db,'AAA');other=_issuer(db,'BBB')
    sec=db.execute('SELECT security_id FROM securities WHERE issuer_id=%s',(issuer,)).fetchone()[0]
    for day,symbol,value in [(date(2026,3,19),'AAA',100),(date(2026,3,20),'AAA',101),(date(2026,3,20),'BBB',200)]:
        db.execute('''INSERT INTO bhavcopy_rows(exchange,trade_date,code,series,isin,instrument_name,close,volume,source_formats)
           VALUES('NSE',%s,%s,'EQ',%s,%s,%s,1000,'{NSE_UDIFF}')''',(day,symbol,f'INE{symbol}A01011',symbol,value))
    db.execute('''INSERT INTO prices(security_id,trade_date,provider,provider_version,close,adjustment,recorded_at)
      VALUES(%s,'2026-03-19','nse_bhavcopy',%s,90,'UNADJUSTED','2026-03-20')''',(sec,prices.ADAPTER_VERSION))
    assert Q.repair_cached_prices(db,date(2026,3,19),date(2026,3,20),[str(issuer)])==1
    assert db.execute('SELECT close FROM prices WHERE trade_date=%s',(date(2026,3,19),)).fetchone()[0]==90
    assert db.execute('SELECT close FROM prices WHERE trade_date=%s',(date(2026,3,20),)).fetchone()[0]==101
    assert db.execute('SELECT count(*) FROM prices WHERE security_id IN(SELECT security_id FROM securities WHERE issuer_id=%s)',(other,)).fetchone()[0]==0


def test_cached_evidence_uses_separate_status_and_never_downloads(db,tmp_path,monkeypatch):
    _,_,plan=scenario(db,tmp_path)
    ids=[str(r[0]) for r in db.execute('SELECT publication_id FROM document_publications')]
    plan['evidence_publications']=ids
    from inflection import repair_jobs as R
    calls=[]
    def ocr(job,conn):
        assert job.args.cached_only and job.args.publication_ids==ids
        calls.append(1)
    monkeypatch.setattr(R,'ocr',ocr)
    monkeypatch.setattr(R,'client',lambda *a:pytest.fail('Cached evidence attempted a download'))
    monkeypatch.setattr(Q,'storage_guard',lambda:None)
    Q.cached_evidence(db,tmp_path,plan)
    state=json.loads((tmp_path/'evidence_status.json').read_text())
    assert calls and state['raw_download_bytes']==0
    assert state['state'] in ('COMPLETE','FINISHED_WITH_GAPS')



def test_cached_ocr_handles_date_only_filings_and_honors_publication_scope(db,tmp_path,monkeypatch):
    from inflection import ingest,repair_jobs as R
    from inflection.sources.download import Archive
    from test_ingest import nse_row,nse_window
    from test_sources import client
    from pdf_fixtures import make_pdf
    from test_repair_jobs import FakeJob
    from types import SimpleNamespace
    body=make_pdf(tmp_path/'blank.pdf',['']).read_bytes()
    ingest.record_window(db,nse_window([nse_row(1,'https://h/one.pdf'),nse_row(2,'https://h/two.pdf')]))
    archive=Archive(tmp_path/'archive');dl,_=client({'one.pdf':[(200,body)],'two.pdf':[(200,body+b'\n%different-source')]})
    ingest.download_pending(db,archive,dl);ingest.extract_pending(db,archive)
    ids=[r[0] for r in db.execute('SELECT publication_id FROM document_publications ORDER BY external_id')]
    db.execute("UPDATE document_publications SET published_at=NULL,published_date='2026-10-08',publication_basis='DATE_ONLY'")
    binary=tmp_path/'output/process_health/vision_ocr_v2';binary.parent.mkdir(parents=True);binary.write_bytes(b'fake')
    monkeypatch.setattr(R,'ROOT',tmp_path)
    monkeypatch.setattr(R,'client',lambda *a:pytest.fail('Cached OCR attempted network access'))
    monkeypatch.setattr(R.subprocess,'run',lambda *a,**k:SimpleNamespace(stdout=json.dumps(dict(pages=['Recovered evidence'],pages_expected=1,low_confidence_pages=[]))))
    job=FakeJob();job.archive=archive;job.args.cached_only=True;job.args.publication_ids=[ids[0]]
    R.ocr(job,db)
    states=dict(db.execute('SELECT publication_id,pipeline_state FROM document_publications'))
    assert states[ids[0]]=='TEXT_READY' and states[ids[1]]=='OCR_REQUIRED'


def test_coordinator_drains_stopped_producer_analysis_without_resetting_state(db,tmp_path,monkeypatch):
    from test_nonindas_source_audit import seeded_old_parser
    archive=seeded_old_parser(db,tmp_path,monkeypatch)
    pid=str(db.execute('SELECT publication_id FROM document_publications').fetchone()[0])
    peer=tmp_path/'output/process_health/jobs/financial_source_recovery';peer.mkdir(parents=True)
    Q.write(peer/'pending_analysis.json',[pid]);Q.write(peer/'status.json',dict(state='ALLOWANCE_REACHED',pending_analysis=1,counts={'VERIFIED':1}))
    monkeypatch.setattr(Q,'ROOT',tmp_path);monkeypatch.setattr(Q,'storage_guard',lambda:None)
    assert Q.finish_source_analysis(db,tmp_path)
    assert json.loads((peer/'pending_analysis.json').read_text())==[]
    state=json.loads((peer/'status.json').read_text())
    assert state['state']=='ALLOWANCE_REACHED' and state['counts']=={'VERIFIED':1}
    assert state['pending_analysis']==0
    assert len(Q.read_lines(peer/'processing.jsonl'))==1


def test_later_cutoff_cannot_reuse_an_earlier_pending_case_basis():
    it=dict(issuer_id='issuer',cutoff=CUTOFF,priority='P2',evaluation_ids=['same'],trigger_event_version_ids=[])
    assert Q.case_basis(it)!=Q.case_basis(dict(it,cutoff=CUTOFF+timedelta(weeks=1)))


def test_final_recovery_continuation_is_bounded_and_keeps_existing_allowance(tmp_path,monkeypatch):
    from inflection import source_recovery as R
    job=tmp_path/'source';job.mkdir()
    ledger=tmp_path/'ledger.json';Q.write(ledger,dict(archive_bytes_added=50))
    Q.write(job/'status.json',dict(state='SOURCE_UNAVAILABLE'))
    monkeypatch.setattr(R,'JOB',job);monkeypatch.setattr(R,'LEDGER',ledger);monkeypatch.setattr(R,'BUDGET',100)
    calls=[]
    monkeypatch.setattr(R,'run_resilient',lambda *a,**k:calls.append(k) or dict(state='ALLOWANCE_REACHED'))
    assert Q.recover_remaining_sources(None)['state']=='ALLOWANCE_REACHED'
    assert calls==[dict(retry_pending=True,source_retries=3)]
    assert json.loads(ledger.read_text())['archive_bytes_added']==50
    Q.write(ledger,dict(archive_bytes_added=100))
    assert Q.recover_remaining_sources(None)['financial_allowance_used']==100
    assert len(calls)==1


def test_future_case_context_cannot_prove_a_historical_update_priority(db,tmp_path):
    it,_,_=scenario(db,tmp_path);it=dict(it,priority='U0')
    db.execute('''INSERT INTO research_cases(issuer_id,admitted_by,cutoff,created_at,updated_at)
      VALUES(%s,%s,%s,%s,%s)''',(it['issuer_id'],it['evaluation_ids'][0],CUTOFF,CUTOFF+timedelta(days=1),CUTOFF+timedelta(days=1)))
    assert Q.historical_case_issue(db,it)
    db.execute('UPDATE research_cases SET created_at=%s,updated_at=%s',(CUTOFF-timedelta(days=1),CUTOFF-timedelta(days=1)))
    assert Q.historical_case_issue(db,it) is None


def test_packets_wait_even_when_active_recovery_has_no_pending_batch(tmp_path,monkeypatch):
    monkeypatch.setattr(Q,'producers',lambda job:{'financial_recovery':'RUNNING','cached_evidence':'FINISHED_WITH_GAPS'})
    assert Q.finish_source_analysis(None,tmp_path) is False
    monkeypatch.setattr(Q,'producers',lambda job:{'cached_evidence':'RUNNING'})
    assert Q.finish_source_analysis(None,tmp_path) is False


def test_ocr_restart_keeps_original_spend_and_cannot_reset_after_cleanup(tmp_path,monkeypatch):
    import json
    from inflection.sources.download import DocumentResourceLimit
    monkeypatch.setattr(Q,'storage_guard',lambda:None)
    ledger=tmp_path/'ocr.json';ledger.write_text(json.dumps(dict(archive_bytes_added=6,counts={'PARTIAL':410})))
    archive=Q.CumulativeOCRArchive(tmp_path/'archive',ledger=ledger,budget=10)
    stored=archive.put(b'1234','scan.pdf')
    assert archive.written==4 and archive.remaining_allowance()==0
    assert json.loads(ledger.read_text())['counts']=={'PARTIAL':410}
    restarted=Q.CumulativeOCRArchive(archive.root,ledger=ledger,budget=10)
    assert restarted.put(b'1234','scan.pdf').sha256==stored.sha256
    assert restarted.written==0
    stored.path.unlink()
    import pytest
    with pytest.raises(DocumentResourceLimit):restarted.put(b'1234','scan.pdf')
    assert json.loads(ledger.read_text())['archive_bytes_added']==10


def test_rechecked_packet_persists_exact_nested_decimal_and_resumes(db,tmp_path):
    from decimal import Decimal
    it,old,plan=scenario(db,tmp_path)
    content=json.loads(json.dumps(old['content']))
    content['source_recheck']={'amount':Decimal('12345678901234567890.0123456789'),'nested':[Decimal('0.000000001')]}
    result=P.store_packet(db,it,content,PC.TOKEN_BUDGET)
    persisted=db.execute('SELECT content,content_hash FROM triage_packets WHERE packet_id=%s',(result['packet_id'],)).fetchone()
    assert result['content']==persisted[0]
    assert result['content']['source_recheck']['amount']=='12345678901234567890.0123456789'
    assert Decimal(result['content']['source_recheck']['nested'][0])==Decimal('0.000000001')
    assert P._input_hash(result['content'])==P._input_hash(content)
    assert content['source_recheck']['amount']==Decimal('12345678901234567890.0123456789')
    assert P.store_packet(db,it,content,PC.TOKEN_BUDGET)['status']=='UNCHANGED'
