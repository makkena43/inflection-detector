"""Reporting periods and comparability (spec section 15 tests 6 and 7).

Quarter, half-year, nine-month and annual figures are never compared as
equal periods, standalone and consolidated never silently mix, and a
cumulative year-to-date figure is turned into a discrete period only by an
explicit subtraction of two YTD figures with the same scope and fiscal year.
SME half-year data stays half-year data: no quarter is invented from it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Optional

from .states import PeriodType, StatementScope
from .units import Money, Scale, same_currency


@dataclass(frozen=True)
class Period:
    start: date
    end: date
    type: PeriodType
    cumulative: bool = False        # reported as fiscal-year-to-date


@dataclass(frozen=True)
class Fact:
    metric: str
    period: Period
    scope: StatementScope
    amount: Money
    segment: str = ""


@dataclass(frozen=True)
class Comparability:
    ok: bool
    reason: str


def comparable(a: Fact, b: Fact) -> Comparability:
    if a.metric != b.metric:
        return Comparability(False, f"different metrics {a.metric} vs {b.metric}")
    if StatementScope.UNKNOWN in (a.scope, b.scope):
        return Comparability(False, "statement scope unknown")
    if a.scope != b.scope:
        return Comparability(False, f"scope mismatch {a.scope.value} vs {b.scope.value}")
    if a.segment != b.segment:
        return Comparability(False, "different segments")
    if a.period.type != b.period.type:
        return Comparability(False, f"period mismatch {a.period.type.value} vs {b.period.type.value}")
    if a.amount.currency != b.amount.currency:
        return Comparability(False, "currency mismatch; no conversion is performed")
    return Comparability(True, "ok")


_YTD_ORDER = {PeriodType.QUARTER: 1, PeriodType.HALF_YEAR: 2, PeriodType.NINE_MONTHS: 3, PeriodType.ANNUAL: 4}
_DISCRETE = {(2, 1): PeriodType.QUARTER, (3, 2): PeriodType.QUARTER, (4, 3): PeriodType.QUARTER,
             (4, 2): PeriodType.HALF_YEAR}


def discrete_from_ytd(later: Fact, earlier: Fact) -> Fact:
    """E.g. Q3 = 9M YTD - H1 YTD.  Both must share metric, scope, segment, currency and fiscal-year start."""
    if later.metric != earlier.metric or later.scope != earlier.scope or later.segment != earlier.segment:
        raise ValueError("YTD figures must share metric, scope and segment")
    if StatementScope.UNKNOWN in (later.scope, earlier.scope):
        raise ValueError("statement scope unknown")
    if later.period.start != earlier.period.start:
        raise ValueError("YTD figures must start on the same fiscal-year date")
    key = (_YTD_ORDER[later.period.type], _YTD_ORDER[earlier.period.type])
    if key not in _DISCRETE:
        raise ValueError(f"cannot derive a discrete period from {later.period.type.value} - "
                         f"{earlier.period.type.value}")
    same_currency(later.amount, earlier.amount)
    value = (later.amount.to_base() - earlier.amount.to_base()) / Scale.CRORE.factor
    period = Period(start=_next_day(earlier.period.end), end=later.period.end, type=_DISCRETE[key])
    return Fact(later.metric, period, later.scope, Money(value, later.amount.currency, Scale.CRORE,
                                                         "derived: YTD difference"), later.segment)


def _next_day(d: date) -> date:
    from datetime import timedelta
    return d + timedelta(days=1)


def ttm(quarters: list[Fact]) -> Optional[Money]:
    """Sum of four consecutive comparable quarters; None if any quarter is missing (never annualised)."""
    if len(quarters) != 4 or any(q.period.type != PeriodType.QUARTER or q.period.cumulative for q in quarters):
        return None
    qs = sorted(quarters, key=lambda q: q.period.end)
    for a, b in zip(qs, qs[1:]):
        if not comparable(a, b).ok or (b.period.start - a.period.end).days != 1:
            return None
    cur = same_currency(*(q.amount for q in qs))
    return Money(sum((q.amount.to_base() for q in qs), 0) / Scale.CRORE.factor, cur, Scale.CRORE, "derived: TTM")
