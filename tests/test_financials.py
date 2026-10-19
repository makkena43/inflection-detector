"""Results XBRL: parsing (ported MakroGraph cases), NSE listing, and loading into financial_facts.
The Rain Industries defects are real: its Q4 CY21 consolidated filing leaves "OneD"/"FourD" undefined,
gives its year-to-date segment context the quarter's dates, and reports owners' profit as +969.59 mn
where the statement prints (969.59)."""

from datetime import date, datetime
from decimal import Decimal

from inflection import financials, prices
from inflection.sources.common import IST, WindowStatus
from inflection.sources.download import Archive
from inflection.sources.xbrl import NSEResultsListing, parse_entry, parse_results_xbrl
from test_sources import client

NS = ('xmlns:xbrli="http://www.xbrl.org/2003/instance" xmlns:xbrldi="http://xbrl.org/2006/xbrldi" '
      'xmlns:iso4217="http://www.xbrl.org/2003/iso4217" '
      'xmlns:in-bse-fin="http://www.bseindia.com/xbrl/fin/2020-03-31/in-bse-fin"')

# (tag, OneD value, FourD value) in rupees; Rain Q4 CY21, consolidated.  Employee cost and the year's other
# expenses are illustrative (MakroGraph's fixture), set so the year's expense lines add up.
FACTS = [("RevenueFromOperations", 40260540000, 145267820000), ("OtherIncome", 546240000, 1931160000),
         ("Income", 40806780000, 147198980000), ("CostOfMaterialsConsumed", 20753630000, 66175520000),
         ("PurchasesOfStockInTrade", 4011060000, 12988190000),
         ("ChangesInInventoriesOfFinishedGoodsWorkInProgressAndStockInTrade", -3152720000, -5080550000),
         ("EmployeeBenefitExpense", 3400000000, 13000000000), ("FinanceCosts", 1192210000, 4789140000),
         ("DepreciationDepletionAndAmortisationExpense", 1998600000, 7981530000),
         ("OtherExpenses", 10363590000, 34575500000), ("Expenses", 38566770000, 134429330000),
         ("ProfitBeforeExceptionalItemsAndTax", 2240010000, 12769650000), ("ExceptionalItemsBeforeTax", 0, 0),
         ("ProfitBeforeTax", 2240010000, 12769650000), ("TaxExpense", 2957620000, 5828790000),
         ("ProfitLossForPeriodFromContinuingOperations", -717610000, 6940860000),
         ("ProfitLossFromDiscontinuedOperationsAfterTax", 0, 0),
         ("ShareOfProfitLossOfAssociatesAndJointVenturesAccountedForUsingEquityMethod", -5450000, -5450000),
         ("ProfitLossForPeriod", -723060000, 6935410000),
         ("ProfitOrLossAttributableToOwnersOfParent", 969590000, 5801580000),      # the filer's sign error (Q)
         ("ProfitOrLossAttributableToNonControllingInterests", 246530000, 1133830000)]


