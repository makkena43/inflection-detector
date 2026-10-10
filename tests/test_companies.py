"""Listing files, the company master built from them, and filings linked by ISIN (fake exchange
transport; the database tests use real PostgreSQL)."""

from datetime import date

from inflection import companies, ingest
from inflection.sources import bse, listings
from inflection.sources.common import WindowStatus
from test_ingest import nse_row, nse_window
from test_prices import DAY
from test_sources import bse_row, client

SNAP = date(2026, 10, 10)
EQUITY_L = (b"SYMBOL,NAME OF COMPANY, SERIES, DATE OF LISTING, PAID UP VALUE, MARKET LOT, ISIN NUMBER, FACE VALUE\n"
            b"ABC,ABC Limited,EQ,05-JAN-2010,10,1,INE111A01011,10\n"
            b"NEWCO,Newco Industries Limited,EQ,15-MAR-2015,10,1,INE333C01033,10\n"
            b"ABCETF,ABC ETF,EQ,01-JAN-2020,10,1,INF999Z01019,10\n")
SME_L = (b"SYMBOL,NAME_OF_COMPANY,SERIES,DATE_OF_LISTING,PAID_UP_VALUE,MARKET_LOT,ISIN_NUMBER,FACE_VALUE\n"
         b"TINY,Tiny Works Limited,SM,02-FEB-2024,10,1200,INE777G01077,10\n")
SYMBOL_CHANGES = (b"ABC Limited,OLDEST,OLDABC,01-JUN-2012\n"
                  b"ABC Limited,OLDABC,ABC,01-MAR-2020\n")
BSE_EQUITY_CSV = (b"Security Code,Issuer Name,Security Id,Security Name,Status,Group,Face Value,ISIN No,Industry,"
                  b"Instrument\n"
                  b"543210,ABC Limited,ABC,ABC LTD,Active,A ,10.00,INE111A01011,Capital Goods,Equity\n"
                  b"500001,Gone Limited,GONE,GONE LTD,Delisted,Z ,10.00,INE555E01055,Textiles,Equity\n"
                  b"500002,Never Traded Limited,NEVER,NEVER LTD,Delisted,Z ,10.00,INE666F01066,,Equity\n")


def nse_lists():
    c, _ = client({"SME_EQUITY_L": [(200, SME_L)], "EQUITY_L": [(200, EQUITY_L)],
                   "symbolchange": [(200, SYMBOL_CHANGES)]})
    return listings.fetch_nse(c)


# ---------------- parsing and fetching ----------------

def test_nse_lists_and_symbol_changes():
    main, sme, changes = nse_lists()
    assert [r.status for r in (main, sme, changes)] == [WindowStatus.COMPLETE] * 3
    abc = main.rows[0]
    assert (abc.code, abc.isin, abc.name, abc.listing_date, abc.board) == (
        "ABC", "INE111A01011", "ABC Limited", date(2010, 1, 5), "MAINBOARD")
    (tiny,) = sme.rows
    assert (tiny.code, tiny.isin, tiny.board, tiny.series, tiny.listing_date) == (
        "TINY", "INE777G01077", "SME", "SM", date(2024, 2, 2))
    assert [(c.old_symbol, c.new_symbol, c.effective_date) for c in changes.rows] == [
        ("OLDEST", "OLDABC", date(2012, 6, 1)), ("OLDABC", "ABC", date(2020, 3, 1))]
    headed = listings.parse_symbol_changes(b"SM_NAME,SM_KEY_SYMBOL,SM_NEW_SYMBOL,SM_APPLICABLE_FROM\n"
                                           + SYMBOL_CHANGES)
    assert len(headed) == 2


def test_bse_list_json_and_file_forms():
    rows = listings.parse_bse([{"SCRIP_CD": "543210", "Scrip_Name": "ABC LTD", "Status": "Active", "GROUP": "A ",
                                "FACE_VALUE": "10.00", "ISIN_NUMBER": "INE111A01011", "INDUSTRY": "Capital Goods",
                                "scrip_id": "ABC", "Issuer_Name": "ABC Limited"}], "BSE_ACTIVE", "ACTIVE")
    (r,) = rows
    assert (r.code, r.ticker, r.isin, r.name, r.series, r.board) == (
        "543210", "ABC", "INE111A01011", "ABC Limited", "A", "MAINBOARD")
    filed = listings.parse_file(BSE_EQUITY_CSV, "BSE")
    assert [(f.code, f.status) for f in filed] == [("543210", "ACTIVE"), ("500001", "DELISTED"),
                                                   ("500002", "DELISTED")]


def test_bse_api_block_is_reported_per_status():
    c, t = client({"ListofScripData": [(403, b"")]})
    out = listings.fetch_bse(c)
    assert [(r.list_name, r.status) for r in out] == [("BSE_ACTIVE", WindowStatus.BLOCKED),
                                                     ("BSE_SUSPENDED", WindowStatus.BLOCKED),
                                                     ("BSE_DELISTED", WindowStatus.BLOCKED)]
    assert all("status=" in u for u in t.calls)


# ---------------- database ----------------

