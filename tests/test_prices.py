"""Bhavcopy prices, the MakroGraph history import, the company list and filing links (fake exchange
transport; the database tests use real PostgreSQL)."""

import os
from datetime import date
from decimal import Decimal

import pytest

from inflection import ingest, prices
from inflection.sources import bhavcopy, bse
from inflection.sources.common import WindowStatus
from inflection.sources.download import Archive
from test_ingest import nse_row, nse_window
from test_sources import bse_row, client, zip_of

DAY = date(2026, 10, 8)
UDIFF_HEAD = ("TradDt,BizDt,Sgmt,Src,FinInstrmTp,FinInstrmId,ISIN,TckrSymb,SctySrs,XpryDt,FininstrmActlXpryDt,"
              "StrkPric,OptnTp,FinInstrmNm,OpnPric,HghPric,LwPric,ClsPric,LastPric,PrvsClsgPric,UndrlygPric,"
              "SttlmPric,OpnIntrst,ChngInOpnIntrst,TtlTradgVol,TtlTrfVal,TtlNbOfTxsExctd,SsnId,NewBrdLotQty,"
              "Rmks,Rsvd1,Rsvd2,Rsvd3,Rsvd4\n")


def udiff(rows, day="2026-10-08", src="NSE"):
    """rows: (instrument id, isin, ticker, series, name, close)"""
    lines = [f"{day},{day},CM,{src},STK,{i},{isin},{sym},{ser},,,,,{name},100.00,110.00,95.00,{close},{close},"
             f"98.00,,{close},,,1000,105000.50,42,F1,1,,,,,\n" for i, isin, sym, ser, name, close in rows]
    return (UDIFF_HEAD + "".join(lines)).encode()


NSE_FULL = (b"SYMBOL, SERIES, DATE1, PREV_CLOSE, OPEN_PRICE, HIGH_PRICE, LOW_PRICE, LAST_PRICE, CLOSE_PRICE, "
            b"AVG_PRICE, TTL_TRD_QNTY, TURNOVER_LACS, NO_OF_TRADES, DELIV_QTY, DELIV_PER\n"
            b"ABC, EQ, 08-Oct-2026, 98.00, 100.00, 110.00, 95.00, 104.00, 105.00, 103.50, 1000, 1.05, 42, 600, 60.00\n"
            b"NEWCO, SM, 08-Oct-2026, 50.00, 50.00, 51.00, 49.00, 50.50, 50.50, 50.10, 2000, 1.00, 5, -, -\n")
NSE_LEGACY = (b"SYMBOL,SERIES,OPEN,HIGH,LOW,CLOSE,LAST,PREVCLOSE,TOTTRDQTY,TOTTRDVAL,TIMESTAMP,TOTALTRADES,ISIN,\n"
              b"ABC,EQ,100,110,95,105,104,98,1000,105000,08-JAN-2024,42,INE111A01011,\n")
BSE_LEGACY = (b"SC_CODE,SC_NAME,SC_GROUP,SC_TYPE,OPEN,HIGH,LOW,CLOSE,LAST,PREVCLOSE,NO_TRADES,NO_OF_SHRS,"
              b"NET_TURNOV,TDCLOINDI,ISIN_CODE,TRADING_DATE,FILLER2,FILLER3\n"
              b"543210,XYZ LTD    ,B ,Q,10.0,11.0,9.5,10.5,10.5,10.0,7,700,7350.0,,INE222B01022,08-Jan-24,,\n")


def nse_files(udiff_rows):
    return {"BhavCopy_NSE_CM": [(200, zip_of({"BhavCopy_NSE_CM_0_0_0_20261008_F_0000.csv": udiff(udiff_rows)}))],
            "sec_bhavdata_full": [(200, NSE_FULL)]}


# ---------------- parsing and fetching ----------------

