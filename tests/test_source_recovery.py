from pathlib import Path
from hashlib import sha256
import json
import pytest
from inflection.source_recovery import RecoveryArchive,AllowanceReached,process_body
from inflection.coverage_repair import write_progress


def store(tmp_path,spent=2,budget=6):
    ledger=tmp_path/'ledger.json';write_progress(ledger,dict(archive_bytes_added=spent))
    return RecoveryArchive(tmp_path/'archive',ledger,budget,guard=lambda:None),ledger


def test_recovery_preserves_cumulative_allowance_and_deduplicates(tmp_path):
    s,l=store(tmp_path);body=b'1234';digest=sha256(body).hexdigest()
    assert s.store(body,digest)==4 and json.loads(l.read_text())['archive_bytes_added']==6
    assert s.store(body,digest)==0
    with pytest.raises(AllowanceReached):s.store(b'x',sha256(b'x').hexdigest())
    assert json.loads(l.read_text())['archive_bytes_added']==6


def test_source_hash_mismatch_never_writes_or_spends(tmp_path):
    s,l=store(tmp_path)
    with pytest.raises(ValueError,match='HASH_MISMATCH'):s.store(b'wrong',sha256(b'1234').hexdigest())
    assert json.loads(l.read_text())['archive_bytes_added']==2
    assert not s.archive.root.exists()


def test_interrupted_reservation_can_finish_without_resetting_allowance(tmp_path):
    s,l=store(tmp_path);body=b'1234';digest=sha256(body).hexdigest()
    write_progress(l,dict(archive_bytes_added=6,source_recovery_reservations={digest:dict(bytes=4,stored=False)}))
    assert s.available(digest)==4 and s.store(body,digest)==4
    assert json.loads(l.read_text())['archive_bytes_added']==6


def test_owner_cleanup_does_not_make_another_copy_free(tmp_path):
    s,l=store(tmp_path);body=b'1234';digest=sha256(body).hexdigest();s.store(body,digest)
    (s.archive.root/digest[:2]/digest).unlink()
    assert s.available(digest)==0
    with pytest.raises(AllowanceReached):s.store(body,digest)
    assert json.loads(l.read_text())['archive_bytes_added']==6


def test_verified_bytes_process_without_retained_raw_file_and_keep_disclosure_clock(db,tmp_path,monkeypatch):
    from test_nonindas_source_audit import seeded_old_parser,nonindas
    from inflection import financials
    archive=seeded_old_parser(db,tmp_path,monkeypatch)
    row=db.execute('SELECT publication_id,published_at,ingested_at FROM document_publications').fetchone()
    digest=db.execute('SELECT sha256 FROM document_versions').fetchone()[0]
    (archive.root/digest[:2]/digest).unlink() # Owner retention does not prevent in-memory reprocessing.
    body=nonindas();entry=dict(sha256=digest,publication_ids=[str(row[0])])
    assert process_body(db,entry,body,guard=lambda:None)==[str(row[0])]
    assert db.execute('SELECT publication_id,published_at,ingested_at FROM document_publications').fetchone()==row
    n=db.execute('SELECT count(*) FROM financial_facts').fetchone()[0]
    assert process_body(db,entry,body,guard=lambda:None)==[str(row[0])]
    assert db.execute('SELECT count(*) FROM financial_facts').fetchone()[0]==n


def test_changed_source_metadata_cannot_receive_old_verified_bytes(db,tmp_path,monkeypatch):
    from test_nonindas_source_audit import seeded_old_parser,nonindas
    seeded_old_parser(db,tmp_path,monkeypatch)
    pid=db.execute('SELECT publication_id FROM document_publications').fetchone()[0]
    body=b'<other/>';entry=dict(sha256=sha256(body).hexdigest(),publication_ids=[str(pid)])
    with pytest.raises(ValueError,match='METADATA_CHANGED'):process_body(db,entry,body,guard=lambda:None)


def test_existing_bytes_finalize_interrupted_reservation_before_owner_cleanup(tmp_path):
    s,l=store(tmp_path);body=b'1234';digest=sha256(body).hexdigest()
    s.archive.put(body,'source.xml')
    write_progress(l,dict(archive_bytes_added=6,source_recovery_reservations={digest:dict(bytes=4,stored=False)}))
    assert s.store(body,digest)==0
    (s.archive.root/digest[:2]/digest).unlink()
    assert s.available(digest)==0
    with pytest.raises(AllowanceReached):s.store(body,digest)


