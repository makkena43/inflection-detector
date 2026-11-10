"""BSE-only companies: older bhavcopy files, BSE delivery, SME groups, splits/bonuses from filings and prices,
and face values for the share count (fake exchange transport; database tests use real PostgreSQL)."""

from datetime import date, timedelta
from decimal import Decimal

import pytest

from inflection import bse_actions, bse_results, companies, prices
from inflection.bse_actions import Bar, Filing
from inflection.identity import BSE_SME_GROUPS
from inflection.sources import bhavcopy, listings
from inflection.sources.common import WindowStatus
from test_prices import BSE_LEGACY, udiff
from test_sources import client, zip_of

HTML = b"<!DOCTYPE html><html><body>File not found</body></html>"
OLD_DAY = date(2024, 1, 8)
DELIVERY = (b"DATE|SCRIP CODE|DELIVERY QTY|DELIVERY VAL|DAY'S VOLUME|DAY'S TURNOVER|DELV. PER.\n"
            b"08012024|543210|0000000420|0000000004410|0000000700|0000000007350|060.00\n"
            b"08012024|999999|0000000001|0000000000010|0000000001|0000000000010|100.00\n")


# ---------------- older BSE files and delivery ----------------

def test_bse_html_for_a_missing_udiff_file_falls_back_to_the_older_file():
    c, t = client({"BhavCopy_BSE_CM": [(200, HTML)],
                   "EQ_ISINCODE_080124": [(200, zip_of({"EQ_ISINCODE_080124.CSV": BSE_LEGACY}))],
                   "SCBSEALL0801": [(200, zip_of({"SCBSEALL0801.TXT": DELIVERY}))]})
    day = bhavcopy.fetch_bse(c, OLD_DAY)
    (row,) = day.rows
    assert day.status == WindowStatus.COMPLETE and day.notes == []
    assert (row.code, row.close, row.delivery_qty, row.delivery_pct) == ("543210", Decimal("10.5"), Decimal(420),
                                                                        Decimal("60.00"))
    assert row.source_formats == ("BSE_LEGACY", "BSE_DELIVERY")
    assert any("EQ_ISINCODE" in u for u in t.calls) and any("BSEDATA/gross/2024/SCBSEALL0801.zip" in u for u in t.calls)


def test_bse_day_of_html_pages_only_is_failed_not_a_holiday():
    c, _ = client({"BhavCopy_BSE_CM": [(200, HTML)], "EQ_ISINCODE": [(200, HTML)]})
    day = bhavcopy.fetch_bse(c, OLD_DAY)
    assert day.status == WindowStatus.FAILED and day.rows == []


def test_bse_holiday_before_udiff_is_empty_unverified():
    c, _ = client({"BhavCopy_BSE_CM": [(200, HTML)]})          # older file: 404
    assert bhavcopy.fetch_bse(c, OLD_DAY).status == WindowStatus.EMPTY_UNVERIFIED


def test_missing_bse_delivery_file_is_noted_not_a_downgrade():
    body = udiff([(543210, "INE222B01022", "XYZ", "B", "XYZ LTD", "10.50")], day="2024-01-08", src="BSE")
    c, _ = client({"BhavCopy_BSE_CM": [(200, body)]})
    day = bhavcopy.fetch_bse(c, OLD_DAY)
    assert day.status == WindowStatus.COMPLETE and day.rows[0].delivery_qty is None
    assert day.notes == ["BSE_DELIVERY: HTTP 404"]


def test_bse_delivery_file_parses_zero_padded_fields():
    rows = bhavcopy.parse_bse_delivery(DELIVERY, OLD_DAY)
    assert [(r.code, r.trade_date, r.delivery_qty, r.delivery_pct) for r in rows] == [
        ("543210", OLD_DAY, Decimal(420), Decimal("60.00")), ("999999", OLD_DAY, Decimal(1), Decimal("100.00"))]


# ---------------- SME groups ----------------

def test_bse_ms_group_is_sme():
    assert set(BSE_SME_GROUPS) == {"M", "MT", "MS"}
    assert prices._board("BSE", "MS") == "SME" and prices._board("BSE", "B") == "MAINBOARD"
    assert listings.BSE_SME_GROUPS is BSE_SME_GROUPS