def test_nse_day_merges_udiff_with_delivery_file():
    c, t = client(nse_files([(2885, "INE111A01011", "ABC", "EQ", "ABC LIMITED", "105.00")]))
    day = bhavcopy.fetch_nse(c, DAY)
    assert day.status == WindowStatus.COMPLETE and day.requests == 2 and len(day.files) == 2
    abc, newco = sorted(day.rows, key=lambda r: r.code)
    assert (abc.isin, abc.instrument_name, abc.close, abc.turnover) == ("INE111A01011", "ABC LIMITED",
                                                                       Decimal("105.00"), Decimal("105000.50"))
    assert (abc.delivery_qty, abc.delivery_pct, abc.avg_price) == (Decimal(600), Decimal("60.00"), Decimal("103.50"))
    assert abc.source_formats == ("NSE_UDIFF", "NSE_FULL")
    # only in the delivery file: lakhs become rupees, "-" stays missing
    assert (newco.series, newco.isin, newco.turnover, newco.delivery_qty) == ("SM", None, Decimal(100000), None)
    assert all("BhavCopy_NSE_CM_0_0_0_20261008" in u or "sec_bhavdata_full_08102026" in u for u in t.calls)


def test_nse_falls_back_to_legacy_file_before_udiff():
    d = date(2024, 1, 8)
    c, t = client({"cm08JAN2024bhav": [(200, zip_of({"cm08JAN2024bhav.csv": NSE_LEGACY}))],
                   "sec_bhavdata_full": [(404, b"")]})
    day = bhavcopy.fetch_nse(c, d)
    assert day.status == WindowStatus.PARTIAL and day.notes == ["NSE_FULL: HTTP 404"]
    (row,) = day.rows
    assert (row.code, row.isin, row.trade_date, row.turnover) == ("ABC", "INE111A01011", d, Decimal(105000))
    assert "BhavCopy_NSE_CM_0_0_0_20240108" in t.calls[0]


@pytest.mark.parametrize("reply,status", [((404, b""), WindowStatus.EMPTY_UNVERIFIED),
                                          ((403, b""), WindowStatus.BLOCKED),
                                          ((200, b"<html>Access Denied</html>"), WindowStatus.FAILED)])
def test_day_without_rows_is_never_silent(reply, status):
    c, _ = client({"nseindia.com": [reply]})
    day = bhavcopy.fetch_nse(c, DAY)
    assert day.status == status and day.rows == [] and day.notes


def test_bse_rows_are_keyed_on_scrip_code_and_keep_missing_values_missing():
    body = udiff([(543210, "INE222B01022", "XYZ", "B", "XYZ LTD", "10.50")], src="BSE")
    c, _ = client({"BhavCopy_BSE_CM_0_0_0_20261008": [(200, body)]})
    day = bhavcopy.fetch_bse(c, DAY)
    (row,) = day.rows
    assert day.status == WindowStatus.COMPLETE
    assert (row.code, row.ticker, row.series, row.isin) == ("543210", "XYZ", "B", "INE222B01022")
    assert (row.avg_price, row.delivery_qty, row.delivery_pct) == (None, None, None)


def test_bse_legacy_file_has_isin():
    c, _ = client({"EQ_ISINCODE_080124": [(200, zip_of({"EQ_ISINCODE_080124.CSV": BSE_LEGACY}))]})
    (row,) = bhavcopy.fetch_bse(c, date(2024, 1, 8)).rows
    assert (row.code, row.isin, row.instrument_name, row.series) == ("543210", "INE222B01022", "XYZ LTD", "B")


def test_weekends_are_skipped():
    assert bhavcopy.weekdays(date(2026, 10, 9), date(2026, 10, 12)) == [date(2026, 10, 9), date(2026, 10, 12)]


# ---------------- database ----------------

def test_record_day_is_idempotent_and_archives_raw_files(db, tmp_path):
    c, _ = client(nse_files([(2885, "INE111A01011", "ABC", "EQ", "ABC LIMITED", "105.00")]))
    day = bhavcopy.fetch_nse(c, DAY)
    archive = Archive(tmp_path / "a")
    prices.record_day(db, day, archive)
    r = prices.record_day(db, day, archive)
    assert (r.coverage_status.value, r.rows) == ("COMPLETE", 2)
    assert db.execute("SELECT count(*) FROM bhavcopy_rows").fetchone()[0] == 2
    assert db.execute("SELECT count(*) FROM ingestion_runs").fetchone()[0] == 2
    files = db.execute("SELECT reconciliation_result->'files' FROM ingestion_runs LIMIT 1").fetchone()[0]
    assert len(files) == 2 and all((archive.root / f["sha256"][:2] / f["sha256"]).exists() for f in files)
    blocked, _ = client({"nseindia.com": [(403, b"")]})
    prices.record_day(db, bhavcopy.fetch_nse(blocked, date(2026, 10, 9)), archive)
    rep = prices.price_report(db, DAY, date(2026, 10, 9))
    assert dict(source="nse_bhavcopy", status="BLOCKED", runs=1, rows=0) in rep["runs"]


