"""OCR quality is a source limitation, not a verified positive or negative decision."""
import json
from types import SimpleNamespace
import pytest
from inflection.ocr_cpu import confidence_issues
from inflection import repair_jobs as R
from test_repair_jobs import FakeJob


def confidence(words,average=96):
    return dict(confidence=average,tsv='level\tpage\tblock\tpar\tline\tword\tl\tt\tw\th\tconf\ttext\n'+
                '\n'.join(f'5\t1\t1\t1\t1\t{i}\t0\t0\t0\t0\t{score}\t{text}' for i,(text,score) in enumerate(words)))


def test_numeric_confidence_cannot_be_hidden_by_high_page_average():
    data=confidence([('Order',99),('INR',99),('100',75),('crore',99)],average=98)
    assert 'numeric text requires verification' in confidence_issues(data)
    assert confidence_issues(confidence([('Order',99),('INR',99),('100',99),('crore',99)]))==[]


@pytest.mark.parametrize('data',[{'confidence':99},{'confidence':float('nan'),'tsv':''},confidence([('text',99)],70)])
def test_missing_word_proof_or_low_page_confidence_is_not_complete(data):
    assert confidence_issues(data)


@pytest.mark.parametrize('invalid',[dict(pages_expected=2),dict(low_confidence_pages=[2]),dict(pages=[123])])
def test_malformed_ocr_result_cannot_create_a_ready_artifact(db,tmp_path,monkeypatch,invalid):
    from inflection import ingest
    from inflection.sources.download import Archive
    from test_ingest import nse_row,nse_window
    from test_sources import client
    from pdf_fixtures import make_pdf
    raw=make_pdf(tmp_path/'scan.pdf',['']).read_bytes()
    ingest.record_window(db,nse_window([nse_row(1,'https://h/scan.pdf')]))
    archive=Archive(tmp_path/'archive');c,_=client({'scan.pdf':[(200,raw)]})
    ingest.download_pending(db,archive,c);ingest.extract_pending(db,archive)
    binary=tmp_path/'output/process_health/vision_ocr_v2';binary.parent.mkdir(parents=True);binary.write_bytes(b'fake')
    monkeypatch.setattr(R,'ROOT',tmp_path)
    data=dict(pages=['Recovered source'],pages_expected=1,low_confidence_pages=[]);data.update(invalid)
    monkeypatch.setattr(R.subprocess,'run',lambda *a,**k:SimpleNamespace(stdout=json.dumps(data)))
    job=FakeJob();job.archive=archive;R.ocr(job,db)
    assert job.data['counts']['ocr_failed']==1
    assert db.execute("SELECT count(*) FROM text_artifacts WHERE extraction_method='apple-vision'").fetchone()[0]==0
    assert db.execute('SELECT pipeline_state FROM document_publications').fetchone()[0]=='OCR_REQUIRED'


def test_partial_ocr_cannot_support_verified_screening_or_financial_mechanism(db):
    from inflection.commercial import pipeline as C
    from inflection.financial import pipeline as F
    from inflection.packets import pipeline as P
    from inflection.orderbook_evidence import awards_totals
    from inflection.triage.screen import triage,prior_orders
    from test_commercial import _seed,_filing,PO
    from test_event_history_processing import at
    from test_detection_audit import packet
    issuer,src=_seed(db);tid=_filing(db,issuer,src,4000,at('2026-09-01'),[PO])
    # Append a new OCR reading; the original native source remains immutable.
    aid=db.execute("""INSERT INTO text_artifacts(document_version_id,extraction_method,extraction_version,status,
         pages_expected,pages_processed,pages_with_text,text_sha256,quality_issues,created_by)
         SELECT document_version_id,'tesseract-cpu','test-cpu','PARTIAL',1,1,1,'hash',
         ARRAY['OCR page 1: numeric text requires verification'],'test' FROM text_artifacts
         WHERE text_artifact_id=%s RETURNING text_artifact_id""",(tid,)).fetchone()[0]
    db.execute('INSERT INTO text_pages(text_artifact_id,page_no,body) VALUES(%s,1,%s)',(aid,PO))
    C.scan(db);C.resolve(db)
    vid=db.execute('SELECT event_version_id FROM event_versions LIMIT 1').fetchone()[0]
    it=dict(issuer_id=issuer,trigger_event_version_ids=[vid],cutoff=at('2026-09-15'),mode='PUBLIC_INFORMATION_RECONSTRUCTION')
    events=P._events(db,it)
    assert events[0]['details']['ocr_verification_required']
    p=packet();p['events']=events
    result=triage(p)
    assert result['triage_action']=='WATCH_MILESTONE' and 'OCR_SOURCE_VERIFICATION_REQUIRED' in result['data_gaps']
    assert all(not m.explains('OPERATING') for m in F._mechanisms(db,issuer,it['cutoff']))
    assert awards_totals(db,issuer,it['cutoff'])==(None,None)
    assert prior_orders(db,issuer,it['cutoff'])==([],1)