# ---------------- splits and bonuses ----------------

def test_stated_ratios():
    r = bse_actions.stated_ratios
    assert [s.label for s in r("Board has approved and recommended Bonus at the ratio of 1:1")] == ["bonus 1:1"]
    assert r("Bonus at the ratio of 1:1")[0].multiplier == 0.5
    assert r("issue of 2 bonus equity shares for every 1 share held")[0].multiplier == pytest.approx(1 / 3)
    (s,) = r("subdivision of 92616256 equity shares of Rs. 4 each into 185232512 equity shares of Rs. 2 each")
    assert (s.kind, s.multiplier) == ("SPLIT", 0.5)
    (s,) = r("sub-division of face value from Rs. 10/- each to Re. 1/- each")
    assert s.multiplier == 0.1
    (s,) = r("consolidation of equity shares of Rs. 1 each into Rs. 10 each")
    assert s.multiplier == 10
    assert r("Board to consider bonus issue") == []


def test_record_dates():
    t = "Company has fixed Wednesday, 25th September, 2024 as the record date for the Sub-division"
    assert bse_actions.record_dates(t) == [date(2024, 9, 25)]


def _bars(start, closes, jump_day=None, opens=None):
    out, d = [], start
    for i, c in enumerate(closes):
        while d.weekday() >= 5:
            d += timedelta(days=1)
        out.append(Bar(d, (opens or {}).get(i, c), c))
        d += timedelta(days=1)
    return out


def test_unstated_split_matches_a_move_beyond_the_price_band():
    bars = _bars(date(2024, 9, 2), [1000, 1010, 1100, 1105, 224, 200, 205])     # 0.203 on the 5th day
    ep = [Filing("p1", date(2024, 7, 20), "Sub-division / Stock Split", "regarding Split of Equity Shares")]
    m, why = bse_actions.match_episode(ep, bars)
    assert why == "matched" and (m.kind, m.multiplier, m.ex_date, m.method) == (
        "SPLIT", Decimal("0.2"), bars[4].day, "plain_ratio_beyond_band")


def test_stated_bonus_needs_a_matching_move_and_ordinary_days_do_not_count():
    ep = [Filing("p1", date(2025, 2, 20), "Bonus", "Board recommends Bonus at the ratio of 1:10")]
    # a 0.91 bonus scaling on day 3; day 5 is an ordinary -11.8% day that also fits: the closer move wins
    bars = _bars(date(2025, 3, 3), [100, 101, 92, 93, 82, 83])
    m, _ = bse_actions.match_episode(ep, bars)
    assert m.ex_date == bars[2].day and m.multiplier == Decimal("0.90909091") and m.kind == "BONUS"
    flat = _bars(date(2025, 3, 3), [100, 101, 102, 88, 89])                       # only the -14% day
    assert bse_actions.match_episode(ep, flat) == (None, "stated_ratio_not_seen_in_prices")


def test_a_move_across_missing_exchange_days_is_not_overnight():
    bars = [Bar(date(2023, 12, 5), 100, 100), Bar(date(2024, 1, 1), 48, 49)]
    ep = [Filing("p1", date(2023, 11, 20), "Bonus", "Bonus issue in the ratio 1:1")]
    hole = frozenset({date(2023, 12, 6) + timedelta(days=i) for i in range(20)})
    assert bse_actions.match_episode(ep, bars, hole)[0] is None
    assert bse_actions.match_episode(ep, bars)[0] is not None


def test_episodes_group_filings_within_gap():
    f = [Filing(str(i), d, "", "bonus") for i, d in enumerate([date(2024, 1, 1), date(2024, 3, 1), date(2025, 1, 1)])]
    assert [len(e) for e in bse_actions.episodes(f)] == [2, 1]


# ---------------- face value ----------------

def test_face_value_is_carried_back_through_splits_only():
    acts = [(date(2025, 3, 21), "SPLIT", 0.1, "face value 10 -> 1"), (date(2025, 6, 1), "BONUS", 0.5, "bonus 1:1")]
    assert bse_results.face_value_at(1.0, date(2024, 12, 31), acts) == 10.0
    assert bse_results.face_value_at(1.0, date(2025, 3, 31), acts) == 1.0
    assert bse_results.face_value_at(2.0, date(2024, 12, 31), [(date(2025, 1, 1), "SPLIT", 0.5, "split 1:2 or bonus 1:1")]) is None