def filing(facts=FACTS, nature="Consolidated", unit="iso4217:INR", declare=True) -> bytes:
    ctx = ('<xbrli:context id="FourReportableSegmentRevenue01D"><xbrli:entity><xbrli:identifier scheme="s">RAIN'
           '</xbrli:identifier></xbrli:entity><xbrli:period><xbrli:startDate>2021-10-01</xbrli:startDate>'
           '<xbrli:endDate>2021-12-31</xbrli:endDate></xbrli:period><xbrli:scenario><xbrldi:explicitMember '
           'dimension="in-bse-fin:ReportableSegmentsAxis">in-bse-fin:Seg01</xbrldi:explicitMember></xbrli:scenario>'
           '</xbrli:context>')
    body = [f'<xbrli:unit id="INR"><xbrli:measure>{unit}</xbrli:measure></xbrli:unit>', ctx,
            f'<in-bse-fin:NatureOfReportStandaloneConsolidated contextRef="OneD">{nature}'
            '</in-bse-fin:NatureOfReportStandaloneConsolidated>',
            '<in-bse-fin:Symbol contextRef="OneD">RAIN</in-bse-fin:Symbol>',
            '<in-bse-fin:DescriptionOfReportableSegment contextRef="FourReportableSegmentRevenue01D">Carbon'
            '</in-bse-fin:DescriptionOfReportableSegment>',
            '<in-bse-fin:SegmentRevenue contextRef="FourReportableSegmentRevenue01D" unitRef="INR">104989600000'
            '</in-bse-fin:SegmentRevenue>']
    if declare:
        body += ['<in-bse-fin:DateOfStartOfReportingPeriod contextRef="OneD">2021-10-01</in-bse-fin:DateOfStartOfReportingPeriod>',
                 '<in-bse-fin:DateOfEndOfReportingPeriod contextRef="OneD">2021-12-31</in-bse-fin:DateOfEndOfReportingPeriod>',
                 '<in-bse-fin:DateOfStartOfReportingPeriod contextRef="FourD">2021-01-01</in-bse-fin:DateOfStartOfReportingPeriod>',
                 '<in-bse-fin:DateOfEndOfReportingPeriod contextRef="FourD">2021-12-31</in-bse-fin:DateOfEndOfReportingPeriod>']
    for tag, q, fy in facts:
        body.append(f'<in-bse-fin:{tag} contextRef="OneD" unitRef="INR" decimals="-6">{q}.00</in-bse-fin:{tag}>')
        body.append(f'<in-bse-fin:{tag} contextRef="FourD" unitRef="INR" decimals="-6">{fy}.00</in-bse-fin:{tag}>')
    return f'<?xml version="1.0" encoding="UTF-8"?><xbrli:xbrl {NS}>{"".join(body)}</xbrli:xbrl>'.encode()


def get(figs, metric, ptype, segment=None):
    return next(f for f in figs if f.metric == metric and f.period_type == ptype and f.segment == segment)


# ---------------- parsing (ported) ----------------

def test_periods_come_from_the_declared_dates_and_values_stay_exact_rupees():   # ported
    p = parse_results_xbrl(filing())
    q = get(p.figures, "revenue", "QUARTER")
    assert (q.value, q.value_kind, q.period_start, q.period_end, q.cumulative) == (
        Decimal("40260540000.00"), "MONEY", date(2021, 10, 1), date(2021, 12, 31), False)
    fy = get(p.figures, "revenue", "ANNUAL")
    assert fy.value == Decimal("145267820000.00") and fy.cumulative
    seg = get(p.figures, "segment_revenue", "ANNUAL", "Carbon")   # the segment context carries the quarter's dates
    assert seg.value == Decimal(104989600000) and seg.scope == "CONSOLIDATED" and p.symbol == "RAIN"
    assert get(p.figures, "employee_cost", "QUARTER").value == Decimal("3400000000.00")   # kept, not check-only


def test_a_figure_that_breaks_the_statement_arithmetic_is_unverified_not_repaired():   # ported
    p = parse_results_xbrl(filing())
    owners = get(p.figures, "pat_owners", "QUARTER")
    assert owners.unverified and owners.value is None and owners.original_text == "969590000.00"
    assert any("owners' share + non-controlling share" in i for i in p.issues)
    assert get(p.figures, "pat", "QUARTER").value == Decimal("-723060000.00")      # continuing + associates
    assert not get(p.figures, "pat_owners", "ANNUAL").unverified
    for m in ("revenue", "depreciation", "finance_cost", "pbt", "tax"):
        assert not get(p.figures, m, "QUARTER").unverified


def test_no_declared_period_no_figures_and_foreign_units_refused():   # ported
    p = parse_results_xbrl(filing(declare=False))
    assert not [f for f in p.figures if f.segment is None] and any("no declared period" in i for i in p.issues)
    p = parse_results_xbrl(filing(unit="iso4217:USD"))
    assert not [f for f in p.figures if f.value_kind == "MONEY"] and any("not INR" in i for i in p.issues)
    assert parse_results_xbrl(b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "b">]><x/>').figures == []


