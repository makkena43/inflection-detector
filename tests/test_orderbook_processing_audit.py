from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
import importlib.util

import pytest
from psycopg.types.json import Jsonb

from inflection.asof import IST
from inflection import orderbook
from inflection.orderbook_evidence import extract_points,effective_points,EXTRACTOR_VERSION
from test_commercial import _seed,_filing


def when(day):return datetime.fromisoformat(day+'T18:00:00+05:30')


def document(db,issuer,source,n,day,text,title='Investor presentation'):
    tid=_filing(db,issuer,source,n,when(day),[text],category='Investor Presentation')
    pid=db.execute('''SELECT p.publication_id FROM document_publications p JOIN text_artifacts t
         USING(document_version_id) WHERE t.text_artifact_id=%s''',(tid,)).fetchone()[0]
    db.execute('UPDATE document_publications SET title=%s,ingested_at=clock_timestamp() WHERE publication_id=%s',(title,pid))
    return pid,tid


def engine(monkeypatch):
    monkeypatch.setenv('INFLECTION_TRIAGE_RULES','3.6')
    spec=importlib.util.spec_from_file_location('audited_engine',Path(__file__).parents[1]/'ops/engine.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize('text',[
    'Our order book stood at $620 million as at 31 March 2025.',
    'The target order inflow for FY25 is INR 25,000 crore.',
    'Our order book pipeline stood at INR 18,000 crore as at 31 March 2025.',
    "Our customer's order book stood at INR 2,000 crore as at 31 March 2025.",
    'The IPO order book was INR 1,000 crore as at 31 March 2025.',
    'The claims backlog was INR 1,000 crore as at 31 March 2025.',
])
def test_foreign_targets_pipelines_and_customer_books_are_not_observed_company_demand(text):
    assert orderbook.figures(text)=={}


@pytest.mark.parametrize('spelling',['31 March 2025','March 31, 2025','2025-03-31','31.03.2025'])
def test_reporting_date_comes_from_the_source_not_filing_season(spelling):
    points,_=extract_points('Our order book was INR 1,000 crore as at '+spelling+'.',published=when('2025-08-01'))
    assert points[0]['period_end']==date(2025,3,31) and points[0]['quality']=='VERIFIED'


def test_future_execution_does_not_turn_an_existing_order_book_into_a_forecast():
    points,_=extract_points('Our order book stood at INR 1,000 crore as at 31 March 2025 and is expected to execute over two years.',
                            published=when('2025-05-01'))
    assert points[0]['quality']=='VERIFIED'


def test_annual_and_quarterly_clauses_are_not_combined():
    points,_=extract_points('Annual order intake for FY25 was INR 400 crore and quarterly order inflow for Q4 FY25 was INR 100 crore.',
                            published=when('2025-05-01'))
    assert {(p['period_basis'],p['amount_cr']) for p in points}=={('ANNUAL',400),('QUARTER',100)}


def test_bare_fiscal_year_does_not_assign_quarterly_intake_to_march():
    points,_=extract_points('Quarterly order inflow in FY25 was INR 100 crore.',published=when('2025-05-01'))
    assert points[0]['period_end'] is None and points[0]['quality']=='UNVERIFIED_PERIOD'


def test_lower_bounds_are_not_exact_order_book_values():
    points,_=extract_points('Our order book exceeded INR 1,000 crore as at 31 March 2025.',published=when('2025-05-01'))
    # "exceeded" is still an explicit unbounded qualifier, not an exact measurement.
    bounded,_=extract_points('Our order book was more than INR 1,000 crore as at 31 March 2025.',published=when('2025-05-01'))
    assert points[0]['quality']=='BOUND_NOT_COMPARABLE'
    assert bounded[0]['quality']=='BOUND_NOT_COMPARABLE'
    assert bounded[0]['metadata']['amount_basis']=='LOWER_BOUND'


def test_quarter_and_annual_flows_remain_distinct_in_the_same_filing(db,monkeypatch):
    issuer,src=_seed(db)
    pid,_=document(db,issuer,src,1000,'2025-05-10',
        'Annual order intake for FY25 was Rs 400 crore; quarterly order inflow for Q4 FY25 was Rs 100 crore.')
    assert orderbook.scan(db,date(2025,1,1),date(2025,6,1),publication_ids=[pid])['inserted']==2
    points=effective_points(db,issuer,when('2025-06-01'),verified_only=True)
    assert {(p['period_basis'],p['amount_cr']) for p in points}=={('ANNUAL',400),('QUARTER',100)}
    result=engine(monkeypatch).order_cycle(db,issuer,when('2025-06-01'))
    assert result['Q'][date(2025,3,31)]==100 and result['FY'][date(2025,3,31)]==400


