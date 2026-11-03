from copy import deepcopy
import json
from datetime import timedelta
import pytest
from inflection import packet_rebuild as R
from inflection.packets import pipeline as P,contents as C
from test_packet_process_audit import setup,save


def legacy(db,actual=False):
    it,p,_,_=setup(db);p=deepcopy(p);p['manifest']['packet_version']='triage-packet-12'
    if actual:
        it['mode']='ACTUAL_SYSTEM_REPLAY';p['manifest']['mode']=it['mode']
    active=C.PACKET_VERSION
    try:
        C.PACKET_VERSION='triage-packet-12';saved=save(db,it,p)
    finally:C.PACKET_VERSION=active
    return it,saved,R.targets(db)[0]


def test_rebuild_appends_current_packet_and_keeps_prior_decision_binding(db):
    it,old,target=legacy(db)
    from inflection.triage import pipeline as T
    assert T.record(db,it['week_start'],'ABC','WATCH_MILESTONE',packet_hash=C.content_hash(old['content']))['triage_action']=='WATCH_MILESTONE'
    before=db.execute('SELECT triage_action,packet_id,revision FROM triage_shortlist_items').fetchone()
    result=R.rebuild(db,target)
    assert result['status']=='UPDATED' and result['original_packet_id']==str(old['packet_id'])
    newest=P._latest(db,it['shortlist_id'],it['issuer_id'])
    assert newest[2]['manifest']['packet_version']==C.PACKET_VERSION
    assert db.execute('SELECT triage_action,packet_id,revision FROM triage_shortlist_items').fetchone()==before
    assert db.execute('SELECT supersedes_id FROM triage_packets WHERE packet_id=%s',(result['packet_id'],)).fetchone()[0]==old['packet_id']
    assert R.rebuild(db,target)['status']=='ALREADY_CURRENT'
    assert R.targets(db)==[]


def test_rebuild_retains_original_cutoff_and_missing_nomination_as_pending_evidence(db):
    from uuid import uuid4
    it,old,target=legacy(db)
    db.execute('UPDATE triage_shortlist_items SET evaluation_ids=array_append(evaluation_ids,%s) WHERE shortlist_id=%s',(uuid4(),it['shortlist_id']))
    result=R.rebuild(db,target)
    assert result['status']=='UPDATED' and result['nomination_issues']
    current=P._latest(db,it['shortlist_id'],it['issuer_id'])[2]
    assert current['manifest']['cutoff']==old['content']['manifest']['cutoff']
    assert current['manifest']['nomination_status']=='VERIFICATION_REQUIRED'


def test_job_checkpoint_resumes_after_commit_without_duplicate_generations(db,tmp_path):
    it,old,target=legacy(db)
    result=R.run(db,tmp_path,guard=lambda:None)
    assert result['completed']==1 and result['remaining']==0
    assert R.run(db,tmp_path,guard=lambda:None)['completed']==1
    assert db.execute('SELECT count(*) FROM triage_packets').fetchone()[0]==2
    # Simulate commit followed by interruption before writing the journal.
    (tmp_path/'results.jsonl').write_text('')
    assert R.run(db,tmp_path,guard=lambda:None)['counts']=={'ALREADY_CURRENT':1}
    assert db.execute('SELECT count(*) FROM triage_packets').fetchone()[0]==2


def test_storage_guard_rolls_back_before_append_and_retains_unprocessed_target(db,tmp_path):
    it,old,target=legacy(db);calls=[]
    def guard():
        calls.append(1)
        if len(calls)>1:raise RuntimeError('STORAGE_LIMIT: test reserve')
    state=R.run(db,tmp_path,guard=guard)
    assert state['state']=='STORAGE_LIMIT' and state['remaining']==1
    assert db.execute('SELECT count(*) FROM triage_packets').fetchone()[0]==1
    assert R.run(db,tmp_path,guard=lambda:None)['completed']==1


def test_actual_system_replay_is_not_rewritten(db):
    it,old,target=legacy(db,actual=True)
    result=R.rebuild(db,target)
    assert result['status']=='PENDING' and 'frozen' in result['reason']
    assert db.execute('SELECT count(*) FROM triage_packets').fetchone()[0]==1
