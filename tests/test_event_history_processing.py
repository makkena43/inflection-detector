from dataclasses import replace
from datetime import datetime,date
from decimal import Decimal
import pytest
from inflection.asof import IST
from inflection.commercial.resolve import Resolver
from inflection.commercial import pipeline as C
from inflection.packets import pipeline as P
from test_commercial import one,PO,_seed,_filing


def at(day):return datetime.fromisoformat(day+'T12:00:00+05:30')


def test_late_intermediate_source_does_not_copy_later_stage_or_terms():
    base=one(PO)
    bid=replace(base,stage='QUALIFIED',amount_basis='NON_BINDING',details={'duration_months':12})
    award=replace(base,details={'duration_months':24,'tax_basis':'INCLUSIVE'})
    r=Resolver('issuer');first=r.place(bid,at('2025-01-01'),'jan')
    future=r.place(award,at('2025-03-01'),'mar')
    late=r.place(replace(bid,relationship='CONFIRMED_RELATED'),at('2025-02-01'),'feb')
    assert late.event.stage=='QUALIFIED' and late.event.basis=='NON_BINDING'
    assert late.event.details['duration_months']==12
    assert late.event.version_no>future.event.version_no
    assert r.events[0].stage=='BINDING_DEMAND' and r.events[0].details['duration_months']==24
    assert r.events_at(at('2025-02-15'))[0].stage=='QUALIFIED'
    assert first.event.version_id!=late.event.version_id


def test_earliest_source_is_materialized_without_future_fields():
    base=one(PO);r=Resolver('issuer')
    later=r.place(replace(base,details={'tax_basis':'INCLUSIVE','duration_months':24}),at('2025-03-01'),'mar')
    earlier=r.place(replace(base,stage='QUALIFIED',amount_basis='NON_BINDING',details={}),at('2025-01-01'),'jan')
    assert earlier.outcome=='EARLIER_DISCLOSURE' and earlier.creates_version
    assert earlier.event.details.get('tax_basis') is None
    assert earlier.event.details.get('duration_months') is None
    assert r.events[0].version_id==later.event.version_id
    assert r.events_at(at('2025-02-01'))[0].stage=='QUALIFIED'


def test_new_terms_are_dated_versions_not_lost_repetitions():
    base=one(PO);r=Resolver('issuer')
    r.place(replace(base,details={}),at('2025-01-01'),'jan')
    result=r.place(replace(base,details={'duration_months':18,'tax_basis':'INCLUSIVE'}),at('2025-03-01'),'mar')
    assert result.outcome=='REVISION'
    assert not r.events_at(at('2025-02-01'))[0].details
    assert r.events[0].details['duration_months']==18


def test_late_partial_cancellation_uses_then_known_value_and_does_not_rewind_current():
    r=Resolver('issuer');r.place(one(PO),at('2025-01-01'),'jan')
    amend=one('The order value from Eastern Rail Systems Limited has been revised to Rs 300 crore.')
    r.place(amend,at('2025-05-01'),'may')
    cancel=one('Eastern Rail Systems Limited has cancelled Rs 150 crore of the purchase order for bogie frames.')
    late=r.place(cancel,at('2025-03-01'),'mar')
    assert late.event.amount.value==300
    assert r.events[0].amount.value==300 and r.events[0].published_at==at('2025-05-01')
    later=r.place(replace(amend,amount=replace(amend.amount,value=Decimal(250))),at('2025-06-01'),'jun')
    assert later.event.version_no==4 and r.events[0].amount.value==250


def test_database_backfill_survives_reload_and_readers_follow_publication_time(db):
    issuer,src=_seed(db)
    _filing(db,issuer,src,3000,at('2025-01-01'),[PO])
    _filing(db,issuer,src,3001,at('2025-05-01'),['The order value from Eastern Rail Systems Limited has been revised to Rs 300 crore.'])
    C.scan(db);C.resolve(db)
    eid,vid=db.execute('SELECT event_id,event_version_id FROM event_versions ORDER BY version_no LIMIT 1').fetchone()
    _filing(db,issuer,src,3002,at('2025-03-01'),['Eastern Rail Systems Limited has cancelled Rs 150 crore of the purchase order for bogie frames.'])
    C.scan(db);C.resolve(db)
    assert C.load_events(db,issuer)[0].published_at==at('2025-05-01')
    it=dict(issuer_id=issuer,trigger_event_version_ids=[vid],cutoff=at('2025-04-01'),mode='PUBLIC_INFORMATION_RECONSTRUCTION')
    assert P._events(db,it)[0]['amount'].startswith('300')
    it['cutoff']=at('2025-06-01')
    current=P._events(db,it)[0]
    assert current['version_no']==2 and current['details']['history_conflict']
    assert current['amount'] is None  # Later snapshots need rebuilding after an inserted earlier update.
    # Reload all history and advance once: no duplicate version number or rollback.
    _filing(db,issuer,src,3003,at('2025-06-01'),['The order value from Eastern Rail Systems Limited has been revised to Rs 250 crore.'])
    C.scan(db);C.resolve(db)
    assert C.load_events(db,issuer)[0].amount.value==250
    assert db.execute('SELECT count(DISTINCT version_no) FROM event_versions WHERE event_id=%s',(eid,)).fetchone()[0]==4


