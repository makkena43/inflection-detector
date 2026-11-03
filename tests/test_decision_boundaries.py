"""Both error directions: bad inputs cannot admit or discard a candidate."""
from copy import deepcopy
from itertools import permutations
import pytest
from inflection.triage.screen import triage,apply_policy
from test_detection_audit import packet


@pytest.mark.parametrize('field,value,gap',[
 ('amount_basis',None,'COMMITMENT_BASIS_REQUIRED'),
 ('amount_basis','UNKNOWN','COMMITMENT_BASIS_REQUIRED'),
 ('amount_basis','UNQUANTIFIED','COMMITMENT_BASIS_REQUIRED'),
 ('observation_status',None,'OBSERVATION_STATUS_REQUIRED'),
 ('observation_status','UNKNOWN','OBSERVATION_STATUS_REQUIRED'),
])
def test_unproved_commitment_fields_are_pending_not_admitted_or_rejected(field,value,gap):
    p=packet();p['events'][0][field]=value
    result=triage(p)
    assert result['triage_action']=='WATCH_MILESTONE' and gap in result['data_gaps']
    assert not result['firm']
    def forbidden(*args,**kwargs):raise AssertionError('Unverified input reached legacy policy')
    assert apply_policy(forbidden,p)['triage_action']=='WATCH_MILESTONE'


@pytest.mark.parametrize('published',[None,'not a date','2026-09-01T12:00:00'])
def test_missing_or_invalid_publication_time_is_pending(published):
    p=packet();p['events'][0]['published_at']=published
    assert triage(p)['triage_action']=='WATCH_MILESTONE'


@pytest.mark.parametrize('change',[{'deadline':'2026-08-31'}, {'published_at':'2024-01-01T12:00:00+05:30'}])
def test_missing_fresh_execution_update_is_pending_not_business_rejection(change):
    p=packet();p['events'][0].update(change)
    result=triage(p)
    assert result['triage_action']=='WATCH_MILESTONE' and result['data_gaps']


def test_conflicting_relationship_does_not_establish_internal_demand_rejection():
    p=packet();p['events'][0].update(relationship='CONFIRMED_RELATED',details={'relationship_conflict':True})
    result=triage(p)
    assert result['triage_action']=='WATCH_MILESTONE' and result['disqualifier'] is None


def test_valid_candidate_survives_invalid_candidates_and_input_permutations():
    p=packet();valid=p['events'][0]
    candidates=[valid,dict(valid,event_id='missing-basis',amount='100 INR CRORE',amount_basis='UNKNOWN'),
                dict(valid,event_id='internal',amount='200 INR CRORE',relationship='CONFIRMED_RELATED'),
                dict(valid,event_id='future',amount='300 INR CRORE',published_at='2027-01-01T00:00:00+05:30')]
    for order in permutations(candidates):
        p['events']=list(order);before=deepcopy(p);result=triage(p)
        assert result['triage_action']=='DEEP_RESEARCH' and result['selected_event_id']=='external'
        assert p==before


def test_tied_valid_candidates_have_deterministic_selection():
    p=packet();p['events'].append(dict(p['events'][0],event_id='second-valid'))
    first=triage(p);p['events'].reverse()
    assert triage(p)==first


@pytest.mark.parametrize('amount',['625000 INR CRORE','161868600 INR CRORE'])
def test_implausible_order_size_is_held_for_verification(amount):
    p=packet();p['events'][0]['amount']=amount
    result=triage(p)
    assert result['triage_action']=='WATCH_MILESTONE' and 'ORDER_SIZE_IMPLAUSIBLE' in result['data_gaps']
    assert result['size_pct_of_revenue'] is None


def test_implausible_order_does_not_outrank_a_real_award():
    p=packet();p['events'].append(dict(p['events'][0],event_id='typo',amount='625000 INR CRORE'))
    result=triage(p)
    assert result['triage_action']=='DEEP_RESEARCH' and result['selected_event_id']=='external'
