from datetime import date
from decimal import Decimal
from pathlib import Path
import pytest
from inflection import financials
from inflection.sources.download import Archive
from inflection.sources.xbrl import parse_results_xbrl
from test_financials import filing,get,_company,entry
from test_sources import client


def nonindas(final=65495000,before=76770000,minority=-11275000,scope='Consolidated'):
    facts=[('RevenueFromOperations',1055809000,1896317000),('ProfitBeforeTax',95100000,178404000),
     ('ProfitLossForThePeriodFromContinuingOperations',76770000,141993000),
     ('ProfitLossFromDiscontinuingOperationAfterTax',0,0),('ShareOfProfitLossOfAssociates',0,0),
     ('ProfitLossForPeriodBeforeMinorityInterest',before,141993000),
     ('ProfitLossOfMinorityInterest',minority,-20491000),('ProfitLossForThePeriod',final,121502000)]
    return filing(facts,nature=scope)


def test_nonindas_final_profit_and_signed_minority_inputs_are_retained():
    p=parse_results_xbrl(nonindas());f=get(p.figures,'pat','QUARTER')
    assert f.value==Decimal('65495000') and not f.unverified
    assert get(p.figures,'pat_continuing','QUARTER').value==Decimal('76770000')
    assert get(p.figures,'minority_adjustment','QUARTER').value==Decimal('-11275000')
    assert not p.issues


@pytest.mark.parametrize('change',[dict(final=90000000),dict(before=90000000)])
def test_nonindas_broken_reconciliation_is_unverified(change):
    p=parse_results_xbrl(nonindas(**change));f=get(p.figures,'pat','QUARTER')
    assert f.value is None and f.unverified and f.original_text


def test_standalone_nonindas_final_profit_without_minority_is_usable():
    body=nonindas(final=76770000,minority=0,scope='Standalone')
    assert get(parse_results_xbrl(body).figures,'pat','QUARTER').value==Decimal('76770000')


def seeded_old_parser(db,tmp_path,monkeypatch):
    _company(db);listing,_=client({'period=Quarterly':[(200,[entry(1)])],
      'corporates-financial-results':[(200,[])],'nseindia.com':[(200,b'')]})
    financials.list_results(db,listing,date(2021,1,1),date(2024,11,30))
    archive=Archive(tmp_path/'archive');active=financials.ADAPTER_VERSION
    monkeypatch.setattr(financials,'ADAPTER_VERSION','nse-results-xbrl-1')
    dl,_=client({'INDAS_1.xml':[(200,nonindas())]});financials.load_pending(db,archive,dl)
    monkeypatch.setattr(financials,'ADAPTER_VERSION',active)
    return archive


def test_successful_cached_filings_can_be_reprocessed_without_downloading(db,tmp_path,monkeypatch):
    archive=seeded_old_parser(db,tmp_path,monkeypatch)
    before=db.execute('SELECT publication_id,ingested_at,published_at,revision FROM document_publications').fetchone()
    old=db.execute('SELECT count(*) FROM financial_facts').fetchone()[0]
    result=financials.reparse_cached(db,archive)
    assert len(result['reparsed'])==1 and not result['pending'] and result['archive_bytes_added']==0
    assert db.execute('SELECT publication_id,ingested_at,published_at,revision FROM document_publications').fetchone()==before
    assert db.execute('SELECT count(*) FROM financial_facts').fetchone()[0]==old*2
    assert financials.reparse_cached(db,archive)['identified']==0
    assert db.execute('SELECT count(*) FROM financial_facts').fetchone()[0]==old*2


@pytest.mark.parametrize('fault',['missing','hash'])
def test_bad_or_missing_source_bytes_remain_pending_without_fact_changes(db,tmp_path,monkeypatch,fault):
    archive=seeded_old_parser(db,tmp_path,monkeypatch)
    key=db.execute('SELECT storage_key FROM document_versions').fetchone()[0]
    if fault=='missing':(archive.root/key).unlink()
    else:(archive.root/key).write_bytes(b'wrong source bytes')
    old=db.execute('SELECT count(*) FROM financial_facts').fetchone()[0]
    result=financials.reparse_cached(db,archive)
    assert result['pending'][0]['reason']==('SOURCE_ARCHIVE_MISSING' if fault=='missing' else 'SOURCE_HASH_MISMATCH')
    assert db.execute('SELECT count(*) FROM financial_facts').fetchone()[0]==old


def test_analysis_reprocesses_cached_parser_generation_before_financial_checks(db,tmp_path,monkeypatch):
    from types import SimpleNamespace
    from inflection import repair_jobs as jobs
    archive=seeded_old_parser(db,tmp_path,monkeypatch)
    monkeypatch.setattr(jobs,'OUT',tmp_path/'reports')
    guard_calls=[]
    job=SimpleNamespace(archive=archive,guard_storage=lambda:guard_calls.append(1),data={'counts':{}},update=lambda **k:None)
    report=jobs.refresh_cached_financials(job,db)
    assert len(report['reparsed'])==1 and guard_calls
    assert job.data['counts']['cached_financial_sources_reparsed']==1
    assert (tmp_path/'reports/financial_parser_repair.json').exists()
    assert jobs.refresh_cached_financials(job,db)['identified']==0
