from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest

from inflection.asof import IST
from inflection.commercial import pipeline as commercial, vocabulary as V
from inflection.commercial.extract import extract_document
from inflection.commercial.resolve import EventState, materiality
from inflection.triage.screen import apply_policy
from test_detection_audit import packet


@pytest.mark.parametrize('issue', ['aggregate_order_total', 'mixed_commitment'])
def test_source_uncertainty_cannot_create_individual_order_materiality(issue):
    from inflection.units import Money, Scale
    e = EventState('e','issuer','ORDER','ORDER',datetime(2025,1,1,tzinfo=IST),
                   amount=Money(Decimal(100),'INR',Scale.CRORE),basis='FIRM',details={issue:True})
    result = materiality(e,Decimal(100)*10**7)
    assert result.status == 'MATERIALITY_UNKNOWN'
    assert result.ratio_total is None


@pytest.mark.parametrize('update,gap', [
    ({'amount':'23 USD MILLION'}, 'DATED_FX_CONVERSION_REQUIRED'),
    ({'ownership_scope':'JOINT_VENTURE'}, 'ISSUER_ATTRIBUTABLE_VALUE_REQUIRED'),
])
def test_unverified_sizing_cannot_be_promoted_by_outer_policy(update,gap):
    p = packet();p['events'][0].update(update)
    def unsafe_policy(*args, **kwargs):
        pytest.fail('An unverified sizing input must not reach the promotion policy')
    result = apply_policy(unsafe_policy,p)
    assert result['triage_action']=='WATCH_MILESTONE'
    assert result['size_pct_of_revenue'] is None and gap in result['data_gaps']


def test_unknown_prior_order_values_cannot_prove_an_award_is_unusual(monkeypatch):
    from inflection.triage import screen
    p=packet();p['events'][0]['rules_version']='test'
    monkeypatch.setattr(screen,'prior_orders',lambda *args,**kwargs:([],1))
    result=screen.triage(p,object(),'issuer')
    assert result['triage_action']=='WATCH_MILESTONE'
    assert 'PRIOR_ORDER_VALUES_UNVERIFIED' in result['data_gaps']


def test_collaborative_award_does_not_imply_entire_value_belongs_to_issuer():
    body=('The Company received a Letter of Award in collaboration with Maps Global Civiltech '
          'Private Limited for supervision services from MSIDC worth Rs 23.46 crore.')
    order=next(m for m in extract_document([(1,body)])[0] if m.family=='ORDER')
    assert order.ownership_scope=='JOINT_VENTURE'
    assert order.counterparty=='MSIDC'


def test_customer_collaboration_is_not_issuer_joint_ownership():
    body=('The Company received an order worth Rs 100 crore from Alpha Utility Limited, '
          'which operates in collaboration with a global partner.')
    order=next(m for m in extract_document([(1,body)])[0] if m.family=='ORDER')
    assert order.ownership_scope=='UNKNOWN'


def test_individual_awards_recovered_from_bundle_keep_exact_source_spans():
    body = ('We secured seven significant new orders worth INR 55.77 crores. '
            'First from Brixo Industries, valued at INR 15.68 crores for EPC electrical works. '
            'Second from Blue Pine Energy Limited, valued at INR 9.62 crores for a fast-track EPC project '
            'involving the supply, installation, testing, and commissioning of a 66 kV double-circuit '
            'transmission line, along with 12 kilometers of underground cable.')
    orders = [m for m in extract_document([(4,body)])[0] if m.family=='ORDER']
    assert [m.amount.value for m in orders] == [Decimal('55.77'),Decimal('15.68'),Decimal('9.62')]
    for m in orders[1:]:
        assert m.stage=='BINDING_DEMAND' and m.amount_basis=='FIRM'
        assert body[m.span_start:m.span_end] == m.quote
        assert m.details['award_context']['page_no']==4
        assert not m.details.get('aggregate_order_total')


