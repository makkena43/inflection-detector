"""Issuer-independent regressions for stale inputs, late corrections and future leakage."""
from datetime import date,datetime,time,timedelta,timezone
from decimal import Decimal
import pytest
from inflection.asof import IST,available_at,eligible
from inflection.states import PublicationBasis,RunMode
from inflection.packets import contents as C,pipeline as P
from inflection.freshness import packet_revenue
from inflection import shareholding,programmes
from test_commercial import _seed,_filing
from test_packets import fact


def test_date_only_data_waits_for_the_whole_day():
    day=date(2026,1,1)
    assert available_at(PublicationBasis.DATE_ONLY,None,day)==datetime.combine(day,time.max,IST)
    assert not eligible(datetime(2026,1,1,23,59,59,500000,tzinfo=IST),RunMode.LIVE,
                        PublicationBasis.DATE_ONLY,published_date=day).eligible


def test_old_period_is_stale_even_if_the_filing_arrived_today():
    cutoff=datetime(2026,10,29,tzinfo=IST)
    facts=[fact('revenue',d,100) for d in ('2023-03-31','2023-06-30','2023-09-30','2023-12-31')]
    for f in facts:f['available_at']=cutoff-timedelta(hours=1)
    fin=C.financial_snapshot(facts,cutoff=cutoff)
    assert fin['freshness']['freshness']=='STALE'
    assert packet_revenue(dict(manifest=dict(cutoff=cutoff.isoformat()),financials=fin)) is None
    assert C.valuation(fin,dict(status='FOUND',market_cap_cr='400'))['status']=='STALE'


def test_future_reporting_period_is_not_a_historical_fact():
    cutoff=datetime(2026,1,1,tzinfo=IST)
    f=fact('revenue','2026-03-31',100);f['available_at']=cutoff-timedelta(days=1)
    assert C.financial_snapshot([f],cutoff=cutoff)['status']=='MISSING'


def test_price_returns_reject_old_base_and_ignore_future_prices():
    prices=[(date(2025,1,1),100,100),(date(2026,1,1),120,100),(date(2027,1,1),900,100)]
    p=C.price_summary(prices,[],date(2026,1,2))
    assert p['last_close']=='120.00'
    assert p['returns_pct']['1m']['value'] is None
    assert p['returns_pct']['12m']['value']=='20.0'


def test_stale_price_does_not_supply_current_market_cap():
    p=C.price_summary([(date(2025,1,1),100,100)],[],date(2026,1,1),Decimal(10000000))
    assert p['status']=='STALE' and 'market_cap_cr' not in p


def test_unreconciled_split_never_supplies_verified_return_or_share_adjustment():
    action=dict(kind='SPLIT',ex_date=date(2025,12,1),multiplier='.5',reconciled=False)
    p=C.price_summary([(date(2025,1,1),100,100),(date(2026,1,1),60,100)], [action],date(2026,1,2),
                      Decimal(10000000),shares_asof=date(2025,9,30))
    assert p['returns_pct']['12m']['value'] is None and 'market_cap_cr' not in p
    action['reconciled']=True
    p=C.price_summary([(date(2026,1,1),60,100)],[action],date(2026,1,2),Decimal(10000000),shares_asof=date(2025,9,30))
    assert p['market_cap_cr']=='120'


def test_shareholding_revisions_cannot_rewrite_an_earlier_read(db):
    iss,_=_seed(db)
    db.execute("""INSERT INTO shareholding_patterns(issuer_id,exchange,symbol,period_end,broadcast_at,
        promoter_pct,mf_pct,source,source_ref) VALUES(%s,'NSE','ABC','2025-12-31','2026-01-15',50,3,'test','timing')""",(iss,))
    cutoff=db.execute('SELECT clock_timestamp()').fetchone()[0]
    db.execute("UPDATE shareholding_patterns SET promoter_pct=60,mf_pct=9 WHERE source_ref='timing'")
    past=shareholding.series(db,iss,cutoff)
    assert past[-1]['promoter_pct']==50 and past[-1]['mf_pct']==3
    assert shareholding.series(db,iss)[-1]['mf_pct']==9
    assert shareholding.series(db,iss,datetime(2026,2,1,tzinfo=IST))==[]


