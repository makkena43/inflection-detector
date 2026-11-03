"""General decision-time and lifecycle invariants, without issuer-specific exceptions."""
from datetime import date,datetime,timedelta
from copy import deepcopy
from decimal import Decimal
import pytest
from inflection.asof import IST
from inflection import queue
from inflection.triage import pipeline as T
from inflection.packets import pipeline as P
from test_triage import _issuer,_evaluation,WEEK,CUTOFF
from test_commercial import _seed,_filing


def version(db,issuer,stage,at,n=1,event=None,recorded=None):
    if event is None:
        event=db.execute("""INSERT INTO events(issuer_id,event_type,first_public_at,rules_version)
          VALUES(%s,'ORDER',%s,'test') RETURNING event_id""",(issuer,at)).fetchone()[0]
    vid=db.execute("""INSERT INTO event_versions(event_id,version_no,commercial_stage,event_type,observation_status,
          magnitude,magnitude_currency,magnitude_scale,amount_basis,content_hash,published_at,recorded_at,details)
          VALUES(%s,%s,%s,'ORDER','OBSERVED',100,'INR','CRORE','FIRM',gen_random_uuid()::text,%s,
                 coalesce(%s,clock_timestamp()),'{}') RETURNING event_version_id""",(event,n,stage,at,recorded)).fetchone()[0]
    return event,vid


def test_actual_shortlist_cannot_see_evaluations_recorded_later(db):
    issuer=_issuer(db,'AAA')
    _evaluation(db,issuer,datetime(2026,10,6,tzinfo=IST),'P1')
    actual=T.build(db,WEEK,mode='ACTUAL_SYSTEM_REPLAY',dry_run=True,now=CUTOFF)
    public=T.build(db,WEEK,mode='PUBLIC_INFORMATION_RECONSTRUCTION',dry_run=True,now=CUTOFF)
    assert actual['shortlist']==[] and public['shortlist'][0]['symbol']=='AAA'


def test_actual_history_does_not_use_a_review_recorded_after_cutoff(db):
    issuer=_issuer(db,'AAA');_evaluation(db,issuer,datetime(2026,10,6,tzinfo=IST),'P1')
    T.build(db,WEEK,now=CUTOFF)
    T.record(db,WEEK,'AAA','WATCH_MILESTONE')
    assert issuer in T._last_triage(db,CUTOFF+timedelta(days=7))
    assert issuer not in T._last_triage(db,CUTOFF+timedelta(days=7),'ACTUAL_SYSTEM_REPLAY')


def test_existing_shortlist_cannot_be_returned_for_an_earlier_cutoff_or_other_mode(db):
    T.build(db,WEEK,now=CUTOFF)
    with pytest.raises(ValueError,match='different mode or a later cutoff'):
        T.build(db,WEEK,mode='ACTUAL_SYSTEM_REPLAY',now=CUTOFF)
    with pytest.raises(ValueError,match='different mode or a later cutoff'):
        T.build(db,WEEK,now=CUTOFF-timedelta(days=2))


def test_base_history_offset_is_converted_not_relabelled(monkeypatch):
    monkeypatch.setenv('INFLECTION_RUN_BASE_UNTIL','2026-01-01T00:00:00+00:00')
    assert T.base_until().hour==5 and T.base_until().minute==30


def test_packet_reads_revision_public_by_cutoff_even_if_original_trigger_is_old(db):
    issuer,_=_seed(db)
    eid,old=version(db,issuer,'BINDING_DEMAND',datetime(2026,1,1,tzinfo=IST))
    _,cancel=version(db,issuer,'CANCELLED',datetime(2026,2,1,tzinfo=IST),2,eid)
    it=dict(issuer_id=issuer,trigger_event_version_ids=[old],mode='PUBLIC_INFORMATION_RECONSTRUCTION',
            cutoff=datetime(2026,3,1,tzinfo=IST))
    assert P._events(db,it)[0]['version_id']==str(cancel)
    assert P._events(db,it)[0]['stage']=='CANCELLED'
    it['cutoff']=datetime(2026,1,15,tzinfo=IST)
    assert P._events(db,it)[0]['version_id']==str(old)


