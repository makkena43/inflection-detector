"""Issuer-safe nomination packets, serialized generations and route-aware review."""
from copy import deepcopy
from datetime import date,timedelta
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import json
import psycopg
import pytest
from psycopg.types.json import Jsonb
from inflection.commercial import pipeline as C
from inflection.packets import pipeline as P,contents as PC
from inflection.triage import pipeline as T,screen
from test_commercial import _seed,_filing,SEBI_ANNEX,PO
from test_packets import CUTOFF

DAY=date(2026,3,16)


def setup(db,build=True):
    issuer,src=_seed(db);tid=_filing(db,issuer,src,6100,CUTOFF-timedelta(days=30),[SEBI_ANNEX])
    C.scan(db);C.resolve(db)
    if not build:return issuer,src,tid
    T.build(db,DAY,now=CUTOFF)
    it=P._items(db,DAY)[0];content,_=P.packet_for(db,it)
    return it,content,tid,src


def save(db,it,content):return P.store_packet(db,it,content,PC.TOKEN_BUDGET)


def test_packet_generations_handle_reversion_and_equal_transaction_times(db):
    it,a,_,_=setup(db);b=deepcopy(a);b['why_now']['reason']='Changed nomination context'
    with db.transaction():
        first=save(db,it,a);second=save(db,it,b);third=save(db,it,a)
        assert save(db,it,a)['status']=='UNCHANGED'
        assert P._latest(db,it['shortlist_id'],it['issuer_id'])[0]==third['packet_id']
    rows=db.execute('SELECT packet_id,supersedes_id,content,created_at FROM triage_packets ORDER BY content->\'manifest\'->>\'generation\'').fetchall()
    assert len(rows)==3 and len({r[3] for r in rows})==1
    assert rows[1][1]==rows[0][0] and rows[2][1]==rows[1][0]
    assert [r[2]['manifest']['generation'] for r in rows]==[1,2,3]
    assert first['packet_id']!=third['packet_id'] and PC.content_hash(first['content'])!=PC.content_hash(third['content'])


def test_parallel_packet_builds_publish_one_generation_from_consistent_snapshots(db,monkeypatch):
    setup(db);barrier=Barrier(2);original=P.packet_for;isolation=[]
    def checked(conn,*args,**kwargs):
        isolation.append(conn.execute('SHOW transaction_isolation').fetchone()[0]);return original(conn,*args,**kwargs)
    monkeypatch.setattr(P,'packet_for',checked)
    def build():
        with psycopg.connect(db.info.dsn,autocommit=True) as conn:
            barrier.wait(timeout=10);return P.assemble(conn,DAY)
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(lambda _:build(),range(2)))
    assert db.execute('SELECT count(*) FROM triage_packets').fetchone()[0]==1
    assert sorted(next(iter(r['counts'])) for r in results)==['NEW','UNCHANGED']
    assert isolation==['repeatable read','repeatable read']


def test_parallel_shortlist_builds_do_not_race_the_unique_week(db):
    setup(db,build=False);barrier=Barrier(2)
    def build():
        with psycopg.connect(db.info.dsn,autocommit=True) as conn:
            barrier.wait(timeout=10);return T.build(conn,DAY,now=CUTOFF)
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(lambda _:build(),range(2)))
    assert db.execute('SELECT count(*) FROM triage_shortlists').fetchone()[0]==1
    assert sum(bool(r.get('existing')) for r in results)==1


def test_changed_requested_policy_is_not_silently_ignored(db):
    setup(db)
    with pytest.raises(ValueError,match='policy differs'):T.build(db,DAY,now=CUTOFF,ranked_cap=2)
    assert T.build(db,DAY,now=CUTOFF,dry_run=True,ranked_cap=2)['policy']['ranked_cap']==2
    assert db.execute('SELECT policy->>\'ranked_cap\' FROM triage_shortlists').fetchone()[0] is None


