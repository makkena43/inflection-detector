"""New source readings must neither create a processing hole nor leave ghosts."""
from datetime import datetime,timezone
from copy import deepcopy
import pytest
from inflection import queue
from inflection.commercial import pipeline as C,vocabulary as V
from inflection.packets import pipeline as P
from test_commercial import _seed,_filing,PO
from test_event_history_processing import at


def original(db,monkeypatch):
    issuer,src=_seed(db);tid=_filing(db,issuer,src,5000,at('2026-01-01'),[PO])
    with monkeypatch.context() as old:
        old.setattr(V,'RULES_VERSION','legacy-handover');C.scan(db);C.resolve(db)
    return issuer,src,tid


def replacement(db,tid,text,status='COMPLETE'):
    aid=db.execute('''INSERT INTO text_artifacts(document_version_id,extraction_method,extraction_version,
        status,pages_expected,pages_processed,pages_with_text,created_at)
        SELECT document_version_id,'corrected-reader',gen_random_uuid()::text,%s,1,1,1,clock_timestamp()
        FROM text_artifacts WHERE text_artifact_id=%s RETURNING text_artifact_id''',(status,tid)).fetchone()[0]
    db.execute('INSERT INTO text_pages(text_artifact_id,page_no,body) VALUES(%s,1,%s)',(aid,text));return aid


def test_new_rules_do_not_retire_old_assessment_while_mentions_are_unresolved(db,monkeypatch):
    issuer,_,_=original(db,monkeypatch)
    old=queue.evaluation_rows(db)[0][10]
    C.scan(db)
    assert [r[10] for r in queue.evaluation_rows(db)]==[old]
    assert any(m.explains('OPERATING') for m in __import__('inflection.financial.pipeline',fromlist=['_mechanisms'])._mechanisms(db,issuer,at('2026-02-01')))
    C.resolve(db)
    rows=queue.evaluation_rows(db)
    assert rows and all(r[10]!=old for r in rows)


def test_completed_zero_match_reread_withdraws_public_but_not_earlier_actual_view(db,monkeypatch):
    issuer,_,tid=original(db,monkeypatch)
    old=queue.evaluation_rows(db)[0];before=datetime.now(timezone.utc)
    monkeypatch.setattr(C,'extract_document',lambda pages:([],0));C.scan(db)
    after=datetime.now(timezone.utc)
    assert queue.evaluation_rows(db)==[]
    rows=queue.evaluation_rows(db,include_superseded=True);history=queue.commercial_checkpoint_history(db,after)
    assert [r[10] for r in queue.actual_rows(rows,before,commercial_history=history)]==[old[10]]
    assert queue.actual_rows(rows,after,commercial_history=history)==[]


@pytest.mark.parametrize('status,withdraw',[('COMPLETE',True),('PARTIAL',False)])
def test_same_rules_new_text_zero_match_replaces_only_complete_source_reading(db,monkeypatch,status,withdraw):
    issuer,src=_seed(db);tid=_filing(db,issuer,src,5001,at('2026-01-01'),[PO]);C.scan(db);C.resolve(db)
    old=queue.evaluation_rows(db)[0];replacement(db,tid,'The registered office address remains unchanged.',status)
    C.scan(db)
    assert bool(queue.evaluation_rows(db)) is not withdraw
    vid=old[12][0]
    it=dict(issuer_id=issuer,cutoff=at('2026-02-01'),mode='PUBLIC_INFORMATION_RECONSTRUCTION',trigger_event_version_ids=[vid])
    event=P._events(db,it)[0]
    assert bool(event['details'].get('source_reading_withdrawn'))==withdraw
    if withdraw:assert event['amount'] is None


def test_same_rules_reaffirmation_keeps_the_existing_nomination(db):
    issuer,src=_seed(db);tid=_filing(db,issuer,src,5002,at('2026-01-01'),[PO]);C.scan(db);C.resolve(db)
    old=queue.evaluation_rows(db)[0][10]
    replacement(db,tid,PO);C.scan(db);result=C.resolve(db)
    assert result['REPETITION']==1
    assert [r[10] for r in queue.evaluation_rows(db)]==[old]


def test_missing_issuer_reread_cannot_withdraw_a_known_nomination(db,monkeypatch):
    issuer,_,tid=original(db,monkeypatch)
    db.execute('''INSERT INTO commercial_scans(text_artifact_id,rules_version,document_version_id,status)
       SELECT text_artifact_id,%s,document_version_id,'NO_ISSUER' FROM text_artifacts WHERE text_artifact_id=%s''',
       (V.RULES_VERSION,tid))
    assert len(queue.evaluation_rows(db))==1