def test_integrated_filing_taxonomy_is_read_the_same_way():   # ported
    text = filing().replace(b'xmlns:in-bse-fin="http://www.bseindia.com/xbrl/fin/2020-03-31/in-bse-fin"',
                            b'xmlns:in-capmkt="http://www.sebi.gov.in/xbrl/2026-01-31/in-capmkt"').replace(
        b"in-bse-fin:", b"in-capmkt:")
    assert get(parse_results_xbrl(text).figures, "revenue", "QUARTER").value == Decimal("40260540000.00")


# ---------------- listing ----------------

def entry(n, to="31-Dec-2021", dis="25-Feb-2022 20:56:04", cons="Consolidated"):
    return {"xbrl": f"https://nsearchives.nseindia.com/corporate/xbrl/INDAS_{n}.xml", "exchdisstime": dis,
            "fromDate": "01-Oct-2021", "toDate": to, "consolidated": cons}


def test_entry_dates_come_from_the_exchange_dissemination_time():   # ported
    e = parse_entry(entry(1), "RAIN", "Quarterly")
    assert e.disseminated_at == datetime(2022, 2, 25, 20, 56, 4, tzinfo=IST) and e.external_id == "INDAS_1"
    assert parse_entry({**entry(1), "xbrl": "-"}, "RAIN", "Quarterly") is None


def test_listing_statuses():
    c, t = client({"period=Quarterly": [(200, [entry(1), {**entry(2), "xbrl": "-"}])],
                   "period=Half-Yearly": [(200, [])], "period=Annual": [(200, [entry(1), entry(3)])],
                   "integrated-filing-results": [(200, {"data": [], "totalCount": 0})], "nseindia.com": [(200, b"")]})
    r = NSEResultsListing(c).list_symbol("RAIN")
    assert r.status == WindowStatus.COMPLETE and [e.external_id for e in r.entries] == ["INDAS_1", "INDAS_3"]
    assert r.notes == ["1 listed filings have no XBRL file"]
    assert any("symbol=RAIN" in u and "index=equities" in u for u in t.calls)
    c, _ = client({"period=Annual": [(403, b"")], "corporates-financial-results": [(200, [entry(1)])],
                   "integrated-filing-results": [(200, {"data": []})], "nseindia.com": [(200, b"")]})
    assert NSEResultsListing(c).list_symbol("RAIN").status == WindowStatus.PARTIAL
    c, _ = client({"corporates-financial-results": [(200, b"<html>challenge</html>")],
                   "integrated-filing-results": [(200, b"<html>challenge</html>")], "nseindia.com": [(200, b"")]})
    assert NSEResultsListing(c).list_symbol("RAIN").status == WindowStatus.BLOCKED


def integrated(n, qe="30-JUN-2025", kind="Integrated Filing- Financials", cons="Consolidated"):
    return {"xbrl": f"https://nsearchives.nseindia.com/corporate/xbrl/INTEGRATED_FILING_INDAS_{n}_WEB.xml",
            "qe_Date": qe, "broadcast_Date": "11-Aug-2025 17:28:06", "consolidated": cons, "type": kind}