def test_record_binds_current_reviewed_hash_and_preserves_it_after_rebuild(db):
    it,a,_,_=setup(db);first=save(db,it,a);b=deepcopy(a);b['why_now']['reason']='Changed';second=save(db,it,b)
    assert 'error' in T.record(db,DAY,'ABC','WATCH_MILESTONE')
    assert 'error' in T.record(db,DAY,'ABC','WATCH_MILESTONE',packet_hash=PC.content_hash(first['content']))
    assert T.record(db,DAY,'ABC','WATCH_MILESTONE',packet_hash=PC.content_hash(second['content']))['triage_action']=='WATCH_MILESTONE'
    save(db,it,a)
    assert db.execute('SELECT packet_id FROM triage_shortlist_items').fetchone()[0]==second['packet_id']
    assert db.execute("SELECT details->>'packet_hash' FROM audit_log WHERE action='TRIAGE_RECORDED'").fetchone()[0]==PC.content_hash(second['content'])


def test_export_preserves_same_packet_draft_and_archives_prior_packet_context(db,tmp_path):
    it,a,_,_=setup(db);first=save(db,it,a);out=P.export(db,DAY,tmp_path)
    folder=tmp_path/'2026-03-16'/'01-ABC';draft=folder/'triage_result.json'
    review=json.loads(draft.read_text());review.update(triage_action='WATCH_MILESTONE',rationale='My unfinished review')
    draft.write_text(json.dumps(review));original_packet=(folder/'packet.md').read_text()
    P.export(db,DAY,tmp_path);assert json.loads(draft.read_text())==review
    b=deepcopy(a);b['why_now']['reason']='Changed';second=save(db,it,b)
    out=P.export(db,DAY,tmp_path);assert len(out['archived_previous_exports'])==1
    from pathlib import Path
    backup=Path(out['archived_previous_exports'][0])
    assert json.loads((backup/'triage_result.json').read_text())==review
    assert (backup/'packet.md').read_text()==original_packet
    assert json.loads(draft.read_text())['packet_hash']==PC.content_hash(second['content'])


@pytest.mark.parametrize('fault',['foreign_evaluation','foreign_event','future_event','missing_evaluation','foreign_publication','bad_text_reference'])
def test_invalid_nomination_references_stay_pending_and_do_not_leak_other_company_data(db,fault):
    from test_triage import _issuer,_evaluation
    from test_decision_state_audit import version
    from uuid import uuid4
    it,_,tid,src=setup(db);it=deepcopy(it);other=_issuer(db,'BBB')
    if fault=='foreign_evaluation':
        _evaluation(db,other,CUTOFF-timedelta(days=5),'P1')
        value=db.execute('SELECT evaluation_id FROM candidate_evaluations WHERE issuer_id=%s',(other,)).fetchone()[0]
        it['evaluation_ids'].append(value)
    elif fault=='missing_evaluation':it['evaluation_ids'].append(uuid4())
    elif fault in ('foreign_event','future_event'):
        _,vid=version(db,other if fault=='foreign_event' else it['issuer_id'],'BINDING_DEMAND',
                       CUTOFF-timedelta(days=1) if fault=='foreign_event' else CUTOFF+timedelta(days=1))
        it['trigger_event_version_ids'].append(vid)
    else:
        components=db.execute('SELECT components FROM candidate_evaluations WHERE evaluation_id=%s',(it['evaluation_ids'][0],)).fetchone()[0]
        if fault=='foreign_publication':
            foreign=_filing(db,other,src,6101,CUTOFF-timedelta(days=2),['Foreign confidential marker'])
            components['filing']['publication_id']=str(db.execute('SELECT publication_id FROM document_publications WHERE document_version_id=(SELECT document_version_id FROM text_artifacts WHERE text_artifact_id=%s)',(foreign,)).fetchone()[0])
        else:components['filing']['text_artifact_id']='malformed-reference'
        eid=db.execute('''INSERT INTO candidate_evaluations(run_id,issuer_id,as_of,mode,policy_version,route,components,
          outcome,reasons,policy_hash,priority_class,queue_allocation,content_hash)
          VALUES(gen_random_uuid(),%s,%s,'LIVE','test','COMMERCIAL',%s,'ADMIT','{reason}','h',%s,'RANKED',gen_random_uuid()::text)
          RETURNING evaluation_id''',(it['issuer_id'],CUTOFF-timedelta(days=1),Jsonb(components),it['priority'])).fetchone()[0]
        it['evaluation_ids'].append(eid)
    content,markdown=P.packet_for(db,it)
    assert content['manifest']['nomination_status']=='VERIFICATION_REQUIRED'
    assert content['manifest']['completeness']!='COMPLETE'
    assert 'Foreign confidential marker' not in markdown
    assert screen.triage(content)['triage_action']=='WATCH_MILESTONE'