def test_programme_outlay_uses_the_observed_version_not_a_later_revision(db):
    iss,src=_seed(db)
    tid=_filing(db,iss,src,990,datetime(2025,1,1,tzinfo=IST),['Government railway project'])
    pid=db.execute('SELECT publication_id FROM document_publications p JOIN text_artifacts t USING(document_version_id) WHERE text_artifact_id=%s',(tid,)).fetchone()[0]
    db.execute('UPDATE document_publications SET ingested_at=clock_timestamp() WHERE publication_id=%s',(pid,))
    gid=db.execute("""INSERT INTO govt_programmes(name,announced_date,outlay_cr,keywords,source_url)
        VALUES('test programme','2024-01-01',100,'rail','https://example.test/source') RETURNING programme_id""").fetchone()[0]
    db.execute("""INSERT INTO programme_mentions(programme_id,issuer_id,publication_id,published_at,is_order,snippet)
        VALUES(%s,%s,%s,'2025-01-01',true,'railway award')""",(gid,iss,pid))
    cutoff=db.execute('SELECT clock_timestamp()').fetchone()[0]
    db.execute('UPDATE govt_programmes SET outlay_cr=900 WHERE programme_id=%s',(gid,))
    assert programmes.exposure(db,iss,cutoff)[0]['outlay_cr']==100
    assert programmes.exposure(db,iss)[0]['outlay_cr']==900


def test_price_provider_selection_cannot_see_late_imports(db):
    iss,_=_seed(db)
    sec=db.execute('SELECT security_id FROM securities WHERE issuer_id=%s',(iss,)).fetchone()[0]
    db.execute("""INSERT INTO prices(security_id,trade_date,provider,provider_version,close,adjustment,recorded_at)
        VALUES(%s,'2025-12-30','bse_bhavcopy','a',100,'UNADJUSTED','2025-12-31'),
              (%s,'2025-12-31','nse_bhavcopy','a',999,'UNADJUSTED','2026-02-01')""",(sec,sec))
    rows,_=P._prices(db,dict(issuer_id=iss,cutoff=datetime(2026,1,2,tzinfo=IST),mode='ACTUAL_SYSTEM_REPLAY'))
    assert len(rows)==1 and rows[0][1]==100


def test_price_versions_and_duplicate_actions_are_not_double_counted(db):
    iss,_=_seed(db);sec=db.execute('SELECT security_id FROM securities WHERE issuer_id=%s',(iss,)).fetchone()[0]
    db.execute("""INSERT INTO prices(security_id,trade_date,provider,provider_version,close,adjustment)
        VALUES(%s,'2025-12-31','nse_bhavcopy','a',100,'UNADJUSTED'),
              (%s,'2025-12-31','nse_bhavcopy','b',101,'UNADJUSTED')""",(sec,sec))
    for v in ('a','b'):
        db.execute("""INSERT INTO corporate_actions(security_id,kind,ex_date,details,provider,provider_version,reconciled)
            VALUES(%s,'SPLIT','2025-12-01','{"price_multiplier":"0.5"}','test',%s,true)""",(sec,v))
    cutoff=db.execute('SELECT clock_timestamp()').fetchone()[0]
    db.execute("UPDATE corporate_actions SET reconciled=false WHERE provider_version='a'")
    rows,actions=P._prices(db,dict(issuer_id=iss,cutoff=cutoff,mode='ACTUAL_SYSTEM_REPLAY'))
    assert len(rows)==1 and rows[0][1]==101
    assert len(actions)==1 and actions[0]['multiplier']=='0.5' and actions[0]['reconciled']


def test_future_event_cannot_enter_screening():
    from inflection.triage.screen import event_block
    assert event_block(dict(published_at='2026-02-01T12:00:00+05:30'),datetime(2026,1,1,tzinfo=IST)) is not None


