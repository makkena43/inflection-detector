"""Regressions from missed-signal audits; no stock-specific admission rules."""
from copy import deepcopy
from datetime import datetime

import pytest
from inflection.commercial.extract import extract_document, _relationship
from inflection.triage.screen import triage, cycle_watch
from inflection.orderbook import inflow_period


def test_order_value_does_not_borrow_preceding_financing_amount():
    text = ('The Preferential Allotment amounts to ₹ 33.24 Cr. '
            'Secured contract of High-Speed Corridor Project from GSRDCL worth of ₹ 5.7 Cr for 48 months.')
    order = next(m for m in extract_document([(1, text)])[0] if m.family == 'ORDER')
    assert str(order.amount.value) == '5.7'
    assert order.details['duration_months'] == 48


def test_value_before_award_wording_is_not_replaced_by_advance_payment():
    text = 'The INR 100 crore order has been awarded with an advance payment of INR 5 crore.'
    order = next(m for m in extract_document([(1, text)])[0] if m.family == 'ORDER')
    assert str(order.amount.value) == '100'


def test_combined_firm_orders_and_forecast_not_sized_as_fully_firm():
    text = ('At Tritium, we bagged almost a $30 million combination of firm purchase order '
            'and forecast from a large US customer.')
    order = next(m for m in extract_document([(1, text)])[0] if m.family == 'ORDER')
    assert order.amount_basis == 'NON_BINDING' and order.details['mixed_commitment']


def test_received_wording_after_customer_still_establishes_firm_award():
    text = ('That is more for order from Torrent, which we have received for INR 750 crores, '
            'which will be executed this year.')
    order = next(m for m in extract_document([(1, text)])[0] if m.family == 'ORDER')
    assert order.stage == 'BINDING_DEMAND' and order.amount_basis == 'FIRM'


@pytest.mark.parametrize('text', [
    'During the first quarter of FY26, we secured seven significant new orders worth INR55.77 crores.',
    'We have secured new orders of INR 412 crores as I just mentioned.',
    'Company has secured significant orders for Solar Modules valued at Rs. 623 Mn.',
])
def test_bundle_amount_is_preserved_without_becoming_one_contract(text):
    order = next(m for m in extract_document([(1, text)])[0] if m.family == 'ORDER')
    assert order.amount is not None and order.details['aggregate_order_total']
    p = packet()
    p['events'][0]['details'] = dict(quote=text)
    result = triage(p)
    assert result['triage_action'] == 'WATCH_MILESTONE'
    assert result['size_pct_of_revenue'] is None


def test_latest_event_revision_supersedes_older_firm_value():
    p = packet()
    p['events'][0]['version_no'] = 1
    p['events'].append(dict(p['events'][0], version_no=2, amount_basis='NON_BINDING', stage='QUALIFIED'))
    assert triage(p)['triage_action'] == 'WATCH_MILESTONE'


def test_source_recheck_corrects_financing_number_and_mixed_commitment(db):
    from test_commercial import _seed, _filing
    from inflection.asof import IST
    from inflection.audit import recheck_packet
    iss, src = _seed(db)
    text = ('The Preferential Allotment amounts to ₹ 33.24 Cr. '
            'Secured contract of High-Speed Corridor Project from GSRDCL worth of ₹ 5.7 Cr.')
    tid = _filing(db, iss, src, 730, datetime(2025, 1, 10, tzinfo=IST), [text])
    quote = next(m.quote for m in extract_document([(1, text)])[0] if m.family == 'ORDER')
    p = packet(); p['company'] = dict(issuer_id=str(iss))
    p['events'][0]['amount'] = '33.24 INR CRORE'
    p['trigger_passages'] = [dict(event_id='external', text_artifact_id=str(tid), page_no=1, quote=quote)]
    fixed = recheck_packet(db, p)
    assert fixed['events'][0]['amount'] == '5.7 INR CRORE'
    assert p['events'][0]['amount'] == '33.24 INR CRORE'


