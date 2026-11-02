from datetime import timedelta
from threading import Barrier,Event
import json
import pytest
from inflection import quality_repair as Q
from test_packets import CUTOFF
from test_packet_process_audit import DAY
from test_triage import _issuer,_evaluation


def test_four_workers_use_distinct_connections_same_cutoff_and_resume(db,tmp_path,monkeypatch):
    issuers=[_issuer(db,symbol) for symbol in ['AAA','BBB','CCC','DDD']]
    for issuer in issuers:_evaluation(db,issuer,CUTOFF-timedelta(days=2),'P1')
    week=dict(week=str(DAY),cohort='recent',original_issuers=list(map(str,issuers)))
    plan=dict(observed_at=CUTOFF.isoformat(),weeks=[week])
    original=Q.P.packet_for;barrier=Barrier(4);observed=[]
    def checked(conn,it,*a,**kw):
        observed.append((conn.info.backend_pid,it['cutoff'],conn.execute('SHOW transaction_isolation').fetchone()[0],
                         conn.execute('SHOW jit').fetchone()[0]))
        barrier.wait(timeout=15)
        return original(conn,it,*a,**kw)
    monkeypatch.setattr(Q.P,'packet_for',checked)
    report=Q.corrected_week(db,week,plan,tmp_path,guard=lambda:None,workers=4)
    assert len({x[0] for x in observed})==4
    assert all(x[1]==CUTOFF and x[2]=='repeatable read' for x in observed)
    assert all(x[3]=='off' for x in observed)
    assert db.execute('SELECT count(*) FROM triage_packets').fetchone()[0]==4
    assert len(Q.read_lines(tmp_path/'cases.jsonl'))==4
    assert Q.corrected_week(db,week,plan,tmp_path,guard=lambda:None,workers=4)==report
    assert db.execute('SELECT count(*) FROM triage_packets').fetchone()[0]==4
    assert db.execute('SELECT count(*) FROM triage_reviews').fetchone()[0]==0
    # A serial rebuild reads the same packets and preserves ranking/report order.
    monkeypatch.setattr(Q.P,'packet_for',original)
    (tmp_path/'serial').mkdir()
    serial=Q.corrected_week(db,week,plan,tmp_path/'serial',guard=lambda:None,workers=1)
    for a,b in zip(report['outcomes'],serial['outcomes']):
        assert (a['issuer_id'],a['packet_hash'],a['status'])==(b['issuer_id'],b['packet_hash'],b['status'])


def test_parallel_failure_yields_completed_peers_before_raising(db,tmp_path,monkeypatch):
    items=[dict(issuer_id=str(n)) for n in range(8)];barrier=Barrier(4);started=[];release=Event()
    def task(dsn,timeout,it,*args):
        started.append(it['issuer_id']);barrier.wait(timeout=10)
        if it['issuer_id']=='0':raise RuntimeError('STORAGE_LIMIT: reserve')
        assert release.wait(timeout=10)
        return it
    original_wait=Q.wait
    def release_peers(*args,**kwargs):
        result=original_wait(*args,**kwargs);release.set();return result
    monkeypatch.setattr(Q,'wait',release_peers)
    monkeypatch.setattr(Q,'case_connection',task)
    results=[]
    with pytest.raises(RuntimeError,match='STORAGE_LIMIT'):
        for result in Q.parallel_cases(db,items,DAY,'audit',tmp_path,lambda:None,4):results.append(result)
    assert sorted(started)==['0','1','2','3']
    assert {x['issuer_id'] for x in results}=={'1','2','3'}


def test_parallel_rejects_duplicate_company_tasks(db,tmp_path):
    with pytest.raises(ValueError,match='Duplicate issuer'):
        list(Q.parallel_cases(db,[dict(issuer_id='same')]*2,DAY,'audit',tmp_path,lambda:None,4))