def test_screen_uses_publication_order_not_backfill_sequence():
    from inflection.triage.screen import triage
    from test_detection_audit import packet
    p=packet();original=p['events'][0]
    p['events']=[dict(original,published_at='2026-09-01T12:00:00+05:30',version_no=2,stage='CANCELLED'),
                 dict(original,published_at='2026-08-01T12:00:00+05:30',version_no=3)]
    result=triage(p)
    assert result['triage_action']!='DEEP_RESEARCH'
    p['events'][0]['published_at']='2026-10-01T12:00:00+05:30'
    assert triage(p)['triage_action']=='DEEP_RESEARCH'  # Future cancellation is not current knowledge.


def test_simultaneous_financial_conflict_is_consistent_across_readers(db):
    from inflection.financial import pipeline as F
    from inflection.snapshots import financials
    from inflection.commercial.pipeline import annual_revenue
    from inflection.financial_revisions import latest_facts
    from inflection.units import Scale
    issuer,src=_seed(db)
    tid=_filing(db,issuer,src,3020,at('2026-01-20'),['Results'])
    pid=db.execute('SELECT publication_id FROM document_publications p JOIN text_artifacts t USING(document_version_id) WHERE t.text_artifact_id=%s',(tid,)).fetchone()[0]
    with db.transaction():
        for value in (500,900):
            db.execute("""INSERT INTO financial_facts(issuer_id,publication_id,metric,period_end,scope,value,value_kind,
                currency,scale,period_type,available_at,provider,provider_version,content_hash)
                VALUES(%s,%s,'revenue','2025-12-31','CONSOLIDATED',%s,'MONEY','INR','CRORE','QUARTER',
                       '2026-01-20','test','conflict',gen_random_uuid()::text)""",(issuer,pid,value))
    assert F._facts(db,pid,at('2026-02-01'))[0][6] is None
    it=dict(issuer_id=issuer,cutoff=at('2026-02-01'),mode='PUBLIC_INFORMATION_RECONSTRUCTION')
    facts=P._facts(db,it)
    rev=next(f for f in facts if f['metric']=='revenue' and f['period_end']==date(2025,12,31))
    assert rev['value'] is None and rev['missing_reason']=='CONFLICTING_SOURCE_VALUES'
    assert financials(db,issuer,it['cutoff'])['ttm']['revenue']['value'] is None
    assert annual_revenue(db,issuer,it['cutoff'])[1]['basis']=='ANNUAL'
    # A genuinely later, unambiguous source correction resolves the cell.
    db.execute("""INSERT INTO financial_facts(issuer_id,publication_id,metric,period_end,scope,value,value_kind,
        currency,scale,period_type,available_at,provider,provider_version,content_hash)
        VALUES(%s,%s,'revenue','2025-12-31','CONSOLIDATED',500,'MONEY','INR','CRORE','QUARTER',
          '2026-01-21','test','correction',gen_random_uuid()::text)""",(issuer,pid))
    assert F._facts(db,pid,it['cutoff'])[0][6]==500*Scale.CRORE.factor


def test_equal_duplicate_values_with_different_scales_are_not_conflicts():
    from inflection.financial_revisions import latest_facts
    a=dict(metric='revenue',period_type='QUARTER',period_end=date(2025,12,31),scope='CONSOLIDATED',
           value=100,currency='INR',scale='CRORE',value_kind='MONEY',available_at=at('2026-01-20'),
           recorded_at=at('2026-01-21'),publication_id='source',fact_id='a')
    b=dict(a,value=1000,scale='MILLION',fact_id='b')
    assert latest_facts([a,b])[0]['value'] is not None


