"""BSE-only round 2: listing dates, dividends/rights/buybacks from BSE filings, incremental BSE results pull."""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from inflection import bse_corp_actions as C
from inflection import listing_dates as L

IST = timezone(timedelta(hours=5, minutes=30))


# ---------------- listing dates ----------------

def test_listing_notice_is_parsed():
    t = ("Trading Members of the Exchange are hereby informed that effective from August 07, 2026, the Equity Shares of "
         "Prima Innovation Ltd (Scrip Code: 544855) are listed and admitted to dealings on the Exchange")
    assert L.parse_notice(t) == ("544855", date(2026, 8, 7), "Prima Innovation Ltd", False)
    assert L.parse_notice(t + " migrated from the SME platform")[3] is True
    assert L.parse_notice("Board meeting on August 07, 2026") is None


def test_first_trade_is_a_listing_only_for_new_sequential_codes():
    start = date(2019, 6, 27)
    assert L.first_trade_date("543905", date(2023, 5, 11), start, 542685) == date(2023, 5, 11)
    assert L.first_trade_date("531637", date(2021, 2, 1), start, 542685) is None      # older code: resumed trading
    assert L.first_trade_date("590134", date(2021, 2, 1), start, 542685) is None      # special series
    assert L.first_trade_date("543905", start, start, 542685) is None                 # seen on the first day: censored


# ---------------- dividends, rights, buybacks ----------------

def f(n, when, text):
    return C.Filing(str(n), "iss", datetime(*when, 18, tzinfo=IST), text)


def test_record_date_is_the_date_written_next_to_it_not_the_meeting_date():
    rd = C.record_date
    assert rd("Record Date For Payment Of Interim Dividend, If Any Declared In Board Meeting Scheduled To Be Held On "
              "10Th August, 2022 Will Be Monday, 22nd August, 2022", date(2022, 8, 3)) == (date(2022, 8, 22), "record_date")
    assert rd("Company has fixed 7th June, 2023 for payment of dividend, if declared at the Board Meeting scheduled to "
              "be held on 30th May, 2023", date(2023, 5, 20)) == (date(2023, 6, 7), "record_date")
    assert rd("Book Closure From Saturday, 13Th August, 2022 To Saturday, 20Th August, 2022", date(2022, 7, 5)) == \
        (date(2022, 8, 13), "book_closure_start")


def test_amounts():
    assert C.amount("recommended dividend of Rs. 1.50 per equity share of Re. 1 each")[0] == Decimal("1.50")
    assert C.amount("The Board approves dividend @ 15% on face value of Rs. 10/- each")[0] == Decimal("1.5")
    assert C.amount("The dividend of Rs.075/- per share") is None


def test_decision_and_record_date_filings_make_one_dividend_with_both_times():
    acts, counts = C.actions([
        f(1, (2025, 5, 1), "Board to consider dividend, if any"),
        f(2, (2025, 5, 20), "Corporate Action-Board approves Dividend. Board recommended dividend of Rs. 2.50 per equity share"),
        f(3, (2025, 7, 1), "Record date for final dividend. The Company has fixed Friday, July 25, 2025 as the Record Date"),
    ])
    (a,) = acts
    assert (a.kind, a.record_date) == ("DIVIDEND", date(2025, 7, 25)) and counts["board_to_consider"] == 1
    ex, basis = C.ex_date(a.record_date, [])
    d = a.details(ex, basis)
    assert ex == date(2025, 7, 25) and d["amount_per_share"] == "2.50" and d["dividend_type"] == "FINAL"
    assert d["announced_at"].startswith("2025-05-20") and d["amount_announced_at"].startswith("2025-05-20")
    assert d["record_date_announced_at"].startswith("2025-07-01")


def test_before_t1_the_ex_date_is_the_trading_day_before_the_record_date():
    days = [date(2022, 8, 18), date(2022, 8, 19), date(2022, 8, 22)]
    assert C.ex_date(date(2022, 8, 22), days) == (date(2022, 8, 19), "T+2: trading day before the record date")


def test_kinds():
    assert C.kind_of("Buy-back of equity shares through tender offer, record date") == "BUYBACK"
    assert C.kind_of("Rights Issue of equity shares - record date") == "RIGHTS"
    assert C.kind_of("Scheme of Arrangement for demerger - record date") == "OTHER"
    assert C.kind_of("Transfer of unclaimed dividend to IEPF") is None