def test_complete_job_persists_list_checkpoints_and_resumes_without_redownload(db,tmp_path,monkeypatch):
    from test_nonindas_source_audit import seeded_old_parser,nonindas
    from inflection import source_recovery as R
    archive=seeded_old_parser(db,tmp_path,monkeypatch);body=nonindas()
    digest=sha256(body).hexdigest();(archive.root/digest[:2]/digest).unlink()
    ledger=tmp_path/'ledger.json';write_progress(ledger,dict(archive_bytes_added=2))
    monkeypatch.setattr(R,'LEDGER',ledger);monkeypatch.setattr(R,'BUDGET',len(body)+3)
    monkeypatch.setattr(R,'storage_guard',lambda:None);monkeypatch.setattr(R.time,'sleep',lambda _:None)
    calls=[]
    monkeypatch.setattr(R,'download',lambda entry,capacity:calls.append(entry['sha256']) or body)
    scans=[];monkeypatch.setattr(R.F,'scan',lambda c,publication_ids:scans.extend(publication_ids) or {})
    monkeypatch.setattr(R,'refresh_packets',lambda *a:[])
    job=tmp_path/'job';state=R.run(db,job,archive.root)
    assert state['state']=='COMPLETE' and state['counts']=={'VERIFIED':1}
    assert isinstance(json.loads((job/'plan.json').read_text()),list)
    assert json.loads((job/'pending_analysis.json').read_text())==[] and scans
    assert len(calls)==1 and json.loads(ledger.read_text())['archive_bytes_added']==len(body)+2
    assert R.run(db,job,archive.root)['completed']==1 and len(calls)==1


def test_explicit_resume_retries_only_connection_failures_without_resetting_spend(db,tmp_path,monkeypatch):
    from test_nonindas_source_audit import seeded_old_parser,nonindas
    from inflection import source_recovery as R
    archive=seeded_old_parser(db,tmp_path,monkeypatch);body=nonindas();digest=sha256(body).hexdigest()
    (archive.root/digest[:2]/digest).unlink()
    ledger=tmp_path/'ledger.json';write_progress(ledger,dict(archive_bytes_added=2))
    monkeypatch.setattr(R,'LEDGER',ledger);monkeypatch.setattr(R,'BUDGET',len(body)+3)
    monkeypatch.setattr(R,'storage_guard',lambda:None);monkeypatch.setattr(R.time,'sleep',lambda _:None)
    def unavailable(*args):raise OSError('DNS resolution temporarily unavailable')
    monkeypatch.setattr(R,'download',unavailable)
    monkeypatch.setattr(R.F,'scan',lambda *a,**k:{})
    monkeypatch.setattr(R,'refresh_packets',lambda *a:[])
    job=tmp_path/'job'
    assert R.run(db,job,archive.root)['counts']=={'PENDING':1}
    assert json.loads(ledger.read_text())['archive_bytes_added']==2
    monkeypatch.setattr(R,'download',lambda *args:body)
    assert R.run(db,job,archive.root,retry_pending=True)['counts']=={'VERIFIED':1}
    assert json.loads(ledger.read_text())['archive_bytes_added']==len(body)+2
    assert len((job/'receipts.jsonl').read_text().splitlines())==2
    assert not R.retryable_connection_failure({'status':'PENDING','reason':'SOURCE_HASH_MISMATCH'})


def test_bounded_network_backoff_keeps_spend_and_uses_saved_receipts(tmp_path,monkeypatch):
    from inflection import source_recovery as R
    pending=dict(status='PENDING',reason='DNS resolution temporarily unavailable')
    (tmp_path/'receipts.jsonl').write_text(json.dumps(pending)+'\n')
    calls=[];sleeps=[]
    def run(conn,job,retry_pending=False):
        calls.append(retry_pending)
        return dict(state='SOURCE_UNAVAILABLE' if len(calls)==1 else 'COMPLETE',financial_allowance_used=12345,counts={'VERIFIED':10})
    monkeypatch.setattr(R,'run',run);monkeypatch.setattr(R.time,'sleep',sleeps.append)
    state=R.run_resilient(None,tmp_path,source_retries=3)
    assert state['state']=='COMPLETE' and state['financial_allowance_used']==12345
    assert calls==[False,True] and sleeps==[60]