def test_existing_policy_receives_only_pre_award_history(db):
    from test_commercial import _seed, _filing
    from inflection.asof import IST
    from inflection.commercial import pipeline
    from inflection.triage.screen import apply_policy
    iss, src = _seed(db)
    for n, month, amount, customer in [(740, 1, 20, 'North Utility Limited'),
                                       (741, 2, 100, 'West Utility Limited'),
                                       (742, 3, 200, 'East Utility Limited')]:
        _filing(db, iss, src, n, datetime(2025, month, 1, tzinfo=IST),
                [f'The Company has received an order worth Rs {amount} crore from {customer}.'])
    pipeline.scan(db); pipeline.resolve(db)
    event = db.execute('SELECT event_id FROM event_versions WHERE magnitude=100 ORDER BY version_no DESC LIMIT 1').fetchone()[0]
    p = packet()
    p['manifest']['cutoff'] = '2025-04-01T00:00:00+05:30'
    p['events'][0].update(event_id=str(event), amount='100 INR CRORE', published_at='2025-02-01 00:00 IST')
    def policy(derived, *args, **kwargs):
        assert derived['_audit_prior_orders']['sizes'] == [20.0]
        assert derived['_audit_prior_orders']['count'] == 1
        assert derived['_audit_prior_orders']['excluded_event_id'] == str(event)
        return dict(triage_action='WATCH_MILESTONE', rationale='Research policy preserved')
    assert apply_policy(policy, p, db, iss)['triage_action'] == 'WATCH_MILESTONE'


def test_financial_recheck_refreshes_reconstruction_without_leaking_into_actual_replay(db):
    from test_commercial import _seed
    from inflection.audit import recheck_financials
    iss, _ = _seed(db)
    p = packet(); p['company'] = dict(issuer_id=str(iss))
    p['manifest']['mode'] = 'PUBLIC_INFORMATION_RECONSTRUCTION'
    fixed = recheck_financials(db, p)
    assert fixed['financials']['ttm']['revenue']['value'] == '1,500.00'
    assert p['financials']['ttm']['revenue']['value'] == '100'
    p['manifest']['mode'] = 'ACTUAL_SYSTEM_REPLAY'
    actual = recheck_financials(db, p)
    assert actual['financials']['status'] == 'MISSING'
    assert actual['financial_recheck']['eligible_facts'] == 0


@pytest.mark.parametrize('description', ['a Tata Group company', 'a Reliance Group company', 'a subsidiary of Global Mobility Corporation'])
def test_customer_belonging_to_another_group_is_not_internal(description):
    text = f'The Company has received an order of INR 4135 lakh from Tejas Networks Limited, {description}.'
    orders = [m for m in extract_document([(1, text)])[0] if m.family == 'ORDER']
    assert orders and all(m.relationship == 'UNKNOWN' for m in orders)


def test_negative_promoter_declaration_does_not_invert_its_meaning():
    text = 'None of the promoter/ promoter group/ group companies have any interest in any of the entity that awarded the order(s).'
    assert _relationship(text, None, None)[0] == 'ISSUER_ASSERTED_UNRELATED'


def test_valiant_style_multiline_annexure():
    pages = [(1, 'The Company has received an order worth INR 4135 lakh from Tejas Networks Limited, a Tata Group company.'),
             (2, 'Whether the order(s) / contract(s) would fall within related party transactions? '
                 'If yes, whether the same is done at arm’s length?\nNo')]
    m = extract_document(pages)[0][0]
    assert m.relationship == 'ISSUER_ASSERTED_UNRELATED'
    assert m.details['relationship_from_document']


def test_positive_issuer_relationship_is_preserved_and_conflict_is_flagged():
    text = 'The Company has received an order worth Rs 100 crore from its group company.'
    assert extract_document([(1, text)])[0][0].relationship == 'CONFIRMED_RELATED'
    m = extract_document([(1, text), (2, 'Whether the order would fall within related party transactions? No')])[0][0]
    assert m.relationship == 'UNKNOWN' and m.details['relationship_conflict']


def packet():
    return dict(manifest=dict(cutoff='2026-09-30T18:30:00+00:00'),
                financials=dict(ttm=dict(revenue=dict(value='100',period_end='2026-06-30'), pat=dict(value='10'))),
                events=[dict(event_id='external', event_type='ORDER', stage='BINDING_DEMAND',
                             amount='20 INR CRORE', amount_basis='FIRM', relationship='UNKNOWN',
                             observation_status='OBSERVED',published_at='2026-09-01T12:00:00+05:30')])


