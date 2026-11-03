"""Mixed-route decisions preserve source warnings and current event chronology."""
from copy import deepcopy
from datetime import datetime,timedelta
from itertools import permutations
import json
import pytest
from inflection import queue
from inflection.asof import IST

AT=datetime(2026,9,1,12,tzinfo=IST)


def row(key,route='COMMERCIAL',events=(),at=AT,priority='P3'):
    components={'events':list(events)} if route=='COMMERCIAL' else {'without_mechanism':['MARGIN_EXPANSION']}
    return ('issuer','SYM','Name',route,at,priority,'DEFER',['reason '+key],components,
            [2,1,-4,1],key,'NONE',[],True,at+timedelta(hours=1))


def event(**changes):
    e=dict(event_id='award',version_id='v1',event_type='ORDER',stage='BINDING_DEMAND',
           observation='OBSERVED',priority='P3',relationship='UNKNOWN')
    e.update(changes);return e


@pytest.mark.parametrize('details',[
 {'ocr_verification_required':True},{'source_recheck_conflict':True},{'history_conflict':True},
 {'relationship_conflict':True},{'relationship':'CONFIRMED_RELATED'}])
def test_source_warnings_cannot_be_lost_in_cross_route_promotion(details):
    result=queue.from_rows([row('fin','FINANCIAL'),row('com',events=[event(details=details)])])[0]
    assert result['priority']=='P3' and not result['corroborated']


@pytest.mark.parametrize('state',[{'observation':'UNKNOWN'},{'observation':None},
                                 {'stage':'CANCELLED'},{'stage':'EXPIRED'},{'stage':'EXECUTED'}])
def test_unproved_or_inactive_operating_events_cannot_promote(state):
    result=queue.from_rows([row('fin','FINANCIAL'),row('com',events=[event(**state)])])[0]
    assert result['priority']=='P3' and not result['corroborated']


def test_cancelled_award_retires_its_old_priority_in_every_input_order():
    rows=[row('fin','FINANCIAL'),row('award',events=[event(priority='P1')],priority='P1'),
          row('cancel',events=[event(version_id='v2',stage='CANCELLED')],at=AT+timedelta(days=2))]
    for ordering in permutations(rows):
        result=queue.from_rows(list(ordering))[0]
        assert result['priority']=='P3' and not result['corroborated']
        assert 'award' not in result['evaluation_ids']


def test_later_reinstatement_is_not_suppressed_by_old_cancellation():
    result=queue.from_rows([row('cancel',events=[event(stage='CANCELLED')]),row('fin','FINANCIAL'),
                           row('reinstated',events=[event(version_id='v2')],at=AT+timedelta(days=2))])[0]
    assert result['priority']=='P2' and result['corroborated']


def test_multi_award_filing_keeps_remaining_event_without_retired_priority():
    original=row('awards',events=[event(priority='P1'),event(event_id='other',version_id='other-v1',priority='P3')],priority='P1')
    rows=[original,row('fin','FINANCIAL'),row('cancel',events=[event(version_id='v2',stage='CANCELLED')],at=AT+timedelta(days=2))]
    before=deepcopy(rows);result=queue.from_rows(rows)[0]
    assert result['priority']=='P2' and result['corroborated']
    assert rows==before
    current=next(r for r in queue.current_commercial_rows(rows) if r[10]=='awards')
    assert current[5]=='P3' and len(current[8]['events'])==1
    assert current[12]==['other-v1']


@pytest.mark.parametrize('commissioned,expected',[(True,'P2'),(False,'P3')])
def test_observed_capacity_commissioning_is_preserved(commissioned,expected):
    result=queue.from_rows([row('fin','FINANCIAL'),row('capacity',events=[
        event(event_type='CAPACITY',stage='COMMERCIAL_START',details={'commissioned':commissioned})])])[0]
    assert result['priority']==expected


def test_queue_hydrates_immutable_source_warnings_omitted_by_old_summary(db):
    from test_commercial import _seed
    from test_decision_state_audit import version
    from psycopg.types.json import Jsonb
    from inflection.commercial import vocabulary as V
    issuer,_=_seed(db);eid,vid=version(db,issuer,'BINDING_DEMAND',AT)
    # Append a warning-bearing source version; immutable original remains stored.
    vid=db.execute("""INSERT INTO event_versions(event_id,version_no,event_type,commercial_stage,observation_status,
       magnitude,magnitude_currency,magnitude_scale,amount_basis,published_at,content_hash,details)
       VALUES(%s,2,'ORDER','BINDING_DEMAND','OBSERVED',100,'INR','CRORE','FIRM',%s,
       'quality-warning','{"ocr_verification_required":true}') RETURNING event_version_id""",(eid,AT)).fetchone()[0]
    for route,components in [('COMMERCIAL',{'events':[event(event_id=str(eid),version_id=str(vid))]}),
                             ('FINANCIAL',{'without_mechanism':['MARGIN_EXPANSION']})]:
        db.execute("""INSERT INTO candidate_evaluations(run_id,issuer_id,as_of,mode,policy_version,route,
            components,outcome,reasons,policy_hash,priority_class,content_hash)
            VALUES(gen_random_uuid(),%s,%s,'LIVE',%s,%s,%s,'DEFER','{reason}','test','P3',%s)""",
            (issuer,AT,V.RULES_VERSION if route=='COMMERCIAL' else 'test',route,Jsonb(components),route))
    rows=queue.evaluation_rows(db)
    result=queue.from_rows(rows)[0]
    assert result['priority']=='P3' and not result['corroborated']
    # Hydration changes only the derived read, never the frozen source evaluation.
    stored=db.execute("SELECT components FROM candidate_evaluations WHERE route='COMMERCIAL'").fetchone()[0]
    assert 'details' not in stored['events'][0]


def test_unverified_source_cannot_keep_a_legacy_high_priority():
    result=queue.from_rows([row('award',events=[event(priority='P1',details={'source_recheck_conflict':True})],priority='P1')])[0]
    assert result['priority']=='P3' and result['allocations']==['NONE']


def test_independent_verified_award_keeps_its_priority_alongside_uncertain_one():
    result=queue.from_rows([row('awards',events=[event(priority='P1',details={'ocr_verification_required':True}),
        event(event_id='other',version_id='v-other',priority='P1')],priority='P1')])[0]
    assert result['priority']=='P1'
