"""Late evidence and repair outcomes must not be mistaken for completed reviews."""
from copy import deepcopy
from datetime import timedelta
from inflection import queue
from inflection.triage import pipeline as T,rules as R
from inflection.packets import pipeline as P,contents as C
from test_triage import _issuer,_evaluation,WEEK,CUTOFF


def evaluate(db,issuer,at,priority='P2'):
    _evaluation(db,issuer,at,priority)
    return str(db.execute('SELECT evaluation_id FROM candidate_evaluations WHERE issuer_id=%s ORDER BY created_at DESC,evaluation_id LIMIT 1',(issuer,)).fetchone()[0])


def initial(db,action='WATCH_MILESTONE'):
    issuer=_issuer(db,'AAA');eid=evaluate(db,issuer,CUTOFF-timedelta(days=3))
    T.build(db,WEEK,now=CUTOFF)
    assert T.record(db,WEEK,'AAA',action)['triage_action']==action
    return issuer,eid


def test_late_assessment_of_old_filing_reenters_and_bypasses_cooldown(db):
    issuer,old=initial(db);late=evaluate(db,issuer,CUTOFF-timedelta(days=2))
    result=T.build(db,WEEK+timedelta(weeks=1),dry_run=True,now=CUTOFF+timedelta(weeks=1))
    assert result['shortlist'][0]['symbol']=='AAA' and result['shortlist'][0]['slot']=='RANKED'
    lines=queue.lines(db,end=CUTOFF+timedelta(weeks=1),since={issuer:CUTOFF},reviewed=T.reviewed_evaluations(db,CUTOFF+timedelta(weeks=1)))
    assert lines[0]['evaluation_ids']==[late] and lines[0]['reassessment_required']
    assert old not in lines[0]['evaluation_ids']


def test_assessment_exactly_at_previous_exclusive_cutoff_is_not_consumed(db):
    issuer,old=initial(db);new=evaluate(db,issuer,CUTOFF,'P1')
    nxt=T.build(db,WEEK+timedelta(weeks=1),dry_run=True,now=CUTOFF+timedelta(weeks=1))
    assert nxt['shortlist'][0]['priority']=='P1'
    lines=queue.lines(db,end=CUTOFF+timedelta(weeks=1),since={issuer:CUTOFF},reviewed={issuer:{old}})
    assert lines[0]['evaluation_ids']==[new]


def test_consumption_includes_all_previous_reviews_not_only_the_latest(db):
    issuer,old=initial(db);new=evaluate(db,issuer,CUTOFF+timedelta(days=2),'P1')
    T.build(db,WEEK+timedelta(weeks=1),now=CUTOFF+timedelta(weeks=1))
    T.record(db,WEEK+timedelta(weeks=1),'AAA','WATCH_MILESTONE')
    at=CUTOFF+timedelta(weeks=2)
    assert T.reviewed_evaluations(db,at)[issuer]=={old,new}
    assert T.build(db,WEEK+timedelta(weeks=2),dry_run=True,now=at)['shortlist']==[]


def test_data_repair_neither_consumes_evidence_nor_starts_cooldown(db):
    issuer,eid=initial(db,'DATA_REPAIR');at=CUTOFF+timedelta(weeks=1)
    assert issuer not in T._last_triage(db,at)
    assert issuer not in T.reviewed_evaluations(db,at)
    assert T.build(db,WEEK+timedelta(weeks=1),dry_run=True,now=at)['shortlist'][0]['slot']=='RANKED'


def test_budget_defer_does_not_consume_assessments(db):
    issuer,eid=initial(db,'DEFER_BUDGET');at=CUTOFF+timedelta(weeks=1)
    assert issuer not in T.reviewed_evaluations(db,at)
    assert T.build(db,WEEK+timedelta(weeks=1),dry_run=True,now=at)['shortlist'][0]['waiting_days']==10


def test_future_recorded_decision_is_not_consumed_in_actual_replay(db):
    issuer,eid=initial(db);at=CUTOFF+timedelta(weeks=1)
    assert T.reviewed_evaluations(db,at)[issuer]=={eid}
    assert T.reviewed_evaluations(db,at,'ACTUAL_SYSTEM_REPLAY')=={}


def test_consumed_packet_references_remain_exact_after_rebuild(db):
    from test_packet_process_audit import setup,save,DAY
    it,p,_,_=setup(db);stored=save(db,it,p)
    T.record(db,DAY,'ABC','WATCH_MILESTONE',packet_hash=C.content_hash(stored['content']))
    original=set(p['manifest']['evaluation_ids']);changed=deepcopy(p)
    changed['manifest']['evaluation_ids']=[];changed['why_now']['reason']='Later rebuild'
    save(db,it,changed)
    assert T.reviewed_evaluations(db,it['cutoff']+timedelta(weeks=1))[it['issuer_id']]==original


def test_actual_replay_discovers_late_old_assessment_at_its_observation_time():
    from test_corroboration_processing import row,AT
    from inflection.replay.pipeline import _queue_weeks
    from datetime import date
    a=row('first','FINANCIAL',at=AT,priority='P2')
    b=list(row('late','FINANCIAL',at=AT-timedelta(days=2),priority='P2'));b[14]=AT+timedelta(days=10)
    weeks=[(date(2026,8,31),AT+timedelta(days=6)),(date(2026,9,7),AT+timedelta(days=13)),(date(2026,9,14),AT+timedelta(days=20))]
    _,items=_queue_weeks([a,tuple(b)],weeks,'ACTUAL_SYSTEM_REPLAY',R.policy(),None)
    assert [i['week_start'] for i in items if i['shortlisted']]==[date(2026,8,31),date(2026,9,7)]
    assert items[-1]['evaluation_ids']==['late']