def test_unrelated_event_is_not_vetoed_by_another_related_order():
    p = packet()
    p['events'].append(dict(p['events'][0], event_id='internal', amount='90 INR CRORE', relationship='CONFIRMED_RELATED'))
    result = triage(p)
    assert result['triage_action'] == 'DEEP_RESEARCH' and result['selected_event_id'] == 'external'
    assert result['size_pct_of_revenue'] == 20 and result['disqualifier'] is None


def test_internal_only_order_still_rejected():
    p = packet(); p['events'][0]['relationship'] = 'CONFIRMED_RELATED'
    assert triage(p)['disqualifier'] == 'INTERNAL_DEMAND'


@pytest.mark.parametrize('change', [dict(deadline='2025-12-31'), dict(stage='CANCELLED'), dict(amount_basis='CEILING')])
def test_stale_cancelled_or_ceiling_is_not_admitted_as_a_new_firm_order(change):
    p = packet(); p['events'][0].update(change)
    assert triage(p)['triage_action'] != 'DEEP_RESEARCH'


def test_cycle_evidence_is_a_watch_without_inventing_an_award_value():
    p = packet(); p['events'] = []
    p['valuation'] = dict(opm_change_pts='2.0', revenue_growth_ttm_pct='5.0')
    p['order_book'] = [dict(quarter_end='2026-06-30', book_yoy_pct=30, sources={'book': {'publication_id': 'source'}})]
    assert cycle_watch(p)
    result = triage(p)
    assert result['triage_action'] == 'WATCH_MILESTONE' and result['size_pct_of_revenue'] is None
    p['order_book'][0]['book_doubtful'] = True
    assert not cycle_watch(p)


def test_unknown_period_and_missing_provenance_do_not_support_cycle():
    p = packet(); p['valuation'] = dict(opm_change_pts='2')
    p['order_book'] = [dict(quarter_end='2026-06-30', inflow_yoy_pct=50)]
    assert not cycle_watch(p)


@pytest.mark.parametrize('text,expected', [('Order intake for the full year', 'ANNUAL'),
    ('Quarterly order inflow', 'QUARTER'), ('Order intake in the nine months', 'NINE_MONTHS'),
    ('Order intake for H1', 'HALF_YEAR'), ('Order inflow increased', 'UNKNOWN')])
def test_intake_reporting_duration(text, expected):
    assert inflow_period(text) == expected


def test_source_recheck_uses_the_original_no_answer_and_preserves_frozen_packet(db):
    from test_commercial import _seed, _filing
    from inflection.asof import IST
    from inflection.audit import recheck_packet
    iss, src = _seed(db)
    text = 'The Company has received an order worth INR 4135 lakh from Tejas Networks Limited, a Tata Group company.'
    ann = 'Whether the order(s) / contract(s) would fall within No related party transactions? If yes, whether the same is done at arm’s length'
    tid = _filing(db, iss, src, 700, datetime(2025, 1, 10, tzinfo=IST), [text, ann])
    p = packet(); p['company'] = dict(issuer_id=str(iss))
    p['events'][0]['relationship'] = 'CONFIRMED_RELATED'
    p['trigger_passages'] = [dict(event_id='external', text_artifact_id=str(tid), page_no=1, quote=text)]
    result = recheck_packet(db, p)
    assert result['events'][0]['relationship'] == 'ISSUER_ASSERTED_UNRELATED'
    assert p['events'][0]['relationship'] == 'CONFIRMED_RELATED'
    p['manifest']['cutoff'] = '2024-01-01T00:00:00+00:00'
    assert recheck_packet(db, p)['events'][0]['relationship'] == 'CONFIRMED_RELATED'