@pytest.mark.parametrize('pages', [
    [(1,'First from Brixo Industries, valued at INR 15.68 crores for EPC electrical works.')],
    [(1,'We expect to secure seven new orders worth INR 55.77 crores. First from Brixo Industries, valued at INR 15.68 crores.')],
    [(1,'We secured seven new orders worth INR 55.77 crores.'),
     (2,'First from Brixo Industries, valued at INR 15.68 crores.')],
])
def test_list_context_cannot_be_invented_or_carried_across_pages(pages):
    assert not any(m.details.get('award_context') for m in extract_document(pages)[0])


def test_repair_reprocesses_sources_refreshes_financials_and_is_append_only_idempotent(db,monkeypatch):
    from test_commercial import _seed, _filing
    from inflection.triage import pipeline as triage
    from inflection.packets import pipeline as packets
    from inflection.audit_repair import run
    iss,src = _seed(db)
    body = ('We secured two new orders worth Rs 600 crore over 12 months. '
            'First from North Utility Limited, valued at Rs 450 crore for EPC works. '
            'Second from South Utility Limited, valued at Rs 150 crore for EPC works.')
    tid = _filing(db,iss,src,900,datetime(2026,1,20,tzinfo=IST),[body])
    with monkeypatch.context() as old:
        old.setattr(V,'RULES_VERSION','legacy-audit-test')
        def legacy(pages):
            mentions,count = extract_document(pages)
            mentions = [m for m in mentions if not m.details.get('award_context')]
            for m in mentions:m.details.pop('aggregate_order_total',None)
            return mentions,count
        old.setattr(commercial,'extract_document',legacy)
        commercial.scan(db);commercial.resolve(db)
        triage.build(db,date(2026,3,16),mode='PUBLIC_INFORMATION_RECONSTRUCTION',
                     now=datetime(2026,3,25,tzinfo=IST))
        original = packets.assemble(db,date(2026,3,16))['packets'][0]['packet_id']
    frozen = db.execute('SELECT content_hash,content FROM triage_packets WHERE packet_id=%s',(original,)).fetchone()
    db.execute('''INSERT INTO financial_facts(issuer_id,metric,period_end,scope,value,value_kind,currency,scale,
        period_type,available_at,provider,provider_version,content_hash)
        VALUES(%s,'revenue','2025-12-31','CONSOLIDATED',5000000000,'MONEY','INR','UNITS','QUARTER',
        '2026-02-01','test','2','recovered-original')''',(iss,))
    report = run(db,[original])
    new_id = report['packets'][0]['packet_id']
    assert new_id != original and report['packets'][0]['status']=='REFRESHED'
    new = db.execute('SELECT content,supersedes_id FROM triage_packets WHERE packet_id=%s',(new_id,)).fetchone()
    assert str(new[1])==original
    assert new[0]['financials']['ttm']['revenue']['value']=='1,600.00'
    assert any(e.get('amount')=='450 INR CRORE' for e in new[0]['events'])
    assert db.execute('SELECT content_hash,content FROM triage_packets WHERE packet_id=%s',(original,)).fetchone()==frozen
    assert db.execute('SELECT count(*) FROM triage_reviews').fetchone()[0]==0
    again = run(db,[original])
    assert again['packets'][0]['status']=='UNCHANGED'
    assert again['packets'][0]['packet_id']==new_id
    assert db.execute('SELECT count(*) FROM commercial_scans WHERE rules_version=%s',(V.RULES_VERSION,)).fetchone()[0]==1


def test_scoped_empty_scan_and_resolution_cannot_drain_unrelated_work(db):
    from test_commercial import _seed, _filing
    iss,src=_seed(db)
    _filing(db,iss,src,901,datetime(2026,1,20,tzinfo=IST),['We received an order worth Rs 500 crore from NTPC Limited.'])
    assert not commercial.scan(db,artifact_ids=[])
    commercial.scan(db)
    assert not commercial.resolve(db,artifact_ids=[])
    assert db.execute('SELECT count(*) FROM events').fetchone()[0]==0