def test_all_rejected_interpretation_invalidates_financial_cache_without_new_event(db,monkeypatch):
    from inflection.financial import pipeline as F
    from test_financial_route import _seed as results_seed,_results,BASE
    from datetime import date
    issuer,src=results_seed(db)
    announcements=db.execute("INSERT INTO sources(name,kind,access_policy) VALUES('nse_announcements','announcements','test') RETURNING source_id").fetchone()[0]
    _filing(db,issuer,announcements,5003,at('2025-10-01'),[PO])
    with monkeypatch.context() as old:
        old.setattr(V,'RULES_VERSION','legacy-handover');C.scan(db);C.resolve(db)
    _results(db,issuer,src,10,date(2024,9,30),at('2024-11-07'),**BASE)
    pid=_results(db,issuer,src,11,date(2025,9,30),at('2025-11-07'),**{**BASE,'total_expenses':860})
    C.scan(db);F.scan(db)
    first=db.execute('SELECT evaluation_id FROM financial_scans WHERE publication_id=%s',(pid,)).fetchone()[0]
    assert db.execute('SELECT priority_class FROM candidate_evaluations WHERE evaluation_id=%s',(first,)).fetchone()[0]=='P2'
    events=db.execute('SELECT count(*) FROM event_versions').fetchone()[0]
    monkeypatch.setattr(C.verify,'REJECTED_SQL','TRUE');C.resolve(db)
    assert db.execute('SELECT count(*) FROM event_versions').fetchone()[0]==events
    assert F.scan(db)['EVALUATED']==1
    current=db.execute('SELECT evaluation_id FROM financial_scans WHERE publication_id=%s',(pid,)).fetchone()[0]
    assert current!=first
    assert db.execute('SELECT priority_class FROM candidate_evaluations WHERE evaluation_id=%s',(current,)).fetchone()[0]=='P3'


def test_pending_new_global_rules_do_not_resurrect_an_older_retired_policy(db,monkeypatch):
    issuer,src=_seed(db);_filing(db,issuer,src,5004,at('2026-01-01'),[PO])
    for policy in ('commercial-10','commercial-11'):
        with monkeypatch.context() as phase:
            phase.setattr(V,'RULES_VERSION',policy);C.scan(db);C.resolve(db)
    assert {r[8]['_policy_version'] for r in queue.evaluation_rows(db)}=={'commercial-11'}


def test_withdrawn_source_does_not_enter_packet_actual_history_early(db,monkeypatch):
    issuer,_,_=original(db,monkeypatch);old=queue.evaluation_rows(db)[0]
    before=datetime.now(timezone.utc)
    monkeypatch.setattr(C,'extract_document',lambda pages:([],0));C.scan(db)
    after=datetime.now(timezone.utc)
    it=dict(issuer_id=issuer,trigger_event_version_ids=old[12],mode='ACTUAL_SYSTEM_REPLAY',cutoff=before)
    assert not P._events(db,it)[0]['details'].get('source_reading_withdrawn')
    it['cutoff']=after
    assert P._events(db,it)[0]['details']['source_reading_withdrawn']


def test_same_rule_negative_reread_clears_verified_award_baselines(db):
    from inflection.triage.screen import prior_orders
    from inflection.orderbook_evidence import awards_totals
    issuer,src=_seed(db);tid=_filing(db,issuer,src,5005,at('2026-01-01'),[PO]);C.scan(db);C.resolve(db)
    assert prior_orders(db,issuer,at('2026-02-01'))[1]==1
    replacement(db,tid,'The registered office address remains unchanged.');C.scan(db)
    assert prior_orders(db,issuer,at('2026-02-01'))==([],0)
    assert awards_totals(db,issuer,at('2026-02-01'))==(0,0)


def test_multi_event_reread_retains_reaffirmed_event_without_withdrawn_high_priority(db):
    issuer,src=_seed(db)
    smaller='The Company has received an order worth Rs 10 crore from Southern Utility Limited.'
    tid=_filing(db,issuer,src,5006,at('2026-01-01'),[PO,smaller]);C.scan(db);C.resolve(db)
    before=datetime.now(timezone.utc)
    original_priority=queue.from_rows(queue.evaluation_rows(db))[0]['priority']
    assert original_priority in ('P1','P2')
    replacement(db,tid,smaller);C.scan(db);C.resolve(db)
    after=datetime.now(timezone.utc)
    assert queue.from_rows(queue.evaluation_rows(db))[0]['priority']=='P3'
    rows=queue.evaluation_rows(db,include_superseded=True);history=queue.commercial_checkpoint_history(db,after)
    assert queue.from_rows(queue.actual_rows(rows,before,commercial_history=history))[0]['priority']==original_priority
    assert queue.from_rows(queue.actual_rows(rows,after,commercial_history=history))[0]['priority']=='P3'


def test_frozen_quote_rerecheck_cannot_resurrect_a_withdrawn_source(db):
    from inflection.audit import recheck_packet
    issuer,src=_seed(db);tid=_filing(db,issuer,src,5007,at('2026-01-01'),[PO]);C.scan(db);C.resolve(db)
    row=queue.evaluation_rows(db)[0];it=dict(issuer_id=issuer,trigger_event_version_ids=row[12],
        cutoff=at('2026-02-01'),mode='PUBLIC_INFORMATION_RECONSTRUCTION')
    p=dict(company={'issuer_id':str(issuer)},manifest={'cutoff':it['cutoff'].isoformat(),'mode':it['mode']},
           events=P._events(db,it),trigger_passages=[dict(event_id=str(P._events(db,it)[0]['event_id']),
                text_artifact_id=str(tid),page_no=1,quote=PO)])
    frozen=deepcopy(p)
    replacement(db,tid,'The registered office address remains unchanged.');C.scan(db)
    current=recheck_packet(db,p)
    assert p==frozen and current['events'][0]['amount'] is None
    assert current['events'][0]['details']['source_reading_withdrawn']