def test_series_never_uses_later_revenue_or_different_intake_period(db):
    from test_commercial import _seed, _filing
    from inflection.asof import IST
    from inflection.orderbook import series
    iss, src = _seed(db)
    for n, when, qe, amount, wording in [
        (710, datetime(2025, 5, 1, tzinfo=IST), '2025-03-31', 100, 'Order intake for the full year was Rs 100 crore'),
        (711, datetime(2026, 5, 1, tzinfo=IST), '2026-03-31', 130, 'Order intake for the quarter was Rs 130 crore')]:
        tid = _filing(db, iss, src, n, when, [wording])
        pid = db.execute('SELECT publication_id FROM document_publications p JOIN text_artifacts t USING(document_version_id) WHERE t.text_artifact_id=%s', (tid,)).fetchone()[0]
        db.execute('''INSERT INTO order_book_figures(issuer_id,publication_id,published_at,quarter_end,kind,amount_cr,sentence,extractor_version)
            VALUES(%s,%s,%s,%s,'INFLOW',%s,%s,'orderbook-2')''', (iss,pid,when,qe,amount,wording))
    cutoff = datetime(2026, 5, 2, tzinfo=IST)
    result = series(db, iss, cutoff)
    assert result[-1]['inflow_yoy_pct'] is None
    assert result[-1]['inflow_period_basis'] == 'QUARTER'
    assert result[-1]['sources']['inflow']['publication_id']
    # A later restatement must not enter the historical revenue read.
    db.execute('''INSERT INTO financial_facts(issuer_id,metric,period_end,scope,value,value_kind,currency,scale,
        period_type,available_at,provider,provider_version,content_hash)
        VALUES(%s,'revenue','2025-03-31','CONSOLIDATED',1,'MONEY','INR','UNITS','QUARTER',
        '2027-01-01','test','2','later-revision')''', (iss,))
    assert series(db, iss, cutoff) == result


def test_aggregate_intake_cannot_fill_an_unquantified_individual_award():
    pages = [(1, 'The Company has received a work order from NTPC Limited for supply of transformers. '
                 'The annual order inflow is worth Rs 5791 crore.')]
    orders = [m for m in extract_document(pages)[0] if m.family == 'ORDER']
    assert orders and all(m.amount is None for m in orders)


def test_cycle_watch_requires_current_and_public_sources():
    p = packet(); p['valuation'] = dict(opm_change_pts='2')
    p['order_book'] = [dict(quarter_end='2022-03-31', book_yoy_pct=40, sources={'book': {'published_at':'2022-05-01T00:00:00+00:00'}})]
    assert not cycle_watch(p)
    p['order_book'][0]['quarter_end'] = '2026-06-30'
    p['order_book'][0]['sources']['book']['published_at'] = '2027-01-01T00:00:00+00:00'
    assert not cycle_watch(p)


def test_old_undated_execution_is_not_recycled_as_a_fresh_pick():
    p = packet(); p['events'][0]['published_at'] = '2022-03-31 12:04 IST'
    result = triage(p)
    assert result['triage_action'] != 'DEEP_RESEARCH'
    assert 'old disclosure' in result['excluded_events'][0]['reason']


def test_period_before_award_wording_is_not_a_single_contract():
    text = 'In the fourth quarter alone, we secured orders worth INR 86 billion, a staggering increase over the last year.'
    assert not [m for m in extract_document([(1,text)])[0] if m.family == 'ORDER']


def test_recheck_marks_legacy_aggregate_even_when_new_extractor_drops_it(db):
    from test_commercial import _seed, _filing
    from inflection.asof import IST
    from inflection.audit import recheck_packet
    iss, src = _seed(db)
    text = 'In the fourth quarter alone, we secured orders worth INR 86 billion, a staggering increase over the last year.'
    tid = _filing(db, iss, src, 720, datetime(2026, 5, 26,tzinfo=IST), [text])
    p = packet();p['company'] = dict(issuer_id=str(iss))
    p['trigger_passages'] = [dict(event_id='external',text_artifact_id=str(tid),page_no=1,quote=text)]
    fixed = recheck_packet(db,p)
    assert fixed['events'][0]['details']['aggregate_order_total']
    assert triage(fixed)['triage_action'] != 'DEEP_RESEARCH'


def test_audit_wrapper_preserves_existing_policy_and_scopes_the_selected_event():
    from inflection.triage.screen import apply_policy
    p=packet();p['events'].append(dict(p['events'][0],event_id='internal',relationship='CONFIRMED_RELATED'))
    def policy(derived,*args,**kwargs):
        assert [e['event_id'] for e in derived['events']] == ['external']
        return dict(triage_action='WATCH_MILESTONE',rationale='Existing policy needs confirmation',custom_signal='preserved')
    result=apply_policy(policy,p)
    assert result['triage_action']=='WATCH_MILESTONE' and result['custom_signal']=='preserved'