@pytest.mark.parametrize('clause,expected',[
 ('worth Rs 450 crore, to be executed within up to 12 months','FIRM'),
 ('worth up to Rs 450 crore, to be executed within 12 months','CEILING'),
 ('worth a maximum value of Rs 450 crore','CEILING'),
 ('worth Rs 450 crore maximum','CEILING'),
])
def test_time_bounds_do_not_turn_a_fixed_order_value_into_a_ceiling(clause,expected):
    m=one('The Company has received a purchase order '+clause+' from Eastern Rail Systems Limited.')
    assert m.amount_basis==expected


def test_legacy_backdated_inheritance_is_unverified_even_through_another_version(db):
    from test_decision_state_audit import version
    from inflection.triage.screen import triage
    from test_detection_audit import packet
    issuer,_=_seed(db)
    eid,first=version(db,issuer,'BINDING_DEMAND',at('2025-01-01'))
    _,future=version(db,issuer,'CANCELLED',at('2025-05-01'),2,eid)
    prior=future
    for seq,day in [(3,'2025-03-01'),(4,'2025-04-01')]:
        prior=db.execute("""INSERT INTO event_versions(event_id,version_no,commercial_stage,event_type,observation_status,
            magnitude,magnitude_currency,magnitude_scale,amount_basis,content_hash,published_at,supersedes_id,details)
            VALUES(%s,%s,'BINDING_DEMAND','ORDER','OBSERVED',100,'INR','CRORE','FIRM',gen_random_uuid()::text,%s,%s,'{}')
            RETURNING event_version_id""",(eid,seq,at(day),prior)).fetchone()[0]
    it=dict(issuer_id=issuer,trigger_event_version_ids=[first],cutoff=at('2025-04-15'),mode='PUBLIC_INFORMATION_RECONSTRUCTION')
    events=P._events(db,it)
    assert events[0]['details']['history_conflict'] and events[0]['amount'] is None
    p=packet();p['events']=events;p['manifest']['cutoff']=it['cutoff'].isoformat()
    result=triage(p)
    assert result['triage_action']=='WATCH_MILESTONE'
    assert 'HISTORICAL_SOURCE_REBUILD_REQUIRED' in result['data_gaps']
    it['cutoff']=at('2025-06-01')
    assert P._events(db,it)[0]['stage']=='UNKNOWN'


def test_late_cancellation_invalidates_later_terms_snapshot_and_award_baseline(db):
    from inflection.orderbook_evidence import awards_totals
    issuer,src=_seed(db)
    _filing(db,issuer,src,3050,at('2025-01-01'),[PO])
    C.scan(db);C.resolve(db)
    # A later terms-only update inherits the original amount. It was processed
    # before the intervening cancellation arrived.
    db.execute('''INSERT INTO event_versions(event_id,version_no,commercial_stage,event_type,observation_status,
        magnitude,magnitude_currency,magnitude_scale,amount_basis,ownership_scope,published_at,details,
        content_hash,supersedes_id) SELECT event_id,2,commercial_stage,event_type,observation_status,
        magnitude,magnitude_currency,magnitude_scale,amount_basis,ownership_scope,%s,
        details || '{"duration_months":18}'::jsonb,gen_random_uuid()::text,event_version_id
        FROM event_versions ORDER BY version_no LIMIT 1''',(at('2025-05-01'),))
    _filing(db,issuer,src,3052,at('2025-03-01'),[
        'Eastern Rail Systems Limited has cancelled Rs 150 crore of the purchase order for bogie frames.'])
    C.scan(db);C.resolve(db)
    first=db.execute('SELECT event_version_id FROM event_versions ORDER BY version_no LIMIT 1').fetchone()[0]
    it=dict(issuer_id=issuer,trigger_event_version_ids=[first],cutoff=at('2025-06-01'),
            mode='PUBLIC_INFORMATION_RECONSTRUCTION')
    event=P._events(db,it)[0]
    assert event['details']=={'history_conflict':True}
    assert event['amount'] is None and event['deadline'] is None and event['relationship']=='UNKNOWN'
    assert awards_totals(db,issuer,it['cutoff'])==(None,None)


def test_asof_event_view_is_empty_before_the_first_disclosure():
    r=Resolver('issuer');r.place(one(PO),at('2025-03-01'),'mar')
    assert r.events_at(at('2025-02-01'))==[]


