from datetime import date, datetime
from decimal import Decimal

from inflection.asof import IST
from inflection import queue
from inflection.financial import pipeline as F, rules as R
from test_financial_route import _seed, _results, BASE, CR


def at(day):
    return datetime.fromisoformat(day+'T18:30:00+05:30')


def add_fact(db,issuer,pid,end,when,metric,value,*,currency='INR',scale='UNITS',ptype='QUARTER',recorded=None):
    return db.execute('''INSERT INTO financial_facts(issuer_id,publication_id,metric,period_end,scope,value,
        value_kind,currency,scale,period_type,available_at,provider,provider_version,content_hash,recorded_at)
        VALUES(%s,%s,%s,%s,'CONSOLIDATED',%s,'MONEY',%s,%s,%s,%s,'test','audit',gen_random_uuid()::text,coalesce(%s,now()))
        RETURNING fact_id''',(issuer,pid,metric,end,value,currency,scale,ptype,when,recorded)).fetchone()[0]


def test_latest_reporting_period_precedes_shortest_comparative_period():
    def fact(pt,end):return ('revenue',pt,date.fromisoformat(end),False,'CONSOLIDATED',None,Decimal(100),None,None,'i')
    assert F._main_period([fact('QUARTER','2024-12-31'),fact('ANNUAL','2025-03-31')])[:2] == ('ANNUAL',date(2025,3,31))


def test_cumulative_segment_result_cannot_overwrite_discrete_quarter():
    end=date(2025,9,30)
    def fact(cumulative,value):return ('segment_result','QUARTER',end,cumulative,'CONSOLIDATED','Solar',Decimal(value),None,None,'i')
    period=F._period([fact(False,-10),fact(True,-100)],'QUARTER',end,'CONSOLIDATED')
    assert period.segments['Solar']==-10


def test_one_filing_can_supply_its_own_comparative_figures(db):
    issuer,src=_seed(db);when=at('2025-11-07')
    pid=_results(db,issuer,src,800,date(2025,9,30),when,**{**BASE,'total_expenses':850})
    for metric,value in BASE.items():
        add_fact(db,issuer,pid,date(2024,9,30),when,metric,Decimal(value)*CR)
    result=F.scan(db,now=at('2025-11-08'))
    assert result['EVALUATED']==1 and not result['NO_COMPARABLE']
    row=db.execute('SELECT components FROM candidate_evaluations').fetchone()[0]
    assert row['filing']['publication_id']==row['filing']['comparable_publication_id']==str(pid)


def test_standalone_is_usable_until_same_period_consolidated_is_public(db):
    issuer,src=_seed(db)
    _results(db,issuer,src,810,date(2024,9,30),at('2024-11-07'),scope='STANDALONE',**BASE)
    _results(db,issuer,src,811,date(2024,9,30),at('2024-11-08'),**BASE)
    standalone=_results(db,issuer,src,812,date(2025,9,30),at('2025-11-07'),scope='STANDALONE',
                        **{**BASE,'total_expenses':850})
    F.scan(db,now=at('2025-11-07'))
    status=db.execute('SELECT status FROM financial_scans WHERE publication_id=%s AND rules_version=%s',
                      (standalone,R.RULES_VERSION)).fetchone()[0]
    assert status=='EVALUATED'
    assert len(queue.evaluation_rows(db,end=at('2025-11-07')))==0  # end is exclusive
    before=at('2025-11-08')
    assert len(queue.evaluation_rows(db,end=before))==1
    _results(db,issuer,src,813,date(2025,9,30),at('2025-11-08'),**BASE)
    F.scan(db,now=at('2025-11-09'))
    assert len(queue.evaluation_rows(db,end=before))==1  # later disclosure cannot rewrite the earlier cutoff
    assert queue.evaluation_rows(db,end=at('2025-11-09'))==[]
    assert len(queue.evaluation_rows(db,include_superseded=True))==1


def test_successful_scan_is_refreshed_after_late_comparative_recovery(db):
    issuer,src=_seed(db)
    prior=_results(db,issuer,src,820,date(2024,9,30),at('2024-11-08'),**BASE)
    current=_results(db,issuer,src,821,date(2025,9,30),at('2025-11-07'),**{**BASE,'total_expenses':850})
    F.scan(db);assert len(queue.evaluation_rows(db))==1
    add_fact(db,issuer,prior,date(2024,9,30),at('2024-11-08'),'total_expenses',850*CR)
    result=F.scan(db)
    assert result['NOT_NOMINATED']==1
    assert queue.evaluation_rows(db)==[]  # the old positive remains in history, not in the effective queue
    assert len(queue.evaluation_rows(db,include_superseded=True))==1
    assert F.scan(db)=={}


def test_unchanged_financial_output_reuses_evaluation_after_input_refresh(db):
    issuer,src=_seed(db)
    _results(db,issuer,src,830,date(2024,9,30),at('2024-11-08'),**BASE)
    current=_results(db,issuer,src,831,date(2025,9,30),at('2025-11-07'),**{**BASE,'total_expenses':850})
    F.scan(db)
    original=db.execute('SELECT evaluation_id FROM candidate_evaluations').fetchone()[0]
    add_fact(db,issuer,current,date(2025,9,30),at('2025-11-07'),'pat',100*CR)
    F.scan(db)
    assert db.execute('SELECT evaluation_id FROM candidate_evaluations').fetchall()==[(original,)]
    assert F.scan(db)=={}