# ---------------- database ----------------

def _bse_only(db, code="543210", isin="INE222B01022", group="MS", fv=1):
    iss = db.execute("INSERT INTO issuers (legal_name) VALUES ('XYZ Ltd') RETURNING issuer_id").fetchone()[0]
    sec = db.execute("INSERT INTO securities (issuer_id, isin) VALUES (%s, %s) RETURNING security_id",
                     (iss, isin)).fetchone()[0]
    db.execute("""INSERT INTO identifier_history (security_id, exchange, kind, value, series, board, valid_from, source)
                  VALUES (%s, 'BSE', 'SCRIP_CODE', %s, %s, 'MAINBOARD', '2023-12-05', 'test')""", (sec, code, group))
    db.execute("""INSERT INTO listing_master (exchange, list_name, code, snapshot_date, isin, name, status, board,
                                              series, face_value, raw)
                  VALUES ('BSE', 'BSE_ACTIVE', %s, '2026-10-29', %s, 'XYZ', 'ACTIVE', 'MAINBOARD', %s, %s, '{}')""",
               (code, isin, group, fv))
    return iss, sec


def test_repair_boards_marks_ms_scrips_sme_and_fills_unknown_segments(db):
    iss, sec = _bse_only(db)
    assert companies.repair_boards(db)["rows"]["listing_master"] == 1
    assert db.execute("SELECT board FROM listing_master").fetchone()[0] == "MAINBOARD"      # dry run kept nothing
    out = companies.repair_boards(db, apply=True)["rows"]
    assert out["listing_master"] == 1 and out["identifier_history"] == 1 and out["securities_sme"] == 1
    assert db.execute("SELECT exchange_segment FROM securities").fetchone()[0] == "SME"


def test_record_bse_delivery_fills_stored_rows(db):
    db.execute("""INSERT INTO bhavcopy_rows (exchange, trade_date, code, series, close, source_formats)
                  VALUES ('BSE', %s, '543210', 'B', 10.5, '{BSE_LEGACY}')""", (OLD_DAY,))
    c, _ = client({"SCBSEALL0801": [(200, zip_of({"SCBSEALL0801.TXT": DELIVERY}))]})
    out = prices.record_bse_delivery(db, bhavcopy.fetch_bse_delivery(c, OLD_DAY))
    assert out == {"status": "COMPLETE", "delivery_rows": 2, "price_rows_updated": 1}
    assert db.execute("SELECT delivery_qty, delivery_pct, source_formats FROM bhavcopy_rows").fetchone() == (
        Decimal(420), Decimal("60.00"), ["BSE_DELIVERY", "BSE_LEGACY"])


def test_face_values_written_with_the_paid_up_capital_fact_time(db):
    iss, sec = _bse_only(db, group="B", fv=2)
    db.execute("""INSERT INTO financial_facts (issuer_id, metric, period_start, period_end, scope, value, value_kind,
                    currency, scale, period_type, available_at, provider, provider_version, content_hash)
                  VALUES (%s, 'paid_up_capital', '2026-04-01', '2026-06-30', 'STANDALONE', 50000000, 'MONEY', 'INR',
                          'UNITS', 'QUARTER', '2026-08-10 12:00+05:30', 'bse_results_snapshot', 'bse-results-snapshot-2', 'h1')""",
               (iss,))
    assert bse_results.face_values(db, issuers=[str(iss)])["counts"] == {"derived": 1}
    bse_results.face_values(db, apply=True, issuers=[str(iss)])
    row = db.execute("""SELECT value, value_kind, available_at = '2026-08-10 12:00+05:30'::timestamptz, provider
                          FROM financial_facts WHERE metric = 'face_value'""").fetchone()
    assert row == (Decimal("2"), "PER_SHARE", True, "bse_listing_face_value")
    assert bse_results.face_values(db, apply=True, issuers=[str(iss)])["counts"] == {}      # idempotent