def _load(db):
    for r in nse_lists():
        companies.record_list(db, r, SNAP)
    filed = listings.ListResult("BSE", "BSE_FILE", WindowStatus.COMPLETE, listings.parse_file(BSE_EQUITY_CSV, "BSE"))
    companies.record_list(db, filed, SNAP, source_key="FILE")
    db.execute("""INSERT INTO bhavcopy_rows (exchange, trade_date, code, series, isin, source_formats) VALUES
        ('BSE', '2020-01-02', '500001', 'Z', NULL, '{BSE_LEGACY}'),
        ('BSE', '2020-06-30', '500001', 'Z', 'INE555E01055', '{BSE_LEGACY}'),
        ('NSE', '2019-01-01', 'NEWCO', 'EQ', 'INE888H01088', '{NSE_LEGACY}'),
        ('NSE', '2021-06-30', 'NEWCO', 'EQ', 'INE888H01088', '{NSE_LEGACY}'),
        ('NSE', '2026-10-09', 'ABC', 'EQ', 'INE111A01011', '{NSE_UDIFF}')""")


def test_company_master_dates_codes_and_keeps_delisted_names(db):
    _load(db)
    from inflection import prices
    prices.build_company_list(db)            # NEWCO belonged to another company until 2021-06-30
    out = companies.build_from_master(db)
    assert out["conflicts"] == []
    assert out["counts"]["codes_without_dates"] == 1                     # delisted, never in a bhavcopy
    spans = db.execute("""SELECT s.isin, h.exchange, h.kind, h.value, h.valid_from, h.valid_to, h.listing_status
                            FROM identifier_history h JOIN securities s USING (security_id)
                           WHERE h.source = 'listing_master' ORDER BY 1, 2, 3, 4""").fetchall()
    assert spans == [
        ("INE111A01011", "BSE", "SCRIP_CODE", "543210", SNAP, None, "LISTED"),
        ("INE111A01011", "BSE", "SYMBOL", "ABC", SNAP, None, "LISTED"),
        ("INE111A01011", "NSE", "SYMBOL", "ABC", date(2020, 3, 1), None, "LISTED"),
        ("INE111A01011", "NSE", "SYMBOL", "OLDABC", date(2012, 6, 1), date(2020, 2, 29), "LISTED"),
        ("INE111A01011", "NSE", "SYMBOL", "OLDEST", date(2010, 1, 5), date(2012, 5, 31), "LISTED"),
        ("INE333C01033", "NSE", "SYMBOL", "NEWCO", date(2021, 7, 1), None, "LISTED"),     # clamped
        ("INE555E01055", "BSE", "SCRIP_CODE", "500001", date(2020, 1, 2), date(2020, 6, 30), "DELISTED"),
        ("INE555E01055", "BSE", "SYMBOL", "GONE", date(2020, 1, 2), date(2020, 6, 30), "DELISTED"),
        ("INE777G01077", "NSE", "SYMBOL", "TINY", date(2024, 2, 2), None, "LISTED")]
    names = dict(db.execute("SELECT s.isin, i.legal_name FROM securities s JOIN issuers i USING (issuer_id)"))
    assert names["INE666F01066"] == "Never Traded Limited" and names["INE777G01077"] == "Tiny Works Limited"
    assert db.execute("SELECT exchange_segment FROM securities WHERE isin = 'INE777G01077'").fetchone() == ("SME",)
    again = companies.build_from_master(db)["counts"]
    assert set(again) == {"identifiers_unchanged", "codes_without_dates"}


def test_filings_link_by_isin_including_suspended_names(db):
    _load(db)
    companies.build_from_master(db)
    suspended = {**nse_row(1, "https://x/a.pdf"), "symbol": "DHARSUGAR", "sm_isin": "INE988C01014",
                 "sm_name": "Dharani Sugars & Chemicals Limited"}
    listed = {**nse_row(2, "https://x/b.pdf"), "symbol": "ABC", "sm_isin": "INE111A01011"}
    ingest.record_window(db, nse_window([suspended, listed]))
    c, _ = client({"AnnSubCategoryGetData": [(200, {"Table": [bse_row(1)], "Table1": [{"ROWCNT": 1}]})]})
    ingest.record_window(db, bse.BSEAnnouncements(c).list_window(DAY, DAY))       # scrip 543210
    out = companies.link_publications(db)
    assert out["counts"] == dict(issuers_created=1, securities_created=1, nse_by_isin=2, bse_by_isin=1, by_code=0)
    assert out["filings"] == [dict(source="bse_announcements", linked=1, unlinked=0),
                              dict(source="nse_announcements", linked=2, unlinked=0)]
    names = db.execute("""SELECT p.raw_metadata->>'_symbol', i.legal_name, i.identity_status
                            FROM document_publications p JOIN issuers i USING (issuer_id) ORDER BY 1""").fetchall()
    assert names == [("543210", "ABC Limited", "PROVISIONAL"), ("ABC", "ABC Limited", "PROVISIONAL"),
                     ("DHARSUGAR", "Dharani Sugars & Chemicals Limited", "PROVISIONAL")]
    rep = companies.master_report(db)
    assert {"list": "NSE_SME_EQUITY_L", "snapshot": "2026-10-10", "status": "ACTIVE", "rows": 1,
            "with_isin": 1} in rep["lists"]
