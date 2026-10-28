"""Process invariants across arbitrary issuers; no named-company admission exceptions."""
from datetime import date,datetime,timedelta,timezone
from decimal import Decimal
import pytest
from inflection.asof import IST
from inflection.packets import contents as C
from inflection.financial import pipeline as F
from inflection.replay import rules as R
from inflection.periods import consecutive_quarters
from test_packets import fact,QUARTER_ENDS
from test_commercial import _seed,_filing


def financials(ends=None):
    ends=ends or QUARTER_ENDS[-8:]
    facts=[]
    for end in ends:
        for metric,v in [('revenue',100),('pbt',5),('finance_cost',1),('depreciation',2),('other_income',0)]:
            facts.append(fact(metric,end,v))
    return C.financial_snapshot(facts)


def test_valuation_refuses_four_nonconsecutive_quarters():
    fin=financials(['2024-03-31','2024-06-30','2025-03-31','2025-12-31'])
    assert fin['ttm']['revenue']['value'] is None
    assert C.valuation(fin,{'market_cap_cr':'100'})['price_to_sales'] is None


def test_missing_other_income_is_unknown_not_zero():
    fin=financials();fin['rows']['other_income'][-1]['value']=None
    assert C.valuation(fin,{})['opm_ttm_pct'] is None


def test_valuation_requires_a_consecutive_eight_quarter_growth_comparison():
    fin=financials();fin['quarters'][0]='2022-03-31'
    v=C.valuation(fin,{})
    assert v['opm_ttm_pct'] is not None
    assert v['revenue_growth_ttm_pct'] is None and v['opm_change_pts'] is None


def test_share_count_cannot_pair_capital_and_face_value_from_different_filings():
    fs=[fact('revenue','2025-12-31',100),fact('paid_up_capital','2025-12-31',10,pub='a'),
        fact('face_value','2025-12-31',10,kind='PER_SHARE',pub='b')]
    assert C.financial_snapshot(fs)['shares']['value'] is None
    fs[-1]['publication_id']='a'
    assert C.financial_snapshot(fs)['shares']['value']=='1.000'


@pytest.mark.parametrize('ends',[[date(2025,3,31)]*4,
    [date(2024,3,31),date(2024,6,30),date(2025,3,31),date(2025,6,30)]])
def test_quarter_continuity_rejects_duplicates_and_gaps(ends):
    assert not consecutive_quarters(ends)


def test_financial_period_cannot_mix_statement_scopes():
    end=date(2025,3,31)
    def f(scope,amount):return ('revenue','QUARTER',end,False,scope,None,Decimal(amount),None,None,'issuer')
    facts=[f('STANDALONE',1),f('CONSOLIDATED',9)]
    assert F._main_period(facts)[2]=='CONSOLIDATED'
    with pytest.raises(ValueError):F._period(facts,'QUARTER',end)
    assert F._period(facts,'QUARTER',end,'CONSOLIDATED').values['revenue']==9


def test_uncertain_returns_are_not_in_primary_performance_statistics():
    rows=[dict(issuer_id='a',status='VERIFIED',price_return=Decimal('.1')),
          dict(issuer_id='b',status='UNVERIFIED',price_return=Decimal('10')),
          dict(issuer_id='c',status='STOPPED_TRADING',price_return=Decimal('-.9'))]
    s=R.stats(rows,R.policy())
    assert s['measured']==2 and s['median_return_pct']=='-40.0'
    assert s['unverified']==1 and s['stopped_trading']==1
    assert s['sensitivity_including_unverified']['measured']==3


def test_stopped_stock_with_unknown_corporate_economics_is_still_unverified():
    series=[(date(2025,1,1),Decimal(100)),(date(2025,2,1),Decimal(10))]
    action=dict(kind='RIGHTS',ex_date=date(2025,1,15))
    out=R.outcome(series,[action],date(2025,1,1),365,date(2026,1,2),R.policy())
    assert out.status=='UNVERIFIED' and any('last close' in s for s in out.notes)


