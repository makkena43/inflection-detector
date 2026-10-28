"""Regressions from missed-signal audits; no stock-specific admission rules."""
from copy import deepcopy
from datetime import datetime

import pytest
from inflection.commercial.extract import extract_document, _relationship
from inflection.triage.screen import triage, cycle_watch
from inflection.orderbook import inflow_period


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
                financials=dict(ttm=dict(revenue=dict(value='100'), pat=dict(value='10'))),
                events=[dict(event_id='external', event_type='ORDER', stage='BINDING_DEMAND',
                             amount='20 INR CRORE', amount_basis='FIRM', relationship='UNKNOWN')])


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