def test_background_packet_rebuild_is_append_only_and_excludes_original_reviews(db,monkeypatch):
    from inflection.commercial import vocabulary as V
    from inflection.triage import pipeline as T
    from inflection.audit_repair import history_conflict_packets,refresh_history_conflicts
    from test_decision_state_audit import version
    issuer,src=_seed(db)
    _filing(db,issuer,src,3040,at('2026-01-01'),[PO])
    with monkeypatch.context() as legacy:
        legacy.setattr(V,'RULES_VERSION','legacy-history-test')
        C.scan(db);C.resolve(db)
        eid=db.execute('SELECT event_id FROM events').fetchone()[0]
        _,future=version(db,issuer,'CANCELLED',at('2026-05-01'),2,eid)
        db.execute("""INSERT INTO event_versions(event_id,version_no,commercial_stage,event_type,observation_status,
           magnitude,magnitude_currency,magnitude_scale,amount_basis,content_hash,published_at,supersedes_id,details)
           VALUES(%s,3,'BINDING_DEMAND','ORDER','OBSERVED',450,'INR','CRORE','FIRM',gen_random_uuid()::text,
                  %s,%s,'{}')""",(eid,at('2026-03-01'),future))
        T.build(db,date(2026,3,16),mode='PUBLIC_INFORMATION_RECONSTRUCTION',now=at('2026-03-25'))
        pid=P.assemble(db,date(2026,3,16))['packets'][0]['packet_id']
    original=db.execute('SELECT content_hash FROM triage_packets WHERE packet_id=%s',(pid,)).fetchone()
    assert str(pid) in {str(p) for p in history_conflict_packets(db,date(2026,1,1),date(2026,4,1))}
    deferred=refresh_history_conflicts(db,date(2026,1,1),date(2026,4,1))
    assert deferred['pending'] and deferred['refreshed']==0
    C.scan(db);C.resolve(db)
    report=refresh_history_conflicts(db,date(2026,1,1),date(2026,4,1))
    assert report['refreshed']==1 and not report['pending']
    assert db.execute('SELECT content_hash FROM triage_packets WHERE packet_id=%s',(pid,)).fetchone()==original
    assert db.execute('SELECT count(*) FROM triage_reviews').fetchone()[0]==0
    assert history_conflict_packets(db,date(2026,1,1),date(2026,4,1))==[]


def test_source_recheck_preserves_resolved_partial_cancellation_not_quote_amount(db):
    from inflection.audit import recheck_packet
    issuer,src=_seed(db)
    _filing(db,issuer,src,3060,at('2025-01-01'),[PO])
    cancel='Eastern Rail Systems Limited has cancelled Rs 150 crore of the purchase order for bogie frames.'
    tid=_filing(db,issuer,src,3061,at('2025-03-01'),[cancel])
    C.scan(db);C.resolve(db)
    eid,vid=db.execute('SELECT event_id,event_version_id FROM event_versions ORDER BY version_no DESC LIMIT 1').fetchone()
    it=dict(issuer_id=issuer,trigger_event_version_ids=[vid],cutoff=at('2025-04-01'),mode='PUBLIC_INFORMATION_RECONSTRUCTION')
    events=P._events(db,it)
    assert events[0]['amount'].startswith('300') and events[0]['stage']=='BINDING_DEMAND'
    p=dict(company=dict(issuer_id=str(issuer)),manifest=dict(cutoff=it['cutoff'].isoformat(),mode=it['mode']),
           events=events,trigger_passages=[dict(event_id=str(eid),version_no=2,text_artifact_id=str(tid),
                                               page_no=1,quote=one(cancel).quote)])
    refreshed=recheck_packet(db,p)
    assert refreshed['events'][0]['amount']==events[0]['amount']
    assert refreshed['events'][0]['stage']=='BINDING_DEMAND'
    # Unknown history may not be resurrected by source quote reclassification.
    db.execute('''INSERT INTO event_versions(event_id,version_no,commercial_stage,event_type,observation_status,
        magnitude,magnitude_currency,magnitude_scale,amount_basis,ownership_scope,published_at,details,
        content_hash,supersedes_id) SELECT event_id,3,commercial_stage,event_type,observation_status,
        magnitude,magnitude_currency,magnitude_scale,amount_basis,ownership_scope,%s,details,
        gen_random_uuid()::text,event_version_id FROM event_versions WHERE event_version_id=%s''',
        (at('2025-02-01'),vid))
    unverified=recheck_packet(db,p)['events'][0]
    assert unverified['amount'] is None and unverified['details']['history_conflict']