def test_legacy_snapshot_uses_first_observation_without_mutating_raw_dates(db):
    iss,_=_seed(db)
    db.execute('''INSERT INTO financial_facts(issuer_id,metric,period_end,scope,value,value_kind,currency,scale,
        period_type,available_at,provider,provider_version,content_hash)
        VALUES(%s,'revenue','2020-03-31','CONSOLIDATED',100,'MONEY','INR','UNITS','ANNUAL',
        '2020-05-30','bse_results_snapshot','bse-results-snapshot-1','snapshot')''',(iss,))
    raw,effective,recorded,basis=db.execute('''SELECT source_available_at,available_at,recorded_at,availability_basis
        FROM financial_facts_asof WHERE issuer_id=%s AND content_hash='snapshot' ''',(iss,)).fetchone()
    assert raw.year==2020 and effective==recorded and basis=='SNAPSHOT_OBSERVED'
    assert db.execute("SELECT count(*) FROM financial_facts_asof WHERE content_hash='snapshot' AND available_at<'2021-01-01'").fetchone()[0]==0


def test_bse_loader_keeps_annual_and_quarter_and_accepts_revisions(db,monkeypatch):
    from inflection import bse_results as B
    iss,src=_seed(db)
    base=dict(metric='revenue',period_start=date(2025,1,1),period_end=date(2025,3,31),scope='STANDALONE',
              value=Decimal(10),value_kind='MONEY',original_text='10',period_type='QUARTER')
    data=[base,dict(base,period_type='ANNUAL',period_start=date(2024,4,1),value=Decimal(40),original_text='40')]
    monkeypatch.setattr(B,'bse_only_scrips',lambda *a:[('123456',str(iss))])
    monkeypatch.setattr(B,'fetch',lambda *a:(B.WindowStatus.COMPLETE,data))
    assert B.load(db,None)['facts']==2
    assert B.load(db,None)['facts']==0
    data[0]=dict(base,value=Decimal(12),original_text='12')
    assert B.load(db,None)['facts']==1
    assert db.execute('SELECT count(DISTINCT period_type) FROM financial_facts WHERE provider=%s',(B.PROVIDER,)).fetchone()[0]==2


def test_mechanisms_survive_rule_rollover_until_their_source_is_reread(db,monkeypatch):
    from inflection.commercial import pipeline as P,vocabulary as V
    iss,src=_seed(db);at=datetime(2026,1,20,tzinfo=IST)
    _filing(db,iss,src,900,at,['The Company has received an order worth Rs 450 crore from NTPC Limited.'])
    P.scan(db);P.resolve(db)
    assert F._mechanisms(db,iss,at+timedelta(days=1))
    monkeypatch.setattr(V,'RULES_VERSION','commercial-next')
    assert F._mechanisms(db,iss,at+timedelta(days=1))
    # Source reread under the new rule retires the older interpretation even before resolution.
    P.scan(db)
    assert F._mechanisms(db,iss,at+timedelta(days=1))==[]


def test_effective_outcome_uses_latest_recomputation_not_the_highest(db):
    import json
    iss,_=_seed(db)
    rid=db.execute('''INSERT INTO triage_reviews(week_start,issuer_id,label,decided_by,triage_action,result,source)
       VALUES('2025-01-06',%s,'ABC','reviewer','DEEP_RESEARCH','{}','test') RETURNING review_id''',(iss,)).fetchone()[0]
    for stamp,ret in [('2026-01-01',2),('2026-02-01',-1)]:
        db.execute('''INSERT INTO triage_review_outcomes(review_id,horizon_days,entry_date,stock_return,excess_return,computed_at)
          VALUES(%s,365,'2025-01-20',%s,%s,%s)''',(rid,ret,ret,stamp))
    assert db.execute('SELECT return_12m FROM triage_review_results WHERE review_id=%s',(rid,)).fetchone()[0]==-1


def test_benchmark_reports_missing_exits_and_excludes_rights(db):
    from inflection.replay.pipeline import Prices
    from test_triage import _issuer
    from test_replay import _prices
    a,b,c=(_issuer(db,x) for x in ('AAA','BBB','CCC'))
    d1,d2=date(2025,1,1),date(2025,12,31)
    sec_a=_prices(db,a,[(d1,100),(d2,120)])
    _prices(db,b,[(d1,100)])
    sec_c=_prices(db,c,[(d1,100),(d2,200)])
    db.execute('''INSERT INTO corporate_actions(security_id,kind,ex_date,details,provider,provider_version)
       VALUES(%s,'RIGHTS','2025-06-01','{}','test','1')''',(sec_c,))
    px=Prices(db);median,n=px.benchmark('nse_bhavcopy',d1,d2)
    assert median==Decimal('.2000') and n==1
    assert px.benchmark_coverage[('nse_bhavcopy',d1,d2)]==dict(entry_securities=3,measured=1,missing_exit=1,uncertain_actions=1)


