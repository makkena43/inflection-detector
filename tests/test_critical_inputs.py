"""Validate decision inputs, not company-specific investment outcomes."""
from datetime import date,datetime
from decimal import Decimal
import pytest
from inflection.asof import IST
from inflection.units import inr_base
from inflection.packets import contents as C
from inflection.commercial.pipeline import annual_revenue
from test_commercial import _seed
from test_packets import fact


@pytest.mark.parametrize('currency,scale,kind,value',[('USD','MILLION','MONEY',100),('INR',None,'MONEY',100),
 ('INR','CRORE','PER_SHARE',100),('INR','UNITS','MONEY','NaN'),('INR','UNITS','MONEY','Infinity')])
def test_unproved_or_nonfinite_values_cannot_enter_inr_arithmetic(currency,scale,kind,value):
    assert inr_base(value,currency,scale,kind) is None


def add_revenue(db,issuer,value,scale='UNITS',currency='INR',kind='MONEY'):
    return db.execute("""INSERT INTO financial_facts(issuer_id,metric,period_end,scope,value,value_kind,currency,scale,
        period_type,available_at,provider,provider_version,content_hash,missing_reason)
        VALUES(%s,'revenue','2025-12-31','CONSOLIDATED',%s,%s,%s,%s,'QUARTER','2026-01-20','test','critical',
               gen_random_uuid()::text,CASE WHEN %s::numeric IS NULL THEN 'UNVERIFIED' END) RETURNING fact_id""",
        (issuer,value,kind,currency,scale,value)).fetchone()[0]


def test_commercial_denominator_normalizes_the_stored_scale_and_carries_proof(db):
    issuer,_=_seed(db)
    fid=add_revenue(db,issuer,500,scale='CRORE')
    value,proof=annual_revenue(db,issuer,datetime(2026,2,1,tzinfo=IST))
    assert value==Decimal(1600)*10**7 and str(fid) in proof['fact_ids']
    assert proof['currency']=='INR' and proof['scale']=='UNITS'


def test_new_unverified_revenue_does_not_resurrect_an_older_value(db):
    issuer,_=_seed(db);add_revenue(db,issuer,None)
    value,proof=annual_revenue(db,issuer,datetime(2026,2,1,tzinfo=IST))
    assert value==Decimal(1200)*10**7 and proof['basis']=='ANNUAL'
    # The valid annual fallback is explicit; the old quarterly TTM is not reused.


def test_foreign_revenue_cannot_be_relabelled_inr_by_any_shared_reader(db):
    from inflection.snapshots import financials
    issuer,_=_seed(db);add_revenue(db,issuer,500,scale='MILLION',currency='USD')
    snap=financials(db,issuer,datetime(2026,2,1,tzinfo=IST))
    assert snap['rows']['revenue'][-1]['value'] is None
    assert snap['ttm']['revenue']['value'] is None
    assert annual_revenue(db,issuer,datetime(2026,2,1,tzinfo=IST))[1]['basis']=='ANNUAL'


def test_mixed_currency_ttm_is_missing_instead_of_a_false_inr_total():
    ends=['2025-03-31','2025-06-30','2025-09-30','2025-12-31']
    facts=[fact('revenue',d,100) for d in ends];facts[-1]['currency']='USD'
    snapshot=C.financial_snapshot(facts)
    assert snapshot['ttm']['revenue']['value'] is None
    assert snapshot['rows']['revenue'][-1]['value'] is None


def test_exceptional_gains_do_not_masquerade_as_operating_profit():
    ends=['2025-03-31','2025-06-30','2025-09-30','2025-12-31'];facts=[]
    for end in ends:
        for metric,value in [('revenue',100),('total_expenses',95),('finance_cost',1),('depreciation',2),
                             ('pbt',55),('exceptional_items',50),('other_income',0)]:facts.append(fact(metric,end,value))
    snapshot=C.financial_snapshot(facts)
    assert C.valuation(snapshot,{})['opm_ttm_pct']=='8.0'
    snapshot['rows']['total_expenses'][-1]['publication_id']='different-restatement'
    assert C.valuation(snapshot,{})['opm_ttm_pct'] is None