def test_audit_wrapper_cannot_promote_a_stale_award_through_existing_policy():
    from inflection.triage.screen import apply_policy
    p=packet();p['events'][0]['deadline']='2025-12-31'
    def policy(*args,**kwargs):
        raise AssertionError('The old policy must not receive a stale award')
    assert apply_policy(policy,p)['triage_action']!='DEEP_RESEARCH'


# ---------------- figures Haiku found sized as orders in the 2024-25 quality-repair packets

def _order(text):
    return next((m for m in extract_document([(1, text)])[0] if m.family == 'ORDER'), None)


@pytest.mark.parametrize('text,kind', [
    ('We have reported Rs. 154.59 crores of revenue during Q4 of FY24, a 60.74% Y-on-Y rise, growth is mainly '
     'driven by large orders executed in the enterprise segment.', 'REPORTED_REVENUE'),
    ('The Diversified Engineering revenue for Q2 FY25 is Rs. 416.36 crore compared to Rs. 433.56 crore in Q2 FY24 '
     'Received major orders from Tata Power, Toyota, KEC International', 'REPORTED_REVENUE'),
    ('During quarter ended 30th June 2025, the company completed 2 HAM projects worth INR1,605 crores and received '
     'LOA for our tunnel projects in State of Kerala.', 'COMPLETED_WORK'),
    ('• Cumulative Orders executed worth H 6744.81 Cr because of their superior strength to weight ratio', 'COMPLETED_WORK'),
    ('The anticipated cost of the project is Rs. 26,076 Crore and we have incurred Rs. 23,753 Crore till March 25. '
     'Five out of the seven contract packages have already been awarded.', 'PROJECT_COST'),
    ('During the year Company has won an order for ` 427.79 earth quake floods etc. Crores and the Company`s order '
     'book stood at ` 955 Crores as on 31st Mar 2024.', 'ORDER_BOOK'),
    ('With this order SPEL’s total order book stands at ₹ 49.52 Cr. We are thrilled to have been awarded this '
     'contract by the solar project company.', 'ORDER_BOOK'),
])
def test_revenue_completed_work_cost_and_book_figures_never_size_an_order(text, kind):
    from inflection.commercial.extract import figure_kind, amounts, split_page
    # whichever sentence the figure sits in, it is read as its kind and never becomes an order value
    for sent in split_page(1, text):
        for a in amounts(sent.text):
            if a.original_text.replace(' ', '') in ('Rs.154.59crores', 'Rs.416.36crore', 'INR1,605crores',
                                                     'Rs.26,076Crore', '955Crores', '₹49.52Cr', '6744.81Cr'):
                assert figure_kind(sent.text, a) == kind
    assert all(m.amount is None for m in extract_document([(1, text)])[0] if m.family == 'ORDER')


def test_order_value_survives_beside_an_order_book_balance():
    text = ('Well, the export order book currently which is Rs. 350 crores is on a higher side on account of the '
            'recent landmark export order that we bagged which was a single order of Rs. 200 crores.')
    assert str(_order(text).amount.value) == '200'


@pytest.mark.parametrize('text', [
    'Revenue grew 20% this year, and we bagged an order of Rs 50 crore from NTPC for supply of transformers.',
    'The company has received an order worth Rs. 30 crore from the Revenue Department of Government of Maharashtra.',
    'Aarvi Encon Limited has received a work contract worth INR 173.49 crore from a Leading Indian PSU.',
])
def test_revenue_words_elsewhere_do_not_remove_a_real_order_value(text):
    assert _order(text).amount is not None


@pytest.mark.parametrize('text', [
    'Although we secured INR1,600 crores in orders over the last 4 quarters, only 15% of these have been executed.',
    'In quarter 3, we secured INR1,318 crores of new orders, taking our year-to- date order inflow to INR3,743 crores.',
    'So as this quarter itself, we have secured about INR1,900 crores of orders, which is quite significant.',
    'We secured ₹15,920 million in new orders during the quarter, bringing our FY25 order inflow to ₹53,353 million.',
    'The company has successfully secured new orders worth Rs. 1,333 crores during the current financial year.',
    'The company has successfully received a new order of Rs 1,851 crore in the period of 2024- 2025.',
    'During the quarter, company secured domestic contracts from PGCIL and several SEBs, contributing to a total '
    'inflow of INR1,660 crores during the period.',
])
def test_period_totals_are_not_single_orders(text):
    from inflection.commercial import vocabulary as V
    assert _order(text) is None and V.PERIOD_INFLOW.search(text)