def test_late_recovered_cancellation_does_not_leak_into_actual_history(db):
    issuer,_=_seed(db)
    eid,old=version(db,issuer,'BINDING_DEMAND',datetime(2026,1,1,tzinfo=IST),recorded=datetime(2026,1,2,tzinfo=IST))
    version(db,issuer,'CANCELLED',datetime(2026,2,1,tzinfo=IST),2,eid,recorded=datetime(2026,4,1,tzinfo=IST))
    it=dict(issuer_id=issuer,trigger_event_version_ids=[old],mode='ACTUAL_SYSTEM_REPLAY',
            cutoff=datetime(2026,3,1,tzinfo=IST))
    assert P._events(db,it)[0]['stage']=='BINDING_DEMAND'
    it['mode']='PUBLIC_INFORMATION_RECONSTRUCTION'
    assert P._events(db,it)[0]['stage']=='CANCELLED'


def test_frozen_packet_recheck_cannot_resurrect_a_cancelled_award(db):
    from inflection.audit import recheck_packet
    issuer,_=_seed(db)
    eid,old=version(db,issuer,'BINDING_DEMAND',datetime(2026,1,1,tzinfo=IST))
    version(db,issuer,'CANCELLED',datetime(2026,2,1,tzinfo=IST),2,eid)
    packet=dict(company=dict(issuer_id=str(issuer)),manifest=dict(cutoff='2026-03-01T00:00:00+05:30',
        mode='PUBLIC_INFORMATION_RECONSTRUCTION'),events=[dict(event_id=str(eid),version_id=str(old),version_no=1,
        event_type='ORDER',stage='BINDING_DEMAND')],trigger_passages=[])
    original=deepcopy(packet);derived=recheck_packet(db,packet)
    assert packet==original
    assert derived['events'][0]['stage']=='CANCELLED' and derived['event_recheck']['changes']


def test_actual_passage_requires_processing_to_have_happened(db):
    from inflection.commercial import pipeline as C
    issuer,src=_seed(db)
    tid=_filing(db,issuer,src,2001,datetime(2026,1,1,tzinfo=IST),
        ['The Company has received a purchase order worth Rs 100 crore from NTPC Limited.'])
    db.execute("UPDATE document_publications SET ingested_at='2026-01-01' WHERE document_version_id=(SELECT document_version_id FROM text_artifacts WHERE text_artifact_id=%s)",(tid,))
    C.scan(db);C.resolve(db)
    vids=[r[0] for r in db.execute('SELECT event_version_id FROM event_versions').fetchall()]
    it=dict(issuer_id=issuer,trigger_event_version_ids=vids,mode='ACTUAL_SYSTEM_REPLAY',cutoff=datetime(2026,2,1,tzinfo=IST))
    passages,excluded=P._passages(db,it)
    assert passages==[] and excluded['POST_CUTOFF_PROCESSING']>0
    it['mode']='PUBLIC_INFORMATION_RECONSTRUCTION'
    assert P._passages(db,it)[0]


def test_actual_queue_uses_latest_known_source_reading_and_no_future_checkpoint(db):
    from inflection.financial import pipeline as F
    from test_financial_processing_audit import _results,at,BASE,_seed as seed_results
    issuer,src=seed_results(db)
    _results(db,issuer,src,2090,date(2024,9,30),at('2024-11-08'),**BASE)
    pid=_results(db,issuer,src,2091,date(2025,9,30),at('2025-11-07'),**{**BASE,'total_expenses':850})
    F.scan(db)
    before=db.execute('SELECT clock_timestamp()').fetchone()[0]
    original=queue.lines(db,end=before,mode='ACTUAL_SYSTEM_REPLAY')
    assert len(original)==1
    # The source reread withdraws its earlier nomination. History must retain
    # the positive reading before that reread and the no-nomination afterwards.
    db.execute("UPDATE financial_scans SET evaluation_id=NULL,status='NOT_NOMINATED',scanned_at=clock_timestamp() WHERE publication_id=%s",(pid,))
    after=db.execute('SELECT clock_timestamp()').fetchone()[0]
    assert len(queue.lines(db,end=before,mode='ACTUAL_SYSTEM_REPLAY'))==1
    assert queue.lines(db,end=after,mode='ACTUAL_SYSTEM_REPLAY')==[]


