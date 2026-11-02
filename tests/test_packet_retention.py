from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
from threading import Event
import psycopg
import pytest
from psycopg.types.json import Jsonb
from inflection import packet_retention as R
from inflection.packets import pipeline as P,contents as C
from inflection.triage import pipeline as T
from test_packet_process_audit import setup,save,DAY


def versions(db):
    it,body,_,_=setup(db);a=save(db,it,body)
    b=deepcopy(body);b['why_now']['reason']='Second version';b=save(db,it,b)
    c=deepcopy(body);c['why_now']['reason']='Latest version';c=save(db,it,c)
    return it,a,b,c


def review(conn,it,packet_hash):
    conn.execute('''INSERT INTO triage_reviews(week_start,issuer_id,label,packet_hash,decided_by,
        triage_action,rationale,result,source) VALUES(%s,%s,'ABC',%s,'retention test',
        'WATCH_MILESTONE','historical review','{}','test')''',(DAY,it['issuer_id'],packet_hash))


def test_removes_only_old_unreferenced_payloads_keeps_links_and_generation(db):
    it,a,b,c=versions(db)
    # Bind the oldest version as recorded decision evidence.
    db.execute('UPDATE triage_shortlist_items SET packet_id=%s WHERE shortlist_id=%s AND issuer_id=%s',
               (a['packet_id'],it['shortlist_id'],it['issuer_id']))
    rows=R.batch(db)
    assert [r['packet_id'] for r in rows]==[str(b['packet_id'])]
    old=db.execute('SELECT content,markdown,content_hash,payload_purged_at FROM triage_packets WHERE packet_id=%s',(b['packet_id'],)).fetchone()
    assert old[0]['retention']['original_content_hash']==old[2] and old[1]=='' and old[3]
    assert db.execute('SELECT content FROM triage_packets WHERE packet_id=%s',(a['packet_id'],)).fetchone()[0]==a['content']
    assert P._latest(db,it['shortlist_id'],it['issuer_id'])[0]==c['packet_id']
    assert db.execute('SELECT supersedes_id FROM triage_packets WHERE packet_id=%s',(c['packet_id'],)).fetchone()[0]==b['packet_id']
    assert R.batch(db)==[]
    d=deepcopy(c['content']);d['why_now']['reason']='Future read'
    newest=save(db,it,d)
    assert newest['content']['manifest']['generation']==4
    assert db.execute('SELECT count(*) FROM packet_payload_purges').fetchone()[0]==1


def test_hash_only_reviews_and_recorded_audit_hashes_are_protected(db):
    it,a,b,c=versions(db)
    review(db,it,C.content_hash(a['content']))
    db.execute("INSERT INTO audit_log(actor,actor_kind,action,details) VALUES('tester','MODEL','TRIAGE_RECORDED',%s)",
               (Jsonb(dict(packet_hash=C.content_hash(b['content']))),))
    assert R.batch(db)==[]


def test_ordinary_mutation_stays_forbidden_and_removed_packets_cannot_bind_decisions(db):
    it,a,b,c=versions(db)
    with pytest.raises(psycopg.errors.RaiseException,match='append-only'):
        db.execute('UPDATE triage_packets SET markdown=\'changed\' WHERE packet_id=%s',(c['packet_id'],))
    R.batch(db)
    with pytest.raises(psycopg.errors.RaiseException,match='removed'):
        db.execute('UPDATE triage_shortlist_items SET packet_id=%s WHERE shortlist_id=%s AND issuer_id=%s',
                   (b['packet_id'],it['shortlist_id'],it['issuer_id']))
    with pytest.raises(psycopg.errors.RaiseException,match='removed'):review(db,it,C.content_hash(a['content']))


def test_concurrent_review_cannot_bind_a_payload_being_removed(db):
    it,a,b,c=versions(db);started=Event()
    def competing():
        with psycopg.connect(db.info.dsn,autocommit=True) as conn:
            started.set();review(conn,it,C.content_hash(a['content']))
    with ThreadPoolExecutor(max_workers=1) as pool:
        with db.transaction():
            db.execute('SELECT packet_id FROM triage_packets WHERE packet_id=%s FOR UPDATE',(a['packet_id'],))
            R.batch(db)
            future=pool.submit(competing);assert started.wait(5)
        with pytest.raises(psycopg.errors.RaiseException,match='removed'):future.result(timeout=10)


def test_completed_old_week_is_removable_but_active_week_and_latest_company_stay(db,tmp_path):
    from datetime import timedelta
    from inflection import quality_repair as Q
    from inflection.triage import screen
    from test_packets import CUTOFF
    from test_triage import _issuer,_evaluation
    issuer=_issuer(db,'AAA');_evaluation(db,issuer,CUTOFF-timedelta(days=2),'P1')
    first=dict(week=str(DAY),cohort='recent',original_issuers=[str(issuer)])
    second=dict(first,week=str(DAY+timedelta(days=7)))
    plan=dict(observed_at=(CUTOFF+timedelta(days=7)).isoformat(),weeks=[first,second])
    a=Q.corrected_week(db,first,plan,tmp_path,guard=lambda:None)['outcomes'][0]
    b=Q.corrected_week(db,second,plan,tmp_path,guard=lambda:None)['outcomes'][0]
    assert R.batch(db)==[] # No completion receipt: neither can be removed.
    Q.append(tmp_path/'stages.jsonl',dict(key='week/recent/'+str(DAY)))
    assert R.register_completed_weeks(db,tmp_path)==1
    assert [r['packet_id'] for r in R.batch(db)]==[a['packet_id']]
    old=db.execute('SELECT content FROM triage_packets WHERE packet_id=%s',(a['packet_id'],)).fetchone()[0]
    result=screen.triage(old,use_llm=False)
    assert result['triage_action']=='WATCH_MILESTONE' and result['data_gaps']
    assert db.execute('SELECT payload_purged_at FROM triage_packets WHERE packet_id=%s',(b['packet_id'],)).fetchone()[0] is None


def test_cleanup_run_persists_receipts_and_vacuums_without_changing_latest(db,tmp_path,monkeypatch):
    it,a,b,c=versions(db)
    monkeypatch.setattr(R,'storage_guard',lambda:None)
    result=R.run(db,tmp_path/'retention',apply=True,quality_job=tmp_path/'quality')
    assert result['state']=='COMPLETE' and result['removed_payloads']==2
    assert len((tmp_path/'retention/receipts.jsonl').read_text().splitlines())==2
    assert P._latest(db,it['shortlist_id'],it['issuer_id'])[0]==c['packet_id']