def test_replaced_nomination_cannot_retain_frozen_priority_without_verification(db,monkeypatch):
    from inflection.commercial import vocabulary as V
    it,_,_,_=setup(db)
    monkeypatch.setattr(V,'RULES_VERSION','commercial-next');monkeypatch.setattr(C,'extract_document',lambda pages:([],0))
    C.scan(db);content,_=P.packet_for(db,it)
    assert any('replaced or withdrawn' in reason for reason in content['manifest']['nomination_issues'])
    assert screen.triage(content)['triage_action']=='WATCH_MILESTONE'


@pytest.mark.parametrize('published_before',[True,False])
def test_zip_member_retrieval_respects_the_specific_publication_boundary(db,published_before):
    it,content,tid,src=setup(db);stored=save(db,it,content)
    doc=db.execute('SELECT document_id FROM document_versions WHERE document_version_id=(SELECT document_version_id FROM text_artifacts WHERE text_artifact_id=%s)',(tid,)).fetchone()[0]
    root=db.execute("INSERT INTO document_versions(document_id,sha256,storage_key,byte_size,media_type) VALUES(%s,%s,'zip',1,'application/zip') RETURNING document_version_id",(doc,f'{6200:064x}')).fetchone()[0]
    member=db.execute("INSERT INTO document_versions(document_id,sha256,storage_key,byte_size,media_type) VALUES(%s,%s,'member',1,'application/pdf') RETURNING document_version_id",(doc,f'{6201:064x}')).fetchone()[0]
    child=db.execute("INSERT INTO text_artifacts(document_version_id,extraction_method,extraction_version,status,pages_processed) VALUES(%s,'test','member','COMPLETE',1) RETURNING text_artifact_id",(member,)).fetchone()[0]
    db.execute('INSERT INTO text_pages(text_artifact_id,page_no,body) VALUES(%s,1,%s)',(child,'ZIP member evidence'))
    pub=db.execute('''INSERT INTO document_publications(document_version_id,source_id,external_id,source_url,published_at,
       publication_basis,issuer_id,pipeline_state) VALUES(%s,%s,'zip-boundary','https://x/archive.zip',%s,
       'EXCHANGE_TIMESTAMP',%s,'TEXT_READY') RETURNING publication_id''',
       (root,src,CUTOFF-timedelta(days=1) if published_before else CUTOFF+timedelta(days=1),it['issuer_id'])).fetchone()[0]
    result=P.page(db,str(stored['packet_id']),str(child),'1')
    if published_before:
        assert result['pages'][0]['text']=='ZIP member evidence'
        docs=P._documents(db,it,[{'components':{'filing':{'publication_id':str(pub)}}}],[])
        assert str(child) in {d['text_artifact_id'] for d in docs}
    else:assert 'not public' in result['error']


@pytest.mark.parametrize('variant',['no_order','small_order','internal_order','pricing_event','bad_financial'])
def test_financial_nominations_are_routed_to_financial_review_instead_of_order_rejection(variant):
    from test_detection_audit import packet
    p=packet();p['why_now']={'evaluations':[dict(route='FINANCIAL',priority='D' if variant=='bad_financial' else 'P2',
                                               unverified=['MARGIN_EXPANSION'] if variant=='bad_financial' else [],fired=['MARGIN_EXPANSION'])]}
    if variant in ('no_order','bad_financial'):p['events']=[]
    elif variant=='small_order':p['events'][0]['amount']='1 INR CRORE'
    elif variant=='internal_order':p['events'][0]['relationship']='CONFIRMED_RELATED'
    elif variant=='pricing_event':p['events'][0]['event_type']='PRICING'
    result=screen.triage(p)
    assert result['triage_action']==('DATA_REPAIR' if variant=='bad_financial' else 'WATCH_MILESTONE')
    assert result['review_route']=='FINANCIAL'
    def unsafe(*args,**kwargs):raise AssertionError('Financial review reached order-only policy')
    assert screen.apply_policy(unsafe,p)==result