def _makrograph_tables(src):
    src.execute("""CREATE TABLE nse_bhavcopy_data (trade_date date, symbol varchar(30), series varchar(5),
        prev_close numeric, open numeric, high numeric, low numeric, last numeric, close numeric, avg_price numeric,
        tottrdqty numeric, tottrdval numeric, totaltrades integer, delivery_qty numeric, delivery_pct numeric,
        PRIMARY KEY (trade_date, symbol))""")
    src.execute("CREATE TABLE bse_bhavcopy_data (LIKE nse_bhavcopy_data INCLUDING ALL, bse_instrument_id varchar(50))")
    src.execute("""INSERT INTO nse_bhavcopy_data VALUES
        ('2026-10-08', 'ABC', 'EQ', 1, 1, 1, 1, 1, 99, 1, 10, 2.5, 3, 5, 50),
        ('2026-10-07', 'ABC', 'nan', 1, 1, 1, 1, 1, 98, 1, 10, 2.5, 3, 5, 50)""")
    src.execute("""INSERT INTO bse_bhavcopy_data VALUES
        ('2024-01-08', '543210', 'B', 10, 10, 11, 9, 0, 10.5, 0, 700, 7350, 7, 0, 0, NULL),
        ('2026-10-08', 'XYZ', 'B', 10, 10, 11, 9, 0, 10.5, 0, 700, 7350, 7, 0, 0, '543210.0'),
        ('2026-10-08', 'UNKNOWN', 'EQ', 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, NULL)""")


def test_import_makrograph_history(db):
    import psycopg
    c, _ = client(nse_files([(2885, "INE111A01011", "ABC", "EQ", "ABC LIMITED", "105.00")]))
    prices.record_day(db, bhavcopy.fetch_nse(c, DAY), None)                      # fetched first: wins
    _makrograph_tables(db)
    dsn = psycopg.conninfo.make_conninfo(os.environ["INFLECTION_TEST_DSN"], dbname=db.info.dbname)
    with psycopg.connect(dsn) as src:
        out = prices.import_makrograph(db, src)
    assert out["NSE"] == dict(status="COPIED", table="nse_bhavcopy_data", read=2, stored=2, skipped_no_code=0,
                                   **{"from": "2026-10-07", "to": "2026-10-08"})
    assert (out["BSE"]["read"], out["BSE"]["stored"], out["BSE"]["skipped_no_code"]) == (3, 2, 1)
    abc = db.execute("""SELECT close, isin, delivery_pct, source_formats FROM bhavcopy_rows
                         WHERE exchange = 'NSE' AND code = 'ABC' AND trade_date = '2026-10-08'""").fetchone()
    assert abc == (Decimal("105.00"), "INE111A01011", Decimal("60.00"), ["MAKROGRAPH_NSE", "NSE_FULL", "NSE_UDIFF"])
    older = db.execute("""SELECT series, close, turnover FROM bhavcopy_rows
                           WHERE exchange = 'NSE' AND trade_date = '2026-10-07'""").fetchone()
    assert older == ("", Decimal(98), Decimal(250000))                        # lakhs -> rupees, 'nan' -> ''
    bse_rows = db.execute("""SELECT trade_date, code, ticker, last, avg_price, delivery_qty FROM bhavcopy_rows
                              WHERE exchange = 'BSE' ORDER BY trade_date""").fetchall()
    assert bse_rows == [(date(2024, 1, 8), "543210", None, None, None, None),
                        (DAY, "543210", "XYZ", None, None, None)]


def _bse_day(rows):
    c, _ = client({"BhavCopy_BSE_CM": [(200, udiff(rows, src="BSE"))]})
    return c