def test_hyphenated_order_book_slide_is_not_an_order():
    text = ("Near-term revenue visibility from order-book position Strong order-book of freight cars (Dec'23) 1,847 "
            "Private 1,637 18% 1,413 1,331 1 1,077 INR 57 bn 482 82% Indian 127 Railways Q1 FY'23 Q2 FY'23 Q3 FY'23 "
            "Q4 FY'23 Q1 FY'24 Q2 FY'24 Q3 FY'24 Strategic alliance with Hindalco Won its largest ever order of "
            "20,000+ freight cars")
    assert _order(text) is None


def test_contracts_bundle_is_an_aggregate():
    text = '• Secured ₹88.51 Crore in strategic contracts across Government, Healthcare, Technology, and Enterprise'
    assert _order(text).details['aggregate_order_total']


def test_amount_is_not_a_counterparty():
    from inflection.commercial.extract import clean_counterparty
    assert clean_counterparty('200 Million') == '' and clean_counterparty('Million from one') == ''
    assert clean_counterparty('Tata Power') == 'Tata Power'


def test_short_tax_inclusive_forms_are_read():
    assert _order('₹ 142.31 crores (incl taxes) order received from DRDO.').details['tax_basis'] == 'INCLUSIVE'


def test_recheck_unsizes_reported_revenue_and_marks_the_why_now_line(db):
    from test_commercial import _seed, _filing
    from inflection.asof import IST
    from inflection.audit import recheck_packet
    iss, src = _seed(db)
    text = ('We have reported Rs. 154.59 crores of revenue during Q4 of FY24, growth is mainly driven by large '
            'orders executed in the enterprise segment.')
    tid = _filing(db, iss, src, 750, datetime(2025, 1, 10, tzinfo=IST), [text])
    p = packet(); p['company'] = dict(issuer_id=str(iss))
    p['events'][0]['amount'] = '154.59 INR CRORE'
    p['why_now'] = dict(evaluations=[dict(detail=['ORDER COMMERCIAL_SHIPMENT (was none, NEW); 154.59 INR CRORE FIRM; '
                                                  'materiality MATERIALITY_UNKNOWN: order is 33.6% of annual revenue'])])
    p['trigger_passages'] = [dict(event_id='external', text_artifact_id=str(tid), page_no=1, quote=text)]
    fixed = recheck_packet(db, p)
    assert fixed['events'][0]['amount'] is None
    assert fixed['source_recheck']['figure_corrections'][0]['kind'] == 'REPORTED_REVENUE'
    assert 'reported revenue, not an order value; not sized' in fixed['why_now']['evaluations'][0]['detail'][0]
    assert triage(fixed)['size_pct_of_revenue'] is None


def test_recheck_keeps_a_value_tax_inclusive_once_any_passage_says_so(db):
    from test_commercial import _seed, _filing
    from inflection.asof import IST
    from inflection.audit import recheck_packet
    iss, src = _seed(db)
    later = 'The Company has received an order worth Rs. 65.48 crore from West Bengal Livestock Development Corporation.'
    tid = _filing(db, iss, src, 751, datetime(2025, 1, 10, tzinfo=IST), [later])
    p = packet(); p['company'] = dict(issuer_id=str(iss))
    p['events'][0]['amount'] = '65.48 INR CRORE'
    p['trigger_passages'] = [dict(event_id='external', text_artifact_id=str(tid), page_no=1, quote=later)]
    p['prior_passages'] = [dict(event_id='external', quote='Award of Contract, amounting to Rs. 65.48 Crore including '
                                                          'GST and all other charges / taxes.')]
    fixed = recheck_packet(db, p)
    assert fixed['events'][0]['details']['tax_basis'] == 'INCLUSIVE'
    assert triage(fixed)['size_pct_of_revenue'] is None


@pytest.mark.parametrize('text,deadline', [
    ('During FY 22-23 the Company bagged an order for 20,067 wagons valuing approx. Rs. 6,450 crore.', None),
    ('The Company has received an order worth Rs 2,300 crore in FY22 from NHPC Limited.', None),
    ('The Company has received an order of Rs 120 crore from NTPC to be executed by Q3FY27.', '2026-12-31'),
])
def test_a_period_mention_is_not_a_completion_deadline(text, deadline):
    assert _order(text).details.get('deadline') == deadline