def test_process_health_checks_entire_window_and_replaces_failed_retries(db):
    from inflection.process_health import collect
    _,src=_seed(db)
    for status,stamp in [('FAILED','2026-01-02'),('COMPLETE','2026-01-03')]:
        db.execute('''INSERT INTO ingestion_runs(source_id,window_start,window_end,coverage_status,started_at,finished_at)
          VALUES(%s,'2026-01-01','2026-01-02',%s,%s,%s)''',(src,status,stamp,stamp))
    report=collect(db,date(2026,1,1),date(2026,1,3))
    checks={x['key']:x for x in report['checks']}
    assert checks['source_coverage']['affected']==0
    assert checks['source_missing']['affected']>0 and checks['source_missing']['blocking']
    assert all(x['status']!='ERROR' for x in report['checks']),report


def test_annual_cumulative_is_valid_annual_data_without_becoming_a_quarter(db):
    from inflection.commercial.pipeline import annual_revenue
    from inflection.snapshots import financials
    iss,_=_seed(db)
    db.execute('''INSERT INTO financial_facts(issuer_id,metric,period_start,period_end,scope,value,value_kind,currency,scale,
       period_type,cumulative,available_at,provider,provider_version,content_hash)
       VALUES(%s,'revenue','2025-04-01','2026-03-31','CONSOLIDATED',20000000000,'MONEY','INR','UNITS',
       'ANNUAL',true,'2026-05-01','test','1','annual-cumulative')''',(iss,))
    rev,basis=annual_revenue(db,iss,datetime(2026,6,1,tzinfo=IST))
    assert rev==20000000000 and basis['basis']=='ANNUAL'
    snap=financials(db,iss,date(2026,6,1))
    assert snap['annual']['revenue'][-1]['value']=='2,000.00'


def test_future_actions_and_future_price_versions_cannot_change_past_features(db):
    from inflection.market_history import adjusted_closes
    from test_triage import _issuer
    from test_replay import _prices
    iss=_issuer(db,'AAA');d1,d2=date(2025,1,1),date(2025,1,2)
    sec=_prices(db,iss,[(d1,100),(d2,110)])
    before,notes=adjusted_closes(db,sec,'nse_bhavcopy',d1,d2)
    db.execute('''INSERT INTO corporate_actions(security_id,kind,ex_date,details,provider,provider_version)
       VALUES(%s,'SPLIT','2025-06-01','{}','test','1')''',(sec,))
    assert adjusted_closes(db,sec,'nse_bhavcopy',d1,d2)==(before,notes)
    assert adjusted_closes(db,sec,'nse_bhavcopy',d1,date(2025,7,1))[0]==[]


def test_shared_metrics_require_the_same_four_pat_and_revenue_quarters(db):
    from inflection.snapshots import metrics
    iss,_=_seed(db)
    # Revenue has four periods but PAT has only one: no partial PAT numerator is allowed.
    db.execute('''INSERT INTO financial_facts(issuer_id,metric,period_end,scope,value,value_kind,currency,scale,
       period_type,available_at,provider,provider_version,content_hash)
       VALUES(%s,'pat','2025-12-31','CONSOLIDATED',10000000,'MONEY','INR','UNITS','QUARTER','2026-01-15','test','1','partial-pat')''',(iss,))
    m=metrics(db,iss,date(2026,2,1))
    assert m['revenue_cr']==1500 and m['pat_margin'] is None


def test_unverified_empty_listing_is_retried_instead_of_cached_as_complete(db):
    from inflection import financials
    from inflection.sources.xbrl import ListingResult
    from inflection.sources.common import WindowStatus
    iss,_=_seed(db)
    first,last=date(2025,1,1),date(2025,12,31)
    financials.record_listing(db,ListingResult('ABC','equities',WindowStatus.EMPTY_UNVERIFIED),str(iss),first,last)
    assert 'ABC' not in financials.listed_symbols(db,first,last)
    financials.record_listing(db,ListingResult('ABC','equities',WindowStatus.COMPLETE),str(iss),first,last)
    assert 'ABC' in financials.listed_symbols(db,first,last)