def test_later_smaller_source_correction_wins_over_larger_old_amount(db):
    issuer,src=_seed(db)
    document(db,issuer,src,1010,'2025-05-01','Our order book was INR 1,000 crore as at 31 March 2025.')
    later,_=document(db,issuer,src,1011,'2025-05-02','Our order book was INR 800 crore as at 31 March 2025.')
    orderbook.scan(db,date(2025,1,1),date(2025,6,1))
    point=effective_points(db,issuer,when('2025-06-01'),verified_only=True)[0]
    assert point['amount_cr']==800 and point['publication_id']==str(later)


def test_rejecting_one_legacy_source_does_not_erase_another_source_for_the_quarter(db):
    issuer,src=_seed(db)
    one,_=document(db,issuer,src,1020,'2025-05-01','Our order book was INR 1,000 crore as at 31 March 2025.')
    two,_=document(db,issuer,src,1021,'2025-05-02','Our order book was INR 800 crore as at 31 March 2025.')
    for pid,value,version in [(one,1000,'orderbook-2'),(two,800,'orderbook-2'),(one,0,'haiku-check-1')]:
        db.execute('''INSERT INTO order_book_figures(issuer_id,publication_id,published_at,quarter_end,kind,amount_cr,sentence,extractor_version)
          VALUES(%s,%s,%s,'2025-03-31','BOOK',%s,%s,%s)''',
          (issuer,pid,when('2025-05-01' if pid==one else '2025-05-02'),value,
           f'Our order book was INR {value} crore as at 31 March 2025.',version))
    result=orderbook.series(db,issuer,when('2025-06-01'))
    assert result[-1]['order_book_cr']==800


def test_no_period_proof_stays_null_and_cannot_support_cycle_arithmetic(db):
    issuer,src=_seed(db)
    pid,_=document(db,issuer,src,1030,'2025-08-01','Our order book stood at INR 1,000 crore.')
    orderbook.scan(db,date(2025,1,1),date(2025,9,1),publication_ids=[pid])
    row=db.execute('SELECT period_end,quality FROM orderbook_observations').fetchone()
    assert row==(None,'UNVERIFIED_PERIOD')
    assert effective_points(db,issuer,when('2025-09-01'),verified_only=True)==[]
    assert orderbook.scan(db,date(2025,1,1),date(2025,9,1),publication_ids=[pid]).get('scanned',0)==0


def test_partial_sources_and_segment_figures_cannot_override_company_total(db):
    issuer,src=_seed(db)
    pid,_=document(db,issuer,src,1040,'2025-05-01',
        'Defence order book was INR 2,817 crore as at 31 March 2025. Total order book was INR 1,900 crore as at 31 March 2025.')
    orderbook.scan(db,date(2025,1,1),date(2025,6,1))
    assert orderbook.series(db,issuer,when('2025-06-01'))[-1]['order_book_cr']==1900
    partial,_=document(db,issuer,src,1041,'2025-05-02','Total order book was INR 3,000 crore as at 31 March 2025.')
    db.execute("UPDATE document_publications SET pipeline_state='PARTIAL_TEXT',processing_issues=ARRAY['ZIP_INCOMPLETE'] WHERE publication_id=%s",(partial,))
    orderbook.scan(db,date(2025,1,1),date(2025,6,1))
    assert orderbook.series(db,issuer,when('2025-06-01'))[-1]['order_book_cr']==1900


def test_changed_source_does_not_backdate_new_content_or_erase_actual_history(db):
    issuer,src=_seed(db)
    pid,_=document(db,issuer,src,1050,'2025-05-01','Our order book was INR 1,000 crore as at 31 March 2025.')
    orderbook.scan(db,date(2025,1,1),date(2025,6,1),publication_ids=[pid])
    historical=datetime.now(timezone.utc)
    replacement,_=document(db,issuer,src,1051,'2025-05-02','No figures are given here.')
    version=db.execute('SELECT document_version_id FROM document_publications WHERE publication_id=%s',(replacement,)).fetchone()[0]
    db.execute('UPDATE document_publications SET document_version_id=%s,ingested_at=clock_timestamp() WHERE publication_id=%s',(version,pid))
    orderbook.scan(db,date(2025,1,1),date(2025,6,1),publication_ids=[pid])
    actual=effective_points(db,issuer,historical,'ACTUAL_SYSTEM_REPLAY',True)
    assert len(actual)==1 and actual[0]['amount_cr']==1000
    assert effective_points(db,issuer,datetime.now(timezone.utc),verified_only=True)==[]
    assert effective_points(db,issuer,when('2025-06-01'),'ACTUAL_SYSTEM_REPLAY',True)==[]
    assert len(effective_points(db,issuer,when('2025-06-01'),verified_only=True))==1