def test_company_list_from_isin_rows(db):
    def nse_day(d, rows):
        c, _ = client({"BhavCopy_NSE_CM": [(200, zip_of({"f.csv": udiff(rows, day=d.isoformat())}))],
                       "sec_bhavdata_full": [(404, b"")]})
        prices.record_day(db, bhavcopy.fetch_nse(c, d))

    d1, d2, d3 = date(2026, 10, 6), date(2026, 10, 7), DAY
    nse_day(d1, [(1, "INE111A01011", "OLDABC", "EQ", "ABC LIMITED", "1"), (9, "INF999Z01019", "SOMEETF", "EQ", "ETF", "1")])
    nse_day(d2, [(1, "INE111A01011", "OLDABC", "EQ", "ABC LIMITED", "1")])
    nse_day(d3, [(1, "INE111A01011", "ABC", "EQ", "ABC LIMITED", "1"), (2, "INE333C01033", "NEWCO", "SM", "NEWCO LTD", "1")])
    c, _ = client({"BhavCopy_BSE_CM": [(200, udiff([(543210, "INE111A01011", "ABC", "A", "ABC LTD", "1")],
                                                   src="BSE"))]})
    prices.record_day(db, bhavcopy.fetch_bse(c, d3))

    out = prices.build_company_list(db)
    assert out["counts"] == dict(issuers_created=2, securities_created=2, identifiers_created=5) and not out["conflicts"]
    spans = db.execute("""SELECT s.isin, h.exchange, h.kind, h.value, h.valid_from, h.valid_to, h.board
                            FROM identifier_history h JOIN securities s USING (security_id)
                           ORDER BY 1, 2, 3, 4""").fetchall()
    assert spans == [("INE111A01011", "BSE", "SCRIP_CODE", "543210", d3, None, "MAINBOARD"),
                     ("INE111A01011", "BSE", "SYMBOL", "ABC", d3, None, "MAINBOARD"),
                     ("INE111A01011", "NSE", "SYMBOL", "ABC", d3, None, "MAINBOARD"),
                     ("INE111A01011", "NSE", "SYMBOL", "OLDABC", d1, d2, "MAINBOARD"),       # renamed
                     ("INE333C01033", "NSE", "SYMBOL", "NEWCO", d3, None, "SME")]
    assert db.execute("SELECT legal_name, identity_status FROM issuers i JOIN securities s USING (issuer_id) "
                      "WHERE isin = 'INE333C01033'").fetchone() == ("NEWCO LTD", "PROVISIONAL")
    assert prices.build_company_list(db)["counts"] == dict(identifiers_unchanged=5)

    # A symbol that moves to another company while the old span is still open is a conflict, not a guess.
    d4 = date(2026, 10, 9)
    nse_day(d4, [(5, "INE444D01044", "ABC", "EQ", "OTHER LTD", "1")])
    out = prices.build_company_list(db)
    assert out["conflicts"] == [] and out["counts"]["identifiers_created"] == 1
    assert db.execute("SELECT valid_to FROM identifier_history WHERE value = 'ABC' AND exchange = 'NSE' "
                      "AND valid_from = %s", (d3,)).fetchone() == (d3,)


def test_overlapping_codes_are_reported_as_conflicts(db):
    db.execute("""INSERT INTO bhavcopy_rows (exchange, trade_date, code, series, isin, source_formats) VALUES
        ('NSE', '2026-10-07', 'ABC', 'EQ', 'INE111A01011', '{NSE_UDIFF}'),
        ('NSE', '2026-10-08', 'ABC', 'BE', 'INE444D01044', '{NSE_UDIFF}'),
        ('NSE', '2026-10-09', 'ABC', 'EQ', 'INE111A01011', '{NSE_UDIFF}')""")
    out = prices.build_company_list(db)
    assert out["counts"]["conflicts"] == 1
    assert out["conflicts"][0]["isin"] == "INE444D01044"