def test_native_results_are_not_misreported_as_missing_pdf_text(db):
    from inflection.process_health import collect
    from inflection import financials
    iss,_=_seed(db)
    src=financials.ensure_source(db)
    doc=db.execute('INSERT INTO documents(issuer_id) VALUES(%s) RETURNING document_id',(iss,)).fetchone()[0]
    ver=db.execute('''INSERT INTO document_versions(document_id,sha256,storage_key,byte_size,media_type)
       VALUES(%s,%s,'native.xml',1,'application/xml') RETURNING document_version_id''',(doc,'f'*64)).fetchone()[0]
    db.execute('''INSERT INTO document_publications(document_version_id,source_id,external_id,source_url,published_at,publication_basis,
       issuer_id,pipeline_state) VALUES(%s,%s,'native-result','https://example.test/result.xml','2026-01-05',
       'EXCHANGE_TIMESTAMP',%s,'TEXT_READY')''',(ver,src,iss))
    checks={x['key']:x for x in collect(db,date(2026,1,1),date(2026,1,7))['checks']}
    assert checks['text_handoff']['affected']==0


def test_actual_replay_source_coverage_requires_the_system_to_have_held_the_filing(db):
    from inflection.replay.pipeline import _coverage
    iss,src=_seed(db)
    _filing(db,iss,src,950,datetime(2022,1,5,tzinfo=IST),['A dated archived filing.'])
    first=last=date(2022,1,3)
    public=_coverage(db,first,last,'PUBLIC_INFORMATION_RECONSTRUCTION')
    actual=_coverage(db,first,last,'ACTUAL_SYSTEM_REPLAY')
    assert public['announcements'][first]==1
    assert actual['announcements'].get(first,0)==0


def test_reference_index_never_uses_a_future_level(db):
    import importlib.util
    from pathlib import Path
    path=Path(__file__).resolve().parents[1]/'dashboard/combo_flags.py'
    spec=importlib.util.spec_from_file_location('integrity_combo',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    db.execute("INSERT INTO index_closes(index_name,trade_date,close,source_url) VALUES('Nifty Smallcap 250','2026-02-01',100,'https://example.test/index')")
    assert module._sc(db,date(2026,1,1)) is None


def test_mainboard_coverage_does_not_hide_a_missing_sme_stream(db):
    from inflection.process_health import collect
    _,nse=_seed(db)
    bse=db.execute("INSERT INTO sources(name,kind,access_policy) VALUES('bse_announcements','announcements','test') RETURNING source_id").fetchone()[0]
    for source,segment in [(nse,'equities'),(bse,'equity')]:
        db.execute('''INSERT INTO ingestion_runs(source_id,segment,window_start,window_end,coverage_status,finished_at)
          VALUES(%s,%s,%s,%s,'COMPLETE',now())''',(source,segment,datetime(2026,1,1,tzinfo=IST),datetime(2026,1,3,tzinfo=IST)))
    checks={x['key']:x for x in collect(db,date(2026,1,1),date(2026,1,2))['checks']}
    assert checks['source_missing']['details']==[dict(name='nse_announcements',segment='sme',affected=2)]


def test_delisting_after_a_stopped_quote_invalidates_the_horizon_mark():
    series=[(date(2025,1,1),Decimal(100)),(date(2025,2,1),Decimal(10))]
    action=dict(kind='DELISTING',ex_date=date(2025,6,1))
    out=R.outcome(series,[action],date(2025,1,1),365,date(2026,1,2),R.policy())
    assert out.status=='UNVERIFIED' and any('after the last quote' in s for s in out.notes)


def test_invalid_adjustment_is_unknown_instead_of_a_division_error():
    series=[(date(2025,1,1),Decimal(100)),(date(2025,12,31),Decimal(10))]
    action=dict(kind='SPLIT',ex_date=date(2025,6,1),multiplier=0,reconciled=False)
    out=R.outcome(series,[action],date(2025,1,1),364,date(2026,1,2),R.policy())
    assert out.status=='UNVERIFIED' and out.price_return is None