def test_money_scale_is_normalized_and_foreign_currency_remains_unverified(db):
    issuer,src=_seed(db)
    pid=_results(db,issuer,src,840,date(2025,9,30),at('2025-11-07'),**BASE)
    add_fact(db,issuer,pid,date(2025,9,30),at('2025-11-07'),'revenue',1000,scale='CRORE')
    values=F._period(F._facts(db,pid,at('2025-11-07')),'QUARTER',date(2025,9,30),'CONSOLIDATED')
    assert values.values['revenue']==1000*CR
    add_fact(db,issuer,pid,date(2025,9,30),at('2025-11-07'),'revenue',1000,currency='USD')
    values=F._period(F._facts(db,pid,at('2025-11-07')),'QUARTER',date(2025,9,30),'CONSOLIDATED')
    assert values.get('revenue')==(None,'UNVERIFIED')


def test_later_disclosed_fact_and_future_filing_cannot_enter_an_earlier_scan(db):
    issuer,src=_seed(db)
    _results(db,issuer,src,850,date(2024,9,30),at('2024-11-08'),**BASE)
    current=_results(db,issuer,src,851,date(2025,9,30),at('2025-11-07'),**{**BASE,'total_expenses':850})
    add_fact(db,issuer,current,date(2026,3,31),at('2026-05-01'),'revenue',99999*CR)
    future=_results(db,issuer,src,852,date(2026,9,30),at('2026-11-07'),**BASE)
    result=F.scan(db,now=at('2025-11-08'))
    assert result['EVALUATED']==1
    row=db.execute('SELECT available_at,period_end FROM financial_scans WHERE publication_id=%s',(current,)).fetchone()
    assert row==(at('2025-11-07'),date(2025,9,30))
    assert db.execute('SELECT count(*) FROM financial_scans WHERE publication_id=%s',(future,)).fetchone()[0]==0


def test_scoped_financial_repair_does_not_process_unrelated_publications(db):
    issuer,src=_seed(db)
    first=_results(db,issuer,src,860,date(2024,9,30),at('2024-11-08'),**BASE)
    second=_results(db,issuer,src,861,date(2025,9,30),at('2025-11-07'),**{**BASE,'total_expenses':850})
    assert F.scan(db,publication_ids=[])=={}
    F.scan(db,publication_ids=[second])
    assert db.execute('SELECT publication_id FROM financial_scans').fetchall()==[(second,)]
    assert db.execute('SELECT count(*) FROM financial_scans WHERE publication_id=%s',(first,)).fetchone()[0]==0


def test_late_commit_is_detected_even_when_fact_timestamp_predates_scan(db):
    import psycopg
    issuer,src=_seed(db)
    prior=_results(db,issuer,src,870,date(2024,9,30),at('2024-11-08'),**BASE)
    current=_results(db,issuer,src,871,date(2025,9,30),at('2025-11-07'),**{**BASE,'total_expenses':850})
    # The prior filing is ingesting on a separate connection. Its row timestamp
    # precedes the scan, but that row is invisible until ingestion commits.
    with psycopg.connect(db.info.dsn) as ingest:
        fact_id=add_fact(ingest,issuer,prior,date(2024,9,30),at('2024-11-08'),'total_expenses',850*CR)
        F.scan(db,publication_ids=[current]);assert len(queue.evaluation_rows(db))==1
        recorded=ingest.execute('SELECT recorded_at FROM financial_facts WHERE fact_id=%s',(fact_id,)).fetchone()[0]
        scanned=db.execute('SELECT scanned_at FROM financial_scans WHERE publication_id=%s',(current,)).fetchone()[0]
        assert recorded<scanned
        ingest.commit()
    F.scan(db,publication_ids=[current])
    assert queue.evaluation_rows(db)==[]
    assert F.scan(db,publication_ids=[current])=={}


def test_unlinked_publication_is_retried_only_after_identity_changes(db):
    issuer,src=_seed(db)
    pid=_results(db,issuer,src,880,date(2025,9,30),at('2025-11-07'),**BASE)
    db.execute('UPDATE document_publications SET issuer_id=NULL WHERE publication_id=%s',(pid,))
    assert F.scan(db)['NO_ISSUER']==1
    assert F.scan(db)=={}  # stable failures cannot repeatedly consume the batch limit
    db.execute('UPDATE document_publications SET issuer_id=%s WHERE publication_id=%s',(issuer,pid))
    assert F.scan(db)['NO_COMPARABLE']==1


def test_input_fingerprint_is_independent_of_connection_timezone(db):
    issuer,src=_seed(db)
    pid=_results(db,issuer,src,890,date(2025,9,30),at('2025-11-07'),**BASE)
    first=F._input_fingerprint(db,pid)
    db.execute("SET TimeZone='America/New_York'")
    assert F._input_fingerprint(db,pid)==first