def test_cycle_does_not_invent_q4_from_mixed_annual_and_quarterly_sources(db,monkeypatch):
    issuer,src=_seed(db)
    for n,day,text in [(1060,'2024-08-01','Quarterly order inflow for Q1 FY25 was INR 100 crore.'),
                       (1061,'2024-11-01','Quarterly order inflow for Q2 FY25 was INR 100 crore.'),
                       (1062,'2025-02-01','Quarterly order inflow for Q3 FY25 was INR 100 crore.'),
                       (1063,'2025-05-01','Annual order inflow for FY25 was INR 600 crore.')]:
        document(db,issuer,src,n,day,text)
    orderbook.scan(db,date(2024,1,1),date(2025,6,1))
    result=engine(monkeypatch).order_cycle(db,issuer,when('2025-06-01'))
    assert date(2025,3,31) not in result['Q'] and result['FY'][date(2025,3,31)]==600


def test_zero_quarters_are_data_not_missing_values(monkeypatch):
    module=engine(monkeypatch);end=date(2025,3,31)
    q={module._shift(end,-3*i):v for i,v in enumerate([0,20,20,20,0,10,10,10])}
    increase,_,_=module.intake_increase(dict(Q=q,FY={},BOOK={}),when('2025-06-01'))
    assert increase==30


def test_unrelated_review_does_not_block_new_intake_and_identical_inputs_do_not_repeat(db,monkeypatch):
    issuer,src=_seed(db);module=engine(monkeypatch)
    document(db,issuer,src,1070,'2024-05-01','Annual order inflow for FY24 was INR 100 crore.')
    document(db,issuer,src,1071,'2025-05-13','Annual order inflow for FY25 was INR 200 crore.')
    orderbook.scan(db,date(2024,1,1),date(2025,6,1))
    db.execute('''INSERT INTO triage_reviews(week_start,issuer_id,label,decided_by,triage_action,result,source)
         VALUES('2025-05-12',%s,'ABC','test','WATCH_MILESTONE','{}','test')''',(issuer,))
    packet=dict(manifest=dict(cutoff='2025-05-25T18:30:00+00:00'),financials=dict(ttm=dict(revenue=dict(value='1000',period_end='2025-03-31'))),
                events=[dict(event_type='ORDER')])
    initial=dict(triage_action='WATCH_MILESTONE',size_pct_of_revenue=None,rationale='Research watch')
    result=module.order_cycle_event(initial,packet,db,issuer)
    assert result['triage_action']=='DEEP_RESEARCH' and result['size_pct_of_revenue']==10
    db.execute('''INSERT INTO triage_reviews(week_start,issuer_id,label,decided_by,triage_action,result,source)
         VALUES('2025-05-19',%s,'ABC','test','DEEP_RESEARCH',%s,'test')''',(issuer,Jsonb(result)))
    packet['manifest']['cutoff']='2025-06-01T18:30:00+00:00'
    assert module.order_cycle_event(initial,packet,db,issuer)==initial
    # A genuinely changed baseline is new input, even though the latest year's
    # amount is unchanged. Its publication cannot be borrowed by earlier cutoffs.
    document(db,issuer,src,1072,'2025-05-27','Annual order inflow for FY24 was INR 80 crore.')
    orderbook.scan(db,date(2024,1,1),date(2025,6,1))
    revised=module.order_cycle_event(initial,packet,db,issuer)
    assert revised['size_pct_of_revenue']==12


def test_award_history_uses_one_source_reading_across_rule_versions(db,monkeypatch):
    from inflection.commercial import pipeline as C,vocabulary as V
    from inflection.orderbook_evidence import awards_totals
    issuer,src=_seed(db)
    document(db,issuer,src,1080,'2025-01-10','The Company has received an order worth INR 100 crore from NTPC Limited.')
    with monkeypatch.context() as old:
        old.setattr(V,'RULES_VERSION','commercial-prior')
        C.scan(db);C.resolve(db)
    C.scan(db);C.resolve(db)
    assert db.execute('SELECT count(*) FROM events').fetchone()[0]==2
    assert awards_totals(db,issuer,when('2025-06-01'))==(100,0)


