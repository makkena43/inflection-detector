"""Spec section 15 tests 6 and 7: periods, scopes, scales, currencies, YTD and negative bases."""

from datetime import date
from decimal import Decimal

import pytest

from inflection.periods import Fact, Period, comparable, discrete_from_ytd, ttm
from inflection.states import PeriodType as PT, StatementScope as SC
from inflection.units import Money, Scale, UnitError, add, growth, parse_amount


def inr(v, scale=Scale.CRORE):
    return Money(Decimal(str(v)), "INR", scale)


# ---------------- test 7: units ----------------

@pytest.mark.parametrize("text,value,currency,scale", [     # ported cases + currency kept separate
    ("order of Rs 4,500 lakh", "4500", "INR", Scale.LAKH),
    ("₹1.2 billion contract", "1.2", "INR", Scale.BILLION),
    ("INR 250 million", "250", "INR", Scale.MILLION),
    ("Rs. 75 crore", "75", "INR", Scale.CRORE),
    ("worth 12 crores", "12", "INR", Scale.CRORE),
    ("USD 3.5 mn export order", "3.5", "USD", Scale.MILLION),
])
def test_parse_amount_keeps_currency_and_scale(text, value, currency, scale):
    m = parse_amount(text)
    assert (m.value, m.currency, m.scale) == (Decimal(value), currency, scale)


def test_bare_million_is_not_money():
    assert parse_amount("supplied 1 million doses") is None


def test_scale_conversion():
    assert inr(4500, Scale.LAKH).to(Scale.CRORE).value == 45
    assert inr(250, Scale.MILLION).to(Scale.CRORE).value == 25
    assert add(inr(1), inr(50, Scale.LAKH)).value == Decimal("1.5")


def test_no_currency_conversion():
    with pytest.raises(UnitError):
        add(inr(1), Money(Decimal(1), "USD", Scale.MILLION))


def test_negative_and_zero_base_growth():
    assert growth(inr(10), inr(-5)).pct is None and "negative base" in growth(inr(10), inr(-5)).reason
    assert growth(inr(10), inr(0)).pct is None
    assert growth(inr(10), inr("0.01"), min_base=inr(1)).pct is None
    assert growth(inr(15), inr(10)).pct == 50


# ---------------- test 6: periods and scopes ----------------

FY = date(2025, 4, 1)


def f(v, typ, end, scope=SC.CONSOLIDATED, start=FY, cumulative=False):
    return Fact("revenue", Period(start, end, typ, cumulative), scope, inr(v))


def test_quarter_vs_half_year_not_comparable():
    r = comparable(f(100, PT.QUARTER, date(2025, 6, 30)), f(180, PT.HALF_YEAR, date(2025, 9, 30)))
    assert not r.ok and "period mismatch" in r.reason


def test_standalone_vs_consolidated_not_comparable():
    r = comparable(f(100, PT.QUARTER, date(2025, 6, 30)),
                   f(90, PT.QUARTER, date(2024, 6, 30), SC.STANDALONE, date(2024, 4, 1)))
    assert not r.ok and "scope mismatch" in r.reason
    assert not comparable(f(1, PT.QUARTER, date(2025, 6, 30), SC.UNKNOWN),
                          f(1, PT.QUARTER, date(2024, 6, 30), SC.UNKNOWN)).ok


def test_q3_from_ytd_is_explicit():
    nine = f(330, PT.NINE_MONTHS, date(2025, 12, 31), cumulative=True)
    half = f(200, PT.HALF_YEAR, date(2025, 9, 30), cumulative=True)
    q3 = discrete_from_ytd(nine, half)
    assert q3.period.type == PT.QUARTER and q3.period.start == date(2025, 10, 1) and q3.amount.value == 130


def test_ytd_scope_mismatch_refused():
    with pytest.raises(ValueError):
        discrete_from_ytd(f(330, PT.NINE_MONTHS, date(2025, 12, 31)),
                          f(200, PT.HALF_YEAR, date(2025, 9, 30), SC.STANDALONE))


def test_sme_half_years_never_become_quarters():
    with pytest.raises(ValueError):
        discrete_from_ytd(f(200, PT.HALF_YEAR, date(2025, 9, 30)), f(200, PT.HALF_YEAR, date(2025, 9, 30)))


def test_ttm_needs_four_contiguous_quarters():
    qs = [f(10, PT.QUARTER, e, start=s) for s, e in [
        (date(2025, 1, 1), date(2025, 3, 31)), (date(2025, 4, 1), date(2025, 6, 30)),
        (date(2025, 7, 1), date(2025, 9, 30)), (date(2025, 10, 1), date(2025, 12, 31))]]
    assert ttm(qs).value == 40
    assert ttm(qs[:3]) is None                                  # never annualised
    assert ttm(qs[:2] + [qs[3], qs[3]]) is None                 # gap