def test_filings_link_to_issuers_by_dated_symbol(db):
    ingest.record_window(db, nse_window([nse_row(1, "https://x/a.pdf")]))         # symbol ABC on DAY
    c, _ = client({"AnnSubCategoryGetData": [(200, {"Table": [bse_row(1)], "Table1": [{"ROWCNT": 1}]})]})
    ingest.record_window(db, bse.BSEAnnouncements(c).list_window(DAY, DAY))       # scrip 543210
    ingest.record_window(db, nse_window([{**nse_row(2, "-"), "symbol": "NOPE"}]))
    db.execute("""INSERT INTO bhavcopy_rows (exchange, trade_date, code, series, ticker, isin, instrument_name,
                                             source_formats) VALUES
        ('NSE', '2026-10-01', 'ABC', 'EQ', NULL, 'INE111A01011', 'ABC LIMITED', '{NSE_UDIFF}'),
        ('BSE', '2026-10-01', '543210', 'B', 'XYZ', 'INE222B01022', 'XYZ LTD', '{BSE_UDIFF}')""")
    prices.build_company_list(db)
    report = prices.link_publications(db)
    assert report == [dict(source="bse_announcements", linked=1, unlinked=0),
                      dict(source="nse_announcements", linked=1, unlinked=1)]
    names = db.execute("""SELECT s.name, i.legal_name FROM document_publications p JOIN sources s USING (source_id)
                           JOIN issuers i USING (issuer_id) ORDER BY 1""").fetchall()
    assert names == [("bse_announcements", "XYZ LTD"), ("nse_announcements", "ABC LIMITED")]
    assert prices.unlinked_symbols(db) == [dict(source="nse_announcements", symbol="NOPE", name="ABC Ltd", filings=1)]


def test_bse_history_without_isin_joins_the_scrip_codes_company(db):
    db.execute("""INSERT INTO bhavcopy_rows (exchange, trade_date, code, series, ticker, isin, close, source_formats)
        VALUES ('BSE', '2024-01-08', '543210', 'B', NULL, NULL, 10, '{MAKROGRAPH_BSE}'),
               ('BSE', '2026-10-08', '543210', 'B', 'XYZ', 'INE222B01022', 11, '{BSE_UDIFF}'),
               ('BSE', '2023-01-02', '500100', 'A', NULL, 'INE555E01055', 20, '{BSE_LEGACY}'),
               ('BSE', '2023-06-01', '500100', 'A', NULL, NULL, 21, '{MAKROGRAPH_BSE}'),
               ('BSE', '2026-10-08', '500100', 'A', 'NEW', 'INE666F01066', 22, '{BSE_UDIFF}')""")
    out = prices.build_company_list(db)
    assert out["counts"]["bse_spans_extended"] == 2 and not out["conflicts"]
    spans = db.execute("""SELECT s.isin, h.kind, h.value, h.valid_from, h.valid_to FROM identifier_history h
                            JOIN securities s USING (security_id) ORDER BY 1, 2""").fetchall()
    assert spans == [("INE222B01022", "SCRIP_CODE", "543210", date(2024, 1, 8), None),
                     ("INE222B01022", "SYMBOL", "XYZ", date(2024, 1, 8), None),
                     ("INE555E01055", "SCRIP_CODE", "500100", date(2023, 1, 2), date(2023, 1, 2)),
                     ("INE666F01066", "SCRIP_CODE", "500100", date(2023, 6, 1), None),   # after the old ISIN's last day
                     ("INE666F01066", "SYMBOL", "NEW", date(2023, 6, 1), None)]
    assert "bse_spans_extended" not in prices.build_company_list(db)["counts"]
    assert [r["rows_written"] for r in prices.fill_prices(db, exchanges=("BSE",))] == [2, 1, 0, 2]


def test_bse_filings_before_a_codes_first_known_day_join_its_company(db):
    c, _ = client({"AnnSubCategoryGetData": [(200, {"Table": [bse_row(1)], "Table1": [{"ROWCNT": 1}]})]})
    ingest.record_window(db, bse.BSEAnnouncements(c).list_window(DAY, DAY))       # scrip 543210, filed on DAY
    db.execute("""INSERT INTO bhavcopy_rows (exchange, trade_date, code, series, ticker, isin, instrument_name,
                                             source_formats) VALUES
        ('BSE', '2026-10-20', '543210', 'B', 'XYZ', 'INE222B01022', 'XYZ LTD', '{BSE_UDIFF}')""")
    prices.build_company_list(db)                         # the code is first known after the filing
    assert prices.link_publications(db) == [dict(source="bse_announcements", linked=1, unlinked=0)]
    assert db.execute("SELECT i.legal_name FROM document_publications JOIN issuers i USING (issuer_id)"
                      ).fetchone() == ("XYZ LTD",)