def test_replay_counts_one_price_and_one_split_across_duplicate_versions(db):
    from inflection.replay.pipeline import Prices
    issuer=_issuer(db,'AAA')
    sec=db.execute('SELECT security_id FROM securities WHERE issuer_id=%s',(issuer,)).fetchone()[0]
    db.execute("""INSERT INTO prices(security_id,trade_date,provider,provider_version,close,adjustment)
        VALUES(%s,'2025-01-01','nse_bhavcopy','a',100,'UNADJUSTED'),
              (%s,'2025-01-01','nse_bhavcopy','b',100,'UNADJUSTED'),
              (%s,'2025-03-01','nse_bhavcopy','a',60,'UNADJUSTED')""",(sec,sec,sec))
    for v in ('a','b'):
        db.execute("""INSERT INTO corporate_actions(security_id,kind,ex_date,details,provider,provider_version,reconciled)
            VALUES(%s,'SPLIT','2025-02-01','{"price_multiplier":"0.5"}','test',%s,true)""",(sec,v))
    px=Prices(db)
    assert len(px.closes(sec,'nse_bhavcopy'))==2
    assert len(px.corporate_actions(sec))==1
    value,measured=px.benchmark('nse_bhavcopy',date(2025,1,1),date(2025,3,1))
    assert value==Decimal('.2') and measured==1
    # A later action edit must not change this measurement's snapshot.
    db.execute("UPDATE corporate_actions SET details='{"+'"price_multiplier":"0.25"'+"}'")
    another=Prices(db)
    assert another.benchmark('nse_bhavcopy',date(2025,1,1),date(2025,3,1))[0]==Decimal('1.4')
    px.bench.clear()
    assert px.benchmark('nse_bhavcopy',date(2025,1,1),date(2025,3,1))[0]==Decimal('.2')


def test_replay_does_not_verify_conflicting_or_unreadable_action_ratios(db):
    from inflection.replay.pipeline import Prices
    issuer=_issuer(db,'AAA');sec=db.execute('SELECT security_id FROM securities WHERE issuer_id=%s',(issuer,)).fetchone()[0]
    db.execute("""INSERT INTO prices(security_id,trade_date,provider,provider_version,close,adjustment)
        VALUES(%s,'2025-01-01','nse_bhavcopy','a',100,'UNADJUSTED'),
              (%s,'2025-03-01','nse_bhavcopy','a',60,'UNADJUSTED')""",(sec,sec))
    for v,m in [('a','0.5'),('b','not parsed')]:
        db.execute("""INSERT INTO corporate_actions(security_id,kind,ex_date,details,provider,provider_version,reconciled)
            VALUES(%s,'SPLIT','2025-02-01',jsonb_build_object('price_multiplier',%s::text),'test',%s,true)""",(sec,m,v))
    px=Prices(db)
    assert px.corporate_actions(sec)[0]['multiplier'] is None
    assert px.benchmark('nse_bhavcopy',date(2025,1,1),date(2025,3,1))==(None,0)


def test_actual_replay_coverage_cannot_count_prices_loaded_after_the_week(db):
    from inflection.replay.pipeline import _coverage
    issuer=_issuer(db,'AAA');sec=db.execute('SELECT security_id FROM securities WHERE issuer_id=%s',(issuer,)).fetchone()[0]
    db.execute("""INSERT INTO prices(security_id,trade_date,provider,provider_version,close,adjustment)
        VALUES(%s,'2025-01-02','nse_bhavcopy','a',100,'UNADJUSTED')""",(sec,))
    public=_coverage(db,date(2024,12,30),date(2024,12,30))
    actual=_coverage(db,date(2024,12,30),date(2024,12,30),'ACTUAL_SYSTEM_REPLAY')
    assert public['nse_bhavcopy_days'][date(2024,12,30)]==1
    assert actual['nse_bhavcopy_days']=={}