@pytest.mark.parametrize('text', [
    'Department of Space (DoS) has got Rs. 13,700 crore (US$ 1.83 billion) in 2022-23 for several key space missions.',
    'The Draft National Rail Plan outlines ambitious capital expenditure of Rs 38.22 lakh crore until 2050.',
])
def test_industry_and_government_figures_are_not_company_events(text):
    assert not extract_document([(1, text)])[0]


def test_recheck_converts_a_dollar_order_at_the_announcement_day_rate(db):
    from test_commercial import _seed
    from inflection.audit import recheck_packet
    iss, _ = _seed(db)
    db.execute("CREATE TABLE dashboard_fx_rates(currency text, rate_date date, inr_per_unit numeric, source text)")
    db.execute("INSERT INTO dashboard_fx_rates(currency,rate_date,inr_per_unit,source) VALUES ('USD','2026-08-28',84,'ECB')")
    p = packet(); p['company'] = dict(issuer_id=str(iss))
    p['events'][0].update(amount='3 USD MILLION', published_at='2026-09-01 12:00 IST',
                          deadline='2021-03-31')
    p['trigger_passages'] = [dict(event_id='external', text_artifact_id=None, quote='x')]
    fixed = recheck_packet(db, p)
    e = fixed['events'][0]
    assert e['details']['fx']['inr_crore'] == '25.20' and e['details']['fx']['rate_date'] == '2026-08-28'
    assert e['deadline'] is None
    result = triage(fixed)
    assert result['size_pct_of_revenue'] == pytest.approx(25.2) and 'DATED_FX_CONVERSION_REQUIRED' not in result.get('data_gaps', [])


def test_recheck_unsizes_an_industry_figure_kept_from_an_old_reading(db):
    from inflection.audit import recheck_packet
    from test_commercial import _seed
    iss, _ = _seed(db)
    p = packet(); p['company'] = dict(issuer_id=str(iss))
    p['events'][0].update(amount='13700 INR CRORE', deadline='2021-03-31', published_at='2022-09-04 16:02 IST')
    p['trigger_passages'] = [dict(event_id='external', text_artifact_id=None, quote='Department of Space (DoS) has '
                                  'got Rs. 13,700 crore (US$ 1.83 billion) in 2022-23 for several key space missions.')]
    fixed = recheck_packet(db, p)
    assert fixed['events'][0]['amount'] is None and fixed['events'][0]['deadline'] is None


def test_an_execution_period_is_not_an_intake_period():
    from inflection.commercial import vocabulary as V
    assert not V.PERIOD_INFLOW.search('We secured two new orders worth Rs 600 crore over 12 months.')
    assert V.PERIOD_INFLOW.search('We secured INR1,600 crores in orders over the last 4 quarters.')


def test_an_expected_order_has_no_firm_value():
    m = _order('The Company expects to receive orders worth Rs 500 crore from Indian Railways in H2 FY27.')
    assert m.stage == 'AMBITION' and m.amount_basis == 'NON_BINDING'


def test_a_huge_order_heard_only_on_a_call_is_not_sized(db):
    from inflection.audit import recheck_packet
    from test_commercial import _seed
    iss, _ = _seed(db)
    p = packet(); p['company'] = dict(issuer_id=str(iss))
    p['events'][0].update(amount='625000 INR CRORE')
    p['trigger_passages'] = [dict(event_id='external', text_artifact_id=None, title='Transcript of earnings call',
                                  quote='one HVDC order, frame contract in England, is about 6,25,000 crores')]
    fixed = recheck_packet(db, p)
    assert fixed['events'][0]['details']['size_needs_filing']
    result = triage(fixed)
    assert result['size_pct_of_revenue'] is None and result['triage_action'] != 'DEEP_RESEARCH'


def test_one_disclosure_split_into_two_events_is_marked(db):
    from inflection.audit import recheck_packet
    from test_commercial import _seed
    iss, _ = _seed(db)
    p = packet(); p['company'] = dict(issuer_id=str(iss))
    p['events'].append(dict(p['events'][0], event_id='twin'))
    fixed = recheck_packet(db, p)
    assert fixed['events'][1]['details']['duplicate_of'] == 'external'
