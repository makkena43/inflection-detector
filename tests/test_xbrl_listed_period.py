"""The exchange-listed period dates an undated current-period group, and nothing else."""

from datetime import date
from decimal import Decimal

from inflection.sources.xbrl import listed_period, parse_results_xbrl

from test_financials import filing, get


def test_listing_dates_the_current_period_only():
    p = parse_results_xbrl(filing(declare=False), listed_period({"fromDate": "01-OCT-2021", "toDate": "31-Dec-2021"}))
    q = get(p.figures, "revenue", "QUARTER")
    assert (q.period_start, q.period_end) == (date(2021, 10, 1), date(2021, 12, 31))
    assert all(f.period_type != "ANNUAL" for f in p.figures if f.segment is None)      # FourD stays undated
    assert any("taken from the exchange listing" in i for i in p.issues)
    assert any("FourD has no declared period" in i for i in p.issues)


def test_listing_that_disagrees_with_a_declared_end_is_ignored():
    p = parse_results_xbrl(filing(declare=False).replace(
        b"</xbrli:xbrl>", b'<in-bse-fin:DateOfEndOfReportingPeriod contextRef="OneD">2021-09-30'
                          b"</in-bse-fin:DateOfEndOfReportingPeriod></xbrli:xbrl>"),
        listed_period({"fromDate": "01-Oct-2021", "toDate": "31-Dec-2021"}))
    assert not [f for f in p.figures if f.segment is None]


def test_declared_periods_win_over_the_listing():
    p = parse_results_xbrl(filing(), listed_period({"fromDate": "01-Jul-2021", "toDate": "30-Sep-2021"}))
    assert get(p.figures, "revenue", "QUARTER").period_end == date(2021, 12, 31)
    assert get(p.figures, "revenue", "ANNUAL").value == Decimal("145267820000.00")


def test_listed_period_parsing():
    assert listed_period({"fromDate": "01-OCT-2023", "toDate": "31-MAR-2024"}) == (date(2023, 10, 1), date(2024, 3, 31))
    assert listed_period({"fromDate": "", "toDate": "31-Mar-2024"}) is None
    assert listed_period(None) is None