def test_integrated_filings_extend_the_listing_past_2024():
    rows = [integrated(1), integrated(2, kind="Integrated Filing- Governance"), integrated(3, qe="31-MAR-2025")]
    c, t = client({"corporates-financial-results": [(200, [entry(1)])],
                   "integrated-filing-results": [(200, {"data": rows, "totalCount": 3})], "nseindia.com": [(200, b"")]})
    r = NSEResultsListing(c).list_symbol("RAIN")
    assert r.status == WindowStatus.COMPLETE
    got = {e.external_id: e for e in r.entries}
    assert set(got) == {"INDAS_1", "INTEGRATED_FILING_INDAS_1_WEB", "INTEGRATED_FILING_INDAS_3_WEB"}
    e = got["INTEGRATED_FILING_INDAS_1_WEB"]
    assert (e.from_date, e.to_date, e.listing_period) == (date(2025, 4, 1), date(2025, 6, 30), "Integrated")
    assert e.disseminated_at == datetime(2025, 8, 11, 17, 28, 6, tzinfo=IST)
    assert got["INTEGRATED_FILING_INDAS_3_WEB"].from_date == date(2025, 1, 1)
    assert any("integrated-filing-results" in u and "size=200" in u for u in t.calls)
    c, _ = client({"corporates-financial-results": [(200, [entry(1)])],
                   "integrated-filing-results": [(200, {"data": rows[:1], "totalCount": 40})], "nseindia.com": [(200, b"")]})
    r = NSEResultsListing(c).list_symbol("RAIN")
    assert r.status == WindowStatus.PARTIAL and any("1 of 40" in n for n in r.notes)


def test_window_is_period_end_from_and_public_by():
    w = (date(2021, 1, 1), date(2024, 11, 30))
    assert financials.in_window(parse_entry(entry(1), "X", "Quarterly"), *w)
    assert not financials.in_window(parse_entry(entry(1, to="31-Dec-2020"), "X", "Quarterly"), *w)
    assert not financials.in_window(parse_entry(entry(1, to="30-Sep-2024", dis="02-Dec-2024 10:00:00"),
                                                "X", "Quarterly"), *w)


# ---------------- database ----------------

def _company(db):
    db.execute("""INSERT INTO bhavcopy_rows (exchange, trade_date, code, series, isin, instrument_name, source_formats)
                  VALUES ('NSE', '2026-10-08', 'RAIN', 'EQ', 'INE855B01025', 'RAIN INDUSTRIES', '{NSE_UDIFF}')""")
    prices.build_company_list(db)
    return db.execute("SELECT issuer_id FROM issuers").fetchone()[0]


def test_list_and_load_into_financial_facts(db, tmp_path):
    issuer = _company(db)
    listing = {"period=Quarterly": [(200, [entry(1), entry(2, to="31-Dec-2020"), entry(3)])],
               "period=Half-Yearly": [(200, [])], "period=Annual": [(200, [])], "integrated-filing-results": [(200, {"data": []})], "nseindia.com": [(200, b"")]}
    c, _ = client(listing)
    w = (date(2021, 1, 1), date(2024, 11, 30))
    counts = financials.list_results(db, c, *w)
    assert counts == {"symbols_COMPLETE": 1, "filings_in_window": 2, "filings_new": 2}
    c, t = client(listing)
    assert financials.list_results(db, c, *w) == {"skipped_already_listed": 1} and not t.calls   # resumes

    dl, _ = client({"INDAS_1.xml": [(200, filing())], "INDAS_3.xml": [(403, b"")]})
    out = financials.load_pending(db, Archive(tmp_path / "a"), dl)
    assert out["LOADED"] == 1 and out["BLOCKED"] == 1 and out["unverified_figures"] == 2
    row = db.execute("""SELECT f.issuer_id, f.value, f.currency, f.scale, f.period_type, f.cumulative, f.scope,
                               f.available_at, p.pipeline_state
                          FROM financial_facts f JOIN document_publications p USING (publication_id)
                         WHERE f.metric = 'revenue' AND f.period_type = 'QUARTER'""").fetchone()
    assert row == (issuer, Decimal("40260540000.00"), "INR", "UNITS", "QUARTER", False, "CONSOLIDATED",
                   datetime(2022, 2, 25, 20, 56, 4, tzinfo=IST), "TEXT_READY")
    owners = db.execute("SELECT value, missing_reason, original_text FROM financial_facts "
                        "WHERE metric = 'pat_owners' AND period_type = 'QUARTER'").fetchone()
    assert owners == (None, "UNVERIFIED", "969590000.00")
    eps_shape = db.execute("SELECT DISTINCT value_kind FROM financial_facts").fetchall()
    assert eps_shape == [("MONEY",)]

    assert financials.load_pending(db, Archive(tmp_path / "a"), dl) == {}          # blocked waits for a retry
    dl2, _ = client({"INDAS_3.xml": [(200, filing(nature="Standalone"))]})
    assert financials.load_pending(db, Archive(tmp_path / "a"), dl2, retry_failed=True)["LOADED"] == 1
    rep = financials.results_report(db)
    assert rep["symbol_listings"] == {"COMPLETE": 1}
    assert rep["filings"] == [dict(state="TEXT_READY", reason="", count=2)]
    assert rep["facts"]["issuers"] == 1 and rep["facts"]["last_period_end"] == "2021-12-31"


