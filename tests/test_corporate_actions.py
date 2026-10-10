"""The prices table, NSE splits and bonuses, their reconciliation, and adjusted prices."""

from datetime import date
from decimal import Decimal

import pytest

from inflection import corporate_actions, prices
from inflection.sources.common import WindowStatus
from inflection.sources.corpactions import NSECorporateActions, parse_subject
from test_sources import client

EX = date(2024, 1, 8)


@pytest.mark.parametrize("subject,expected", [
    ("Bonus 1:1", [("BONUS", Decimal("0.5"), "1:1")]),
    ("Bonus 1:2", [("BONUS", Decimal(2) / Decimal(3), "1:2")]),
    ("Face Value Split (Sub-Division) - From Rs 10/- Per Share To Rs 2/- Per Share",
     [("SPLIT", Decimal("0.2"), "10->2")]),
    ("Face Value Split (Sub-Division) - From Rs 10/- Per Share To Re 1/- Per Share",
     [("SPLIT", Decimal("0.1"), "10->1")]),
    ("Consolidation Of Shares From Re 1/- Per Share To Rs 10/- Per Share", [("SPLIT", Decimal(10), "1->10")]),
    ("Interim Dividend - Rs 5 Per Share", [("DIVIDEND", None, None)]),
    ("Face Value Split", [("SPLIT", None, None)]),
    ("Annual General Meeting", [("OTHER", None, None)]),
])
def test_subjects(subject, expected):
    assert parse_subject(subject) == expected


def test_blocked_listing_is_reported():
    c, _ = client({"corporates-corporateActions": [(403, b"")], "nseindia.com": [(200, b"")]})
    assert NSECorporateActions(c).list_window(EX, EX).status == WindowStatus.BLOCKED


def _bhav(db):
    db.execute("""INSERT INTO bhavcopy_rows (exchange, trade_date, code, series, isin, prev_close, open, close, volume,
                                             source_formats) VALUES
        ('NSE', '2024-01-05', 'ABC', 'EQ', 'INE111A01011', 990, 995, 1000, 10, '{NSE_LEGACY}'),
        ('NSE', '2024-01-05', 'ABC', 'BL', 'INE111A01011', NULL, 950, 950, 99, '{NSE_LEGACY}'),
        ('NSE', '2024-01-08', 'ABC', 'EQ', 'INE111A01011', 500, 505, 510, 20, '{NSE_LEGACY}'),
        ('NSE', '2024-01-09', 'ABC', '',   NULL,           510, 512, 520, 30, '{MAKROGRAPH_NSE}'),
        ('NSE', '2024-01-10', 'ABC', 'EQ', 'INE111A01011', 520, 521, 525, 40, '{NSE_LEGACY}'),
        ('NSE', '2024-01-05', 'XYZ', 'EQ', 'INE222B01022', 100, 100, 100, 5, '{NSE_LEGACY}'),
        ('NSE', '2024-01-08', 'XYZ', 'EQ', 'INE222B01022', 50, 51, 52, 5, '{NSE_LEGACY}'),
        ('NSE', '2024-01-09', 'XYZ', 'EQ', 'INE222B01022', 52, 52, 53, 5, '{NSE_LEGACY}'),
        ('BSE', '2024-01-08', '543210', 'A', 'INE111A01011', 500, 505, 511, 7, '{BSE_LEGACY}')""")
    prices.build_company_list(db)


def test_fill_prices_ties_rows_to_securities(db):
    _bhav(db)
    out = prices.fill_prices(db)
    assert [r["rows_written"] for r in out] == [7, 1]
    abc = db.execute("""SELECT trade_date, close, volume FROM prices p JOIN securities s USING (security_id)
                         WHERE isin = 'INE111A01011' AND provider = 'nse_bhavcopy' ORDER BY 1""").fetchall()
    assert abc == [(date(2024, 1, 5), Decimal(1000), Decimal(10)),         # EQ, not the block-deal row
                   (EX, Decimal(510), Decimal(20)),
                   (date(2024, 1, 9), Decimal(520), Decimal(30)),          # no ISIN: tied by the dated symbol
                   (date(2024, 1, 10), Decimal(525), Decimal(40))]
    assert [r["rows_written"] for r in prices.fill_prices(db)] == [0, 0]   # unchanged rows are not rewritten
    assert {r["provider"]: r["securities"] for r in prices.prices_report(db)} == {"bse_bhavcopy": 1,
                                                                                  "nse_bhavcopy": 2}


def test_bonus_is_reconciled_and_adjusts_earlier_prices(db):
    _bhav(db)
    prices.fill_prices(db)
    items = [{"symbol": "ABC", "series": "EQ", "subject": "Bonus 1:1", "exDate": "08-Jan-2024",
              "isin": "INE111A01011", "comp": "ABC Limited"},
             {"symbol": "XYZ", "series": "EQ", "subject": "Face Value Split", "exDate": "08-Jan-2024", "isin": ""},
             {"symbol": "NOPE", "series": "EQ", "subject": "Bonus 1:1", "exDate": "08-Jan-2024", "isin": ""}]
    c, _ = client({"corporates-corporateActions": [(200, items)], "nseindia.com": [(200, b"")]})
    (rec,) = corporate_actions.fetch(db, c, EX, EX, indexes=("equities",))
    assert rec["counts"] == dict(BONUS=1, SPLIT=1, unresolved=1, ratio_unreadable=1)
    assert corporate_actions.reconcile(db) == {"reconciled:exchange_reference_price": 1}
    detail = db.execute("SELECT reconciled, details->'reconciliation' FROM corporate_actions WHERE kind = 'BONUS'")
    ok, result = detail.fetchone()
    assert ok and result["implied"] == "0.500000" and result["previous_day"] == "2024-01-05"

    adjusted = db.execute("""SELECT trade_date, close, volume, multiplier, unverified
                               FROM prices_split_bonus_adjusted a JOIN securities s USING (security_id)
                              WHERE isin = 'INE111A01011' AND provider = 'nse_bhavcopy' ORDER BY 1""").fetchall()
    assert adjusted == [(date(2024, 1, 5), Decimal(500), Decimal(20), Decimal(0.5), False),
                        (EX, Decimal(510), Decimal(20), Decimal(1), False),
                        (date(2024, 1, 9), Decimal(520), Decimal(30), Decimal(1), False),
                        (date(2024, 1, 10), Decimal(525), Decimal(40), Decimal(1), False)]
    # XYZ halved its reference price with no readable split stored: listed as a missing action.
    missing = corporate_actions.unexplained_adjustments(db, date(2024, 1, 1), date(2024, 1, 31))
    assert [(m["symbol"], m["day"], m["ratio"]) for m in missing] == [("XYZ", "2024-01-08", "0.5000")]
    rep = corporate_actions.report(db)
    assert dict(kind="SPLIT", rows=1, reconciled=0, ratio_unreadable=1) in rep["actions"]


def test_overnight_move_is_the_fallback_check():
    assert corporate_actions.check(Decimal("0.5"), Decimal(1000), None, Decimal(480))[:2] == (True, "overnight_move")
    assert corporate_actions.check(Decimal("0.5"), Decimal(1000), None, Decimal(950))[0] is False
    assert corporate_actions.check(Decimal("0.5"), None, None, None) == (False, "no_prices", None)