def test_valid_order_is_not_blocked_by_an_additional_financial_nomination():
    from test_detection_audit import packet
    p=packet();p['why_now']={'evaluations':[dict(route='FINANCIAL',priority='P2')]}
    assert screen.triage(p)['triage_action']=='DEEP_RESEARCH'


def test_order_cycle_promotion_cannot_bypass_packet_verification_gaps(monkeypatch):
    from test_orderbook_processing_audit import engine
    from test_detection_audit import packet
    module=engine(monkeypatch);p=packet()
    initial=dict(triage_action='WATCH_MILESTONE',data_gaps=['NOMINATION_PACKET_VERIFICATION_REQUIRED'])
    monkeypatch.setattr(module,'acceleration',lambda *a,**k:pytest.fail('Unverified packet reached promotion'))
    assert module.order_cycle_event(initial,p,object(),'issuer')==initial


def test_legacy_packet_foreign_event_is_removed_and_verification_is_required(db):
    from inflection.audit import recheck_packet
    from test_triage import _issuer
    from test_decision_state_audit import version
    it,content,_,_=setup(db);other=_issuer(db,'BBB');eid,vid=version(db,other,'BINDING_DEMAND',CUTOFF-timedelta(days=1))
    content['events'].append(dict(content['events'][0],event_id=str(eid),version_id=str(vid)))
    content['manifest'].pop('nomination_issues',None);frozen=deepcopy(content)
    current=recheck_packet(db,content)
    assert content==frozen and str(eid) not in {e['event_id'] for e in current['events']}
    assert screen.triage(current)['triage_action']=='WATCH_MILESTONE'


def test_legacy_packet_foreign_evaluation_cannot_survive_a_current_recheck(db):
    from inflection.audit import recheck_packet
    from test_triage import _issuer,_evaluation
    it,content,_,_=setup(db);other=_issuer(db,'BBB');_evaluation(db,other,CUTOFF-timedelta(days=1),'P1',route='FINANCIAL')
    eid=db.execute('SELECT evaluation_id FROM candidate_evaluations WHERE issuer_id=%s',(other,)).fetchone()[0]
    content['manifest']['evaluation_ids'].append(str(eid));content['manifest']['completeness']='COMPLETE'
    content['manifest'].pop('nomination_issues',None)
    current=recheck_packet(db,content)
    assert current['manifest']['completeness']=='PARTIAL'
    assert all(e['route']!='FINANCIAL' for e in current['why_now']['evaluations'])
    assert screen.triage(current)['triage_action']=='WATCH_MILESTONE'


def test_changed_financial_inputs_quarantine_packet_until_calculation_reruns(db):
    from inflection.financial import pipeline as F
    from test_financial_route import _seed as results_seed,_results,BASE
    from inflection.asof import IST
    from datetime import datetime
    issuer,src=results_seed(db);at=lambda day:datetime.fromisoformat(day+'T18:30:00+05:30')
    _results(db,issuer,src,6300,date(2024,9,30),at('2024-11-07'),**BASE)
    _results(db,issuer,src,6301,date(2025,9,30),at('2025-11-07'),**{**BASE,'total_expenses':860});F.scan(db)
    day=date(2025,11,10);T.build(db,day,now=at('2025-11-18'))
    it=P._items(db,day)[0];content,_=P.packet_for(db,it)
    assert not content['manifest']['nomination_issues']
    db.execute('''INSERT INTO financial_facts(issuer_id,metric,period_end,scope,value,value_kind,currency,scale,
       period_type,available_at,provider,provider_version,publication_id,content_hash)
       SELECT issuer_id,metric,period_end,scope,value*2,value_kind,currency,scale,period_type,available_at,
       provider,'changed-input',publication_id,gen_random_uuid()::text FROM financial_facts
       WHERE issuer_id=%s AND metric='revenue' AND period_end='2025-09-30' ''',(issuer,))
    current,_=P.packet_for(db,it)
    assert any('inputs changed' in issue for issue in current['manifest']['nomination_issues'])
    assert screen.triage(current)['triage_action']=='WATCH_MILESTONE'