def test_commercial_materiality_never_uses_stale_or_future_revenue(db):
    from inflection.commercial.pipeline import annual_revenue
    iss,_=_seed(db)
    # Existing revenue ends in 2025; importing it again cannot make it current in 2028.
    assert annual_revenue(db,iss,datetime(2028,1,1,tzinfo=IST))[0] is None
    db.execute("""INSERT INTO financial_facts(issuer_id,metric,period_end,scope,value,value_kind,currency,scale,
        period_type,available_at,provider,provider_version,content_hash)
        VALUES(%s,'revenue','2028-03-31','CONSOLIDATED',999999,'MONEY','INR','UNITS',
               'ANNUAL','2026-01-01','test','1','future-period')""",(iss,))
    assert annual_revenue(db,iss,datetime(2028,1,1,tzinfo=IST))[0] is None


def test_later_financial_checkpoint_cannot_erase_an_earlier_candidate(db):
    from inflection.financial import pipeline as F
    from inflection import queue
    from test_financial_processing_audit import _results,at,BASE,_seed as seed_results
    iss,src=seed_results(db)
    _results(db,iss,src,1880,date(2024,9,30),at('2024-11-08'),**BASE)
    pid=_results(db,iss,src,1881,date(2025,9,30),at('2025-11-07'),**{**BASE,'total_expenses':850})
    F.scan(db,now=at('2025-11-08'))
    eid=db.execute('SELECT evaluation_id FROM financial_scans WHERE publication_id=%s',(pid,)).fetchone()[0]
    assert eid
    db.execute("UPDATE financial_scans SET available_at='2026-05-01',evaluation_id=NULL WHERE publication_id=%s",(pid,))
    rows=queue.evaluation_rows(db,end=at('2025-12-01'))
    assert eid in {r[10] for r in rows}


def test_timing_inventory_separates_listing_from_missing_download(db):
    from inflection.timing_audit import collect
    iss,src=_seed(db)
    db.execute("""INSERT INTO document_publications(source_id,external_id,source_url,attachment_url,
        published_at,publication_basis,first_seen_at,issuer_id)
        VALUES(%s,'timing-pending','https://example.test/source','https://example.test/a.pdf',
          '2026-10-01 12:00+05:30','EXCHANGE_TIMESTAMP','2026-10-01 12:02+05:30',%s)""",(src,iss))
    report=collect(db,date(2026,10,1),date(2026,10,1),datetime(2026,10,1,18,tzinfo=IST))
    s=report['sources'][0]
    assert s['listed_publications']==1 and s['awaiting_download']==1
    assert s['discovery_delay_p95_seconds']==120 and s['future_publications']==0


def test_midday_listing_does_not_verify_the_rest_of_the_day(db):
    from inflection.ingest import record_window,coverage_report
    from inflection.process_health import _unresolved_windows
    from inflection.sources.common import WindowResult,WindowStatus
    # A successful exchange snapshot cannot establish a full-day window at midday.
    today=datetime.now(IST).date()
    w=WindowResult(exchange='NSE',segment='equities',from_date=today,to_date=today,
                   status=WindowStatus.COMPLETE,announcements=[])
    r=record_window(db,w,observed_at=datetime.combine(today,time(12),IST))
    assert r.coverage_status.value=='PARTIAL'
    # Legacy COMPLETE rows also remain incomplete when the claimed end was in the future.
    src=db.execute('SELECT source_id FROM sources WHERE name=\'nse_announcements\'').fetchone()[0]
    start=datetime.combine(today,time.min,IST);end=start+timedelta(days=1)
    db.execute("""INSERT INTO ingestion_runs(source_id,segment,window_start,window_end,coverage_status,finished_at)
        VALUES(%s,'sme',%s,%s,'COMPLETE',%s)""",(src,start,end,start+timedelta(hours=12)))
    assert all(x['status']=='PARTIAL' for x in coverage_report(db,today,today)['windows'])
    assert any(x['coverage_status']=='PARTIAL' for x in _unresolved_windows(db,start,end))