def test_share_count_needs_monetary_capital_and_per_share_face_value():
    facts=[fact('revenue','2025-12-31',100),fact('paid_up_capital','2025-12-31',10),
           fact('face_value','2025-12-31',10,kind='PER_SHARE')]
    assert C.financial_snapshot(facts)['shares']['value']=='1.000'
    facts[-1]['value_kind']='MONEY';facts[-1]['scale']='CRORE'
    assert C.financial_snapshot(facts)['shares']['value'] is None


def test_late_recovered_commercial_mechanism_invalidates_financial_decision_cache(db):
    from inflection.financial import pipeline as F
    from test_financial_route import _seed as results_seed,_results,_event,BASE
    issuer,src=results_seed(db)
    at=lambda day:datetime.fromisoformat(day+'T18:30:00+05:30')
    _results(db,issuer,src,2120,date(2024,9,30),at('2024-11-07'),**BASE)
    pid=_results(db,issuer,src,2121,date(2025,9,30),at('2025-11-07'),**{**BASE,'total_expenses':850})
    F.scan(db)
    old=db.execute('SELECT evaluation_id,input_fingerprint FROM financial_scans WHERE publication_id=%s',(pid,)).fetchone()
    _event(db,issuer,'ORDER','BINDING_DEMAND',at('2025-10-01'))
    assert F.scan(db)['EVALUATED']==1
    new=db.execute('SELECT evaluation_id,input_fingerprint FROM financial_scans WHERE publication_id=%s',(pid,)).fetchone()
    assert old[0]!=new[0] and old[1]!=new[1]
    _event(db,issuer,'ORDER','BINDING_DEMAND',at('2026-01-01'))
    assert F.scan(db)=={}  # A genuinely future mechanism is not an earlier input.


@pytest.mark.parametrize('text,expected',[('1000000000 INR UNITS',100),('1000000 INR THOUSAND',100),
 ('100 INR CRORE',100),('1000 INR MILLION',100),('1 INR BILLION',100),('10000 INR LAKH',100),
 ('100 USD MILLION',None),('100 INR CRORE trailing unproved amount',None)])
def test_all_supported_canonical_order_scales_reach_the_same_sizing_input(text,expected):
    from inflection.triage.screen import crore
    assert crore(text)==expected


def test_tax_inclusive_award_needs_net_value_without_guessing_tax_rate():
    from inflection.triage.screen import triage
    from inflection.commercial.resolve import EventState,materiality
    from inflection.units import Money,Scale
    from test_detection_audit import packet
    p=packet();p['events'][0].setdefault('details',{})['tax_basis']='INCLUSIVE'
    result=triage(p)
    assert result['triage_action']=='WATCH_MILESTONE' and result['size_pct_of_revenue'] is None
    assert 'NET_ORDER_VALUE_REQUIRED' in result['data_gaps']
    e=EventState('event','issuer','ORDER','ORDER',datetime(2026,1,1,tzinfo=IST),
        amount=Money(Decimal(100),'INR',Scale.CRORE),basis='FIRM',details={'tax_basis':'INCLUSIVE','duration_months':12})
    assert materiality(e,Decimal(500)*10**7).status=='MATERIALITY_UNKNOWN'


def test_nonfinite_source_xml_is_an_issue_not_a_valid_figure_or_parser_crash():
    from test_financials import filing,FACTS
    from inflection.sources.xbrl import parse_results_xbrl
    raw=filing([(tag,'NaN' if tag=='RevenueFromOperations' else q,fy) for tag,q,fy in FACTS]).replace(b'>NaN.00<',b'>NaN<')
    parsed=parse_results_xbrl(raw)
    assert any('non-finite' in issue for issue in parsed.issues)
    assert all(f.value is None or f.value.is_finite() for f in parsed.figures)


def test_tax_inclusive_backlog_is_not_verified_cycle_input(db):
    from inflection import orderbook
    from inflection.orderbook_evidence import effective_points
    from test_orderbook_processing_audit import document,when
    issuer,src=_seed(db)
    document(db,issuer,src,2140,'2025-05-10',
             'Our order book stood at INR 1,000 crore including GST as at 31 March 2025.')
    orderbook.scan(db,date(2025,1,1),date(2025,6,1))
    assert effective_points(db,issuer,when('2025-06-01'),verified_only=True)==[]
    assert effective_points(db,issuer,when('2025-06-01'))[0]['quality']=='UNVERIFIED_TAX_BASIS'