def test_unreadable_xbrl_is_failed_with_reason_and_not_retried(db, tmp_path):
    _company(db)
    c, _ = client({"period=Quarterly": [(200, [entry(1)])], "corporates-financial-results": [(200, [])],
                   "nseindia.com": [(200, b"")]})
    financials.list_results(db, c, date(2021, 1, 1), date(2024, 11, 30))
    dl, _ = client({"INDAS_1.xml": [(200, b"<html>not xbrl</html>")]})
    assert financials.load_pending(db, Archive(tmp_path / "a"), dl) == {"NO_FIGURES": 1}
    reason = db.execute("SELECT failure_reason FROM document_publications").fetchone()[0]
    assert reason.startswith("XBRL: no in-bse-fin")
    dl2, t = client({"INDAS_1.xml": [(200, filing())]})
    assert financials.load_pending(db, Archive(tmp_path / "a"), dl2, retry_failed=True) == {} and not t.calls


def test_parallel_downloads_overlap_and_keep_a_bounded_ordered_queue():
    from threading import Barrier, Lock
    from inflection.sources.http import HttpClient, Response
    barrier = Barrier(4)
    lock = Lock()
    calls = []
    class DownloadClient:
        def get(self, url, **kwargs):
            with lock:
                calls.append(url)
            if int(url) < 4:
                barrier.wait(timeout=5)
            return Response(url, 200, url.encode())
    rows = [(i, None, str(i)) for i in range(12)]
    downloads = financials._download_rows(rows, HttpClient(), 4, DownloadClient)
    row, response = next(downloads)
    assert row[0] == 0 and response.body == b"0"
    assert sorted(calls) == ["0", "1", "2", "3"]
    rest = list(downloads)
    assert [row[0] for row, response in rest] == list(range(1, 12))
    assert len(calls) == len(set(calls)) == 12


def test_parallel_load_stores_each_filing_once(db, tmp_path):
    _company(db)
    c, _ = client({"period=Quarterly": [(200, [entry(1), entry(3)])],
                   "period=Half-Yearly": [(200, [])], "period=Annual": [(200, [])],
                   "nseindia.com": [(200, b"")]})
    financials.list_results(db, c, date(2021, 1, 1), date(2024, 11, 30))
    def download_client():
        return client({"INDAS_1.xml": [(200, filing())],
                       "INDAS_3.xml": [(200, filing())]})[0]
    out = financials.load_pending(db, Archive(tmp_path / "parallel"), download_client(),
                                 workers=2, client_factory=download_client)
    assert out["LOADED"] == 2
    assert db.execute("SELECT count(DISTINCT publication_id) FROM financial_facts").fetchone()[0] == 2
    count = db.execute("SELECT count(*) FROM financial_facts").fetchone()[0]
    assert financials.load_pending(db, Archive(tmp_path / "parallel"), download_client(),
                                  workers=2, client_factory=download_client) == {}
    assert db.execute("SELECT count(*) FROM financial_facts").fetchone()[0] == count