def test_deep_research_requires_packet_hash_and_verified_nomination(db):
    it,content,_,_=setup(db)
    assert 'error' in T.record(db,DAY,'ABC','DEEP_RESEARCH')
    content['manifest']['evaluation_ids'].append('00000000-0000-0000-0000-000000000001')
    stored=save(db,it,content)
    result=T.record(db,DAY,'ABC','DEEP_RESEARCH',packet_hash=PC.content_hash(stored['content']))
    assert 'verification' in result['error']
    assert db.execute('SELECT triage_action FROM triage_shortlist_items').fetchone()[0] is None


def test_manifest_includes_current_and_cited_text_generations(db):
    it,content,tid,_=setup(db)
    aid=db.execute('''INSERT INTO text_artifacts(document_version_id,extraction_method,extraction_version,status,
       pages_processed,text_sha256,created_at) SELECT document_version_id,'new-reader','v2','COMPLETE',1,'second-hash',
       clock_timestamp() FROM text_artifacts WHERE text_artifact_id=%s RETURNING text_artifact_id''',(tid,)).fetchone()[0]
    db.execute('INSERT INTO text_pages(text_artifact_id,page_no,body) VALUES(%s,1,%s)',(aid,SEBI_ANNEX))
    current,_=P.packet_for(db,it)
    artifacts={d['text_artifact_id'] for d in current['documents']}
    assert {str(aid),str(tid)}<=artifacts
    assert {str(aid),str(tid)}<={s['text_artifact_id'] for s in current['manifest']['sources']}


def test_consistent_reviewed_packet_can_still_enter_deep_research(db):
    it,content,_,_=setup(db);stored=save(db,it,content)
    result=T.record(db,DAY,'ABC','DEEP_RESEARCH',packet_hash=PC.content_hash(stored['content']))
    assert result['triage_action']=='DEEP_RESEARCH'
    assert db.execute('SELECT packet_id FROM triage_shortlist_items').fetchone()[0]==stored['packet_id']


def test_import_review_keeps_original_hash_when_export_folder_has_newer_packet(db):
    from inflection.packets.review_binding import review_packet
    it,a,_,_=setup(db);first=save(db,it,a)
    b=deepcopy(a);b['why_now']['reason']='Updated export';second=save(db,it,b)
    review=dict(issuer_id=str(it['issuer_id']),as_of=it['cutoff'].isoformat(),packet_hash=PC.content_hash(first['content']))
    assert review_packet(db,review,second['packet_id'],DAY)==first['packet_id']
    assert review_packet(db,review,first['packet_id'],DAY)==first['packet_id']


@pytest.mark.parametrize('fault',['issuer','cutoff','week','hash','timezone','nonfinite','nohash'])
def test_import_review_rejects_unproved_or_invalid_packet_binding(db,fault):
    from inflection.packets.review_binding import review_packet
    from uuid import uuid4
    it,a,_,_=setup(db);stored=save(db,it,a);week=DAY
    review=dict(issuer_id=str(it['issuer_id']),as_of=it['cutoff'].isoformat(),packet_hash=PC.content_hash(stored['content']))
    if fault=='issuer':review['issuer_id']=str(uuid4())
    elif fault=='cutoff':review['as_of']=(it['cutoff']-timedelta(days=1)).isoformat()
    elif fault=='week':week=DAY-timedelta(days=7)
    elif fault=='hash':review['packet_hash']='not-the-reviewed-content'
    elif fault=='timezone':review['as_of']=it['cutoff'].replace(tzinfo=None).isoformat()
    elif fault=='nonfinite':review['size_pct_of_revenue']='NaN'
    elif fault=='nohash':review.pop('packet_hash')
    with pytest.raises(ValueError):review_packet(db,review,stored['packet_id'],week)


def test_import_unbound_legacy_review_is_explicitly_unbound(db):
    from inflection.packets.review_binding import review_packet
    assert review_packet(db,{'triage_action':'WATCH_MILESTONE'}) is None