def test_old_award_is_not_moved_into_current_year_by_a_later_update(db):
    from inflection.commercial import pipeline as C
    from inflection.orderbook_evidence import awards_totals
    issuer,src=_seed(db)
    document(db,issuer,src,1090,'2024-01-10','The Company has received an order worth INR 100 crore from NTPC Limited.')
    C.scan(db);C.resolve(db)
    db.execute('''INSERT INTO event_versions(event_id,version_no,commercial_stage,event_type,observation_status,
        magnitude,magnitude_currency,magnitude_scale,amount_basis,ownership_scope,published_at,details,
        content_hash,supersedes_id) SELECT event_id,version_no+1,commercial_stage,event_type,observation_status,
        magnitude,magnitude_currency,magnitude_scale,amount_basis,ownership_scope,%s,details,gen_random_uuid()::text,
        event_version_id FROM event_versions ORDER BY version_no DESC LIMIT 1''',(when('2025-05-01'),))
    assert awards_totals(db,issuer,when('2025-06-01'))==(0,100)


def test_grounded_large_award_is_not_discarded_by_an_assumed_size_cap(db):
    from inflection.commercial import pipeline as C
    from inflection.orderbook_evidence import awards_totals
    issuer,src=_seed(db)
    document(db,issuer,src,1100,'2025-01-10','The Company has received an order worth INR 400 crore from NTPC Limited.')
    C.scan(db);C.resolve(db)
    assert awards_totals(db,issuer,when('2025-06-01'))==(400,0)


def test_conflicting_same_source_values_are_not_resolved_by_choosing_the_largest(db):
    issuer,src=_seed(db)
    document(db,issuer,src,1110,'2025-05-01','Order book was INR 1,000 crore as at 31 March 2025. '
             'Order book was INR 800 crore as at 31 March 2025.')
    orderbook.scan(db,date(2025,1,1),date(2025,6,1))
    assert effective_points(db,issuer,when('2025-06-01'),verified_only=True)==[]


def test_annual_reports_are_read_and_scoped_repair_honours_explicit_source_ids(db):
    issuer,src=_seed(db)
    annual,_=document(db,issuer,src,1120,'2025-05-01','Order book was INR 1,000 crore as at 31 March 2025.')
    other,_=document(db,issuer,src,1121,'2025-05-02','Order book was INR 800 crore as at 31 March 2025.')
    db.execute("UPDATE document_publications SET original_category='Annual Report' WHERE publication_id=%s",(annual,))
    db.execute("UPDATE document_publications SET original_category='Other' WHERE publication_id=%s",(other,))
    assert orderbook.scan(db,date(2025,1,1),date(2025,6,1))['scanned']==1
    assert orderbook.scan(db,date(2025,1,1),date(2025,6,1),publication_ids=[other])['scanned']==1


def test_individual_award_is_not_vetoed_because_it_equals_the_quarters_intake(db,monkeypatch):
    from inflection.commercial import pipeline as C
    issuer,src=_seed(db)
    document(db,issuer,src,1130,'2025-05-10',
        'The Company has received a single order worth INR 200 crore from NTPC Limited. '
        'Quarterly order inflow for Q4 FY25 was INR 200 crore.')
    C.scan(db);C.resolve(db);orderbook.scan(db,date(2025,1,1),date(2025,6,1))
    eid=db.execute("SELECT event_id FROM events WHERE event_type='ORDER'").fetchone()[0]
    packet=dict(company=dict(issuer_id=str(issuer)),manifest=dict(cutoff='2025-05-25T18:30:00+00:00'),
        financials=dict(ttm=dict(revenue=dict(value='1000',period_end='2025-03-31'))),
        events=[dict(event_id=str(eid),event_type='ORDER',stage='BINDING_DEMAND',amount='200 INR CRORE',
                     amount_basis='FIRM',relationship='UNKNOWN',published_at='2025-05-10 18:00 IST',version_no=1)])
    result=engine(monkeypatch).triage(packet,db,issuer)
    assert result['triage_action']=='DEEP_RESEARCH' and result['size_pct_of_revenue']==20


def test_consolidated_and_standalone_books_are_not_false_conflicts_or_mixed_growth(db,monkeypatch):
    issuer,src=_seed(db)
    for n,day,year,consolidated,standalone in [(1140,'2024-05-01',2024,800,300),(1141,'2025-05-01',2025,1000,500)]:
        document(db,issuer,src,n,day,
          f'Consolidated order book was INR {consolidated} crore as at 31 March {year}. '
          f'Standalone order book was INR {standalone} crore as at 31 March {year}.')
    orderbook.scan(db,date(2024,1,1),date(2025,6,1))
    points=effective_points(db,issuer,when('2025-06-01'),verified_only=True)
    assert len(points)==4
    assert orderbook.series(db,issuer,when('2025-06-01'))[-1]['book_yoy_pct']==25
    assert engine(monkeypatch).order_cycle(db,issuer,when('2025-06-01'))['BOOK'][date(2025,3,31)]==1000
