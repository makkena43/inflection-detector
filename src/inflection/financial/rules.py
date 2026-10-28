"""Spec 18.1 financial nominations and spec 18.2 priority, as pure functions.

A results filing is compared with the same period one year earlier (same scope, same period
length, figures public by the filing's own time).  Each check reports FIRED, NOT_FIRED,
UNVERIFIED (an input failed the statement's arithmetic) or NOT_MEASURABLE (an input is missing or
the base is too small to divide by).  Values are exact rupees; ratios are computed, never stored
as money.

Working-capital days need a balance sheet, which results XBRL does not carry, so that check is
reported as not covered rather than silently skipped.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Optional

RULES_VERSION = "financial-4"

CR = Decimal(10) ** 7

POLICY = dict(
    margin_bps=200,                     # gross or operating margin up at least 200 bps year on year
    operating_profit_growth=Decimal("0.25"),
    segment_loss_reduction=Decimal("0.30"),
    finance_cost_drop=Decimal("0.20"),
    min_revenue=CR,                     # ₹1 crore in both periods, or margins mean little
    operating_base_share=Decimal("0.02"),   # a positive base of at least 2% of revenue
    segment_loss_share=Decimal("0.01"),     # a segment loss of at least 1% of revenue
    finance_cost_share=Decimal("0.005"),    # finance cost of at least 0.5% of revenue
    revenue_jump=Decimal("0.50"),       # revenue up more than this: check acquisitions or reclassification
    comparable_tolerance_days=7,
    mechanism_lookback_days=450,        # commercial events public within this many days before the results
    equity_funding_lookback_days=365,
    live_window_days=7,
)

COGS = ("cost_of_materials", "purchases_stock_in_trade", "inventory_change")

# Commercial event types that can explain an operating improvement, and the one that can explain
# lower interest.  Equity financing is context: debt repaid from shareholder money is not operating.
OPERATING_MECHANISMS = frozenset({"ORDER", "COMMERCIAL_START", "CUSTOMER_QUALIFICATION", "LOSS_DRAG_REMOVAL",
                                  "CAPACITY", "PRICING", "PRODUCT_LAUNCH"})
DEBT_MECHANISMS = frozenset({"DEBT_REDUCTION"})
QUALIFIED_RANK = 3                       # commercial STAGE_RANK of QUALIFIED

CLASS_ORDER = {"U0": 0, "P1": 1, "P2": 2, "P3": 3, "D": 4}


def policy_hash() -> str:
    parts = [RULES_VERSION, repr(sorted(POLICY.items())), repr(COGS), repr(sorted(OPERATING_MECHANISMS)),
             repr(sorted(DEBT_MECHANISMS))]
    return hashlib.sha256("\n".join(parts).encode()).hexdigest()


# ---------------------------------------------------------------- figures

@dataclass
class Period:
    """Company-level figures of one period from one filing.  ``values[m]`` is None when the figure
    was filed but failed the statement arithmetic (UNVERIFIED); a metric not filed is absent."""
    period_end: object
    values: dict[str, Optional[Decimal]] = field(default_factory=dict)
    segments: dict[str, Optional[Decimal]] = field(default_factory=dict)      # segment result by name

    def get(self, m: str) -> tuple[Optional[Decimal], str]:
        """(value, state) with state OK, UNVERIFIED or MISSING."""
        if m not in self.values:
            return None, "MISSING"
        v = self.values[m]
        return (v, "OK") if v is not None else (None, "UNVERIFIED")


def segment_key(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", name.lower()).strip()


@dataclass
class Derived:
    value: Optional[Decimal]
    state: str                  # OK | UNVERIFIED | MISSING
    inputs: tuple[str, ...] = ()


def _combine(p: Period, needed: tuple[str, ...], optional: tuple[str, ...] = ()) -> tuple[dict, str]:
    """Inputs for a derived figure: UNVERIFIED if any input failed the arithmetic, MISSING if a needed
    one was not filed; optional inputs not filed count as zero."""
    vals, missing = {}, False
    for m in needed + optional:
        v, s = p.get(m)
        if s == "UNVERIFIED":
            return {}, "UNVERIFIED"
        if s == "MISSING" and m in needed:
            missing = True
        vals[m] = v if v is not None else Decimal(0)
    return vals, "MISSING" if missing else "OK"


def operating_profit(p: Period) -> Derived:
    """Profit before depreciation, finance cost, other income and exceptional items:
    revenue - (total expenses - finance cost - depreciation)."""
    names = ("revenue", "total_expenses", "finance_cost", "depreciation")
    vals, state = _combine(p, names)
    if state != "OK":
        return Derived(None, state, names)
    return Derived(vals["revenue"] - vals["total_expenses"] + vals["finance_cost"] + vals["depreciation"], "OK",
                   names)


def gross_profit(p: Period) -> Derived:
    """Revenue less materials, traded goods and inventory change; only for companies that report
    materials or traded goods (for a service company the figure would just be revenue)."""
    if not any(m in p.values for m in COGS[:2]):
        return Derived(None, "MISSING", ("revenue",) + COGS)
    vals, state = _combine(p, ("revenue",), COGS)
    if state != "OK":
        return Derived(None, state, ("revenue",) + COGS)
    return Derived(vals["revenue"] - sum(vals[m] for m in COGS), "OK", ("revenue",) + COGS)


# ---------------------------------------------------------------- checks (spec 18.1)

@dataclass
class Check:
    name: str
    status: str                 # FIRED | NOT_FIRED | UNVERIFIED | NOT_MEASURABLE
    detail: str
    strength: Decimal = Decimal(0)      # how far past the threshold, in units of the threshold
    values: dict = field(default_factory=dict)
    mechanism_kind: str = "OPERATING"   # OPERATING | DEBT | NONE

    def as_dict(self) -> dict:
        return dict(name=self.name, status=self.status, detail=self.detail, strength=str(self.strength),
                    values={k: (str(v) if isinstance(v, Decimal) else v) for k, v in self.values.items()})


def _pct(x: Decimal) -> str:
    return f"{x * 100:.1f}%"


def _cr(x: Decimal) -> str:
    return f"₹{x / CR:,.2f} cr"


def _bad(name: str, a: str, b: str, what: str, kind: str = "OPERATING") -> Optional[Check]:
    if "UNVERIFIED" in (a, b):
        return Check(name, "UNVERIFIED", f"{what} fails the statement arithmetic", mechanism_kind=kind)
    if "MISSING" in (a, b):
        return Check(name, "NOT_MEASURABLE", f"{what} not reported for both periods", mechanism_kind=kind)
    return None


def margin_check(cur: Period, prior: Period) -> Check:
    name = "MARGIN_EXPANSION"
    (r1, s1), (r0, s0) = cur.get("revenue"), prior.get("revenue")
    bad = _bad(name, s1, s0, "revenue")
    if bad:
        return bad
    if r1 < POLICY["min_revenue"] or r0 < POLICY["min_revenue"]:
        return Check(name, "NOT_MEASURABLE", f"revenue below {_cr(POLICY['min_revenue'])} in one period")
    out, unverified = [], False
    for label, fn in (("gross", gross_profit), ("operating", operating_profit)):
        d1, d0 = fn(cur), fn(prior)
        if "UNVERIFIED" in (d1.state, d0.state):
            unverified = True
            continue
        if d1.state != "OK" or d0.state != "OK":
            continue
        m1, m0 = d1.value / r1, d0.value / r0
        out.append((label, m1, m0, ((m1 - m0) * 10000).quantize(Decimal(1))))
    if not out:
        return Check(name, "UNVERIFIED" if unverified else "NOT_MEASURABLE",
                     "margin inputs fail the statement arithmetic" if unverified else "no margin inputs")
    values = {f"{lb}_margin": f"{_pct(m0)} -> {_pct(m1)}" for lb, m1, m0, _ in out}
    best = max(out, key=lambda t: t[3])
    label, m1, m0, bps = best
    if bps >= POLICY["margin_bps"]:
        return Check(name, "FIRED", f"{label} margin up {bps} bps year on year ({_pct(m0)} to {_pct(m1)})",
                     bps / POLICY["margin_bps"], values | dict(bps=int(bps)))
    return Check(name, "NOT_FIRED", f"best margin change {bps} bps ({label})", values=values | dict(bps=int(bps)))


def operating_profit_check(cur: Period, prior: Period) -> Check:
    name = "OPERATING_PROFIT_GROWTH"
    d1, d0 = operating_profit(cur), operating_profit(prior)
    bad = _bad(name, d1.state, d0.state, "operating profit input")
    if bad:
        return bad
    r0 = prior.values.get("revenue") or Decimal(0)
    values = dict(operating_profit=f"{_cr(d0.value)} -> {_cr(d1.value)}")
    if d0.value <= 0 or d0.value < POLICY["operating_base_share"] * r0:
        return Check(name, "NOT_MEASURABLE", "year-earlier operating profit is not a positive comparable base "
                     f"({_cr(d0.value)})", values=values | dict(turned_positive=d0.value <= 0 < d1.value))
    growth = (d1.value - d0.value) / d0.value
    values["growth"] = _pct(growth)
    if growth >= POLICY["operating_profit_growth"]:
        return Check(name, "FIRED", f"operating profit up {_pct(growth)} year on year ({_cr(d0.value)} to "
                     f"{_cr(d1.value)})", growth / POLICY["operating_profit_growth"], values)
    return Check(name, "NOT_FIRED", f"operating profit {'+' if growth >= 0 else ''}{_pct(growth)}", values=values)


def segment_check(cur: Period, prior: Period) -> Check:
    name = "SEGMENT_LOSS_REDUCTION"
    r0 = prior.values.get("revenue")
    if not r0 or r0 <= 0:
        return Check(name, "NOT_MEASURABLE", "no year-earlier revenue to size segment losses")
    now = {segment_key(k): (k, v) for k, v in cur.segments.items()}
    found, unverified, any_loss = [], False, False
    for key0, (label, v0) in {segment_key(k): (k, v) for k, v in prior.segments.items()}.items():
        if key0 not in now:
            continue
        v1 = now[key0][1]
        if v0 is None or v1 is None:
            unverified = True
            continue
        if v0 >= 0 or -v0 < POLICY["segment_loss_share"] * r0:
            continue
        any_loss = True
        shrink = (v1 - v0) / -v0
        if shrink >= POLICY["segment_loss_reduction"]:
            found.append((shrink, label, v0, v1))
    if found:
        shrink, label, v0, v1 = max(found)
        return Check(name, "FIRED", f"{label} segment loss {'turned to profit' if v1 >= 0 else f'shrank {_pct(shrink)}'}"
                     f" ({_cr(v0)} to {_cr(v1)})", shrink / POLICY["segment_loss_reduction"],
                     dict(segments=[dict(segment=lb, prior=str(a), current=str(b)) for _, lb, a, b in found]))
    if unverified:
        return Check(name, "UNVERIFIED", "segment results fail the statement arithmetic")
    if not any_loss:
        return Check(name, "NOT_MEASURABLE", "no segment with a year-earlier loss of at least "
                     f"{_pct(POLICY['segment_loss_share'])} of revenue")
    return Check(name, "NOT_FIRED", "segment losses did not shrink enough")


def finance_cost_check(cur: Period, prior: Period) -> Check:
    name = "FINANCE_COST_DROP"
    (f1, s1), (f0, s0) = cur.get("finance_cost"), prior.get("finance_cost")
    bad = _bad(name, s1, s0, "finance cost", "DEBT")
    if bad:
        return bad
    r0 = prior.values.get("revenue") or Decimal(0)
    values = dict(finance_cost=f"{_cr(f0)} -> {_cr(f1)}")
    if f0 <= 0 or f0 < POLICY["finance_cost_share"] * r0:
        return Check(name, "NOT_MEASURABLE", "year-earlier finance cost too small to measure a drop", values=values,
                     mechanism_kind="DEBT")
    drop = (f0 - f1) / f0
    values["drop"] = _pct(drop)
    if drop >= POLICY["finance_cost_drop"]:
        return Check(name, "FIRED", f"finance cost down {_pct(drop)} year on year ({_cr(f0)} to {_cr(f1)}); "
                     "source of debt reduction to investigate", drop / POLICY["finance_cost_drop"], values,
                     mechanism_kind="DEBT")
    return Check(name, "NOT_FIRED", f"finance cost change {_pct(-drop)}", values=values, mechanism_kind="DEBT")


def working_capital_check(cur: Period, prior: Period) -> Check:
    return Check("WORKING_CAPITAL_DAYS", "NOT_MEASURABLE", "not covered: results XBRL has no balance sheet",
                 mechanism_kind="NONE")


CHECKS = (margin_check, operating_profit_check, segment_check, finance_cost_check, working_capital_check)


def run_checks(cur: Period, prior: Period) -> list[Check]:
    return [fn(cur, prior) for fn in CHECKS]


def cautions(cur: Period, prior: Period) -> list[str]:
    """Reasons the two periods may not be comparable even with the same scope and length."""
    out = []
    (r1, s1), (r0, s0) = cur.get("revenue"), prior.get("revenue")
    if s1 == s0 == "OK" and r0 and r0 > 0 and (r1 - r0) / r0 > POLICY["revenue_jump"]:
        out.append(f"revenue up {_pct((r1 - r0) / r0)}: check for an acquisition, merger or reclassification "
                   "before reading the margins")
    e1, t1 = cur.get("exceptional_items")
    if t1 == "OK" and r1 and e1 and abs(e1) >= Decimal("0.05") * abs(r1):
        out.append(f"exceptional items of {_cr(e1)} this period (excluded from operating profit)")
    (d1, u1) = cur.get("pat_discontinued")
    if u1 == "OK" and d1:
        out.append("discontinued operations reported this period")
    return out


# ---------------------------------------------------------------- mechanisms and priority (spec 18.2)

@dataclass(frozen=True)
class Mechanism:
    event_id: str
    version_id: str
    event_type: str
    stage: str
    stage_rank: int
    observation: str
    first_public_at: datetime
    details: dict

    def explains(self, kind: str) -> bool:
        if self.observation == "FORECAST" or self.stage == "CANCELLED":
            return False
        if kind == "DEBT":
            return self.event_type in DEBT_MECHANISMS and not self.details.get("funded_by_equity")
        if kind != "OPERATING" or self.event_type not in OPERATING_MECHANISMS:
            return False
        if self.event_type == "ORDER":
            return self.stage_rank >= QUALIFIED_RANK
        if self.event_type == "CAPACITY":
            return bool(self.details.get("commissioned"))
        return True

    def label(self) -> str:
        return f"{self.event_type.replace('_', ' ').lower()} ({self.stage.lower().replace('_', ' ')}, " \
               f"public {self.first_public_at.date().isoformat()})"


def classify(checks: list[Check], mechanisms: list[Mechanism], active_case: bool, equity_recent: bool,
             issuer_id: str, as_of: datetime, notes: list[str]) -> Optional[dict]:
    """One evaluation for a filing, or None when nothing fired and nothing failed verification.

    U0 open case; P2 a financial anomaly plus a possible operating explanation; P3 financial change
    with no identified mechanism (EXPLORATION when two or more checks fire); D figures to repair."""
    fired = [c for c in checks if c.status == "FIRED"]
    unverified = [c for c in checks if c.status == "UNVERIFIED"]
    if not fired and not unverified:
        return None
    explained: dict[str, list[Mechanism]] = {}
    reasons: list[str] = []
    for c in fired:
        ms = [m for m in mechanisms if m.explains(c.mechanism_kind)]
        if c.mechanism_kind == "DEBT" and equity_recent:
            ms = []
            c.detail += "; equity raised within a year, so debt may have been repaid from shareholder money"
        explained[c.name] = ms
    with_mech = [c for c in fired if explained[c.name]]
    if active_case and fired:
        cls, outcome, alloc = "U0", "ADMIT", "UPDATE"
        reasons.append("financial change for an issuer with an open research case")
    elif with_mech:
        cls, outcome, alloc = "P2", "ADMIT", "RANKED"
    elif fired:
        cls, outcome = "P3", "DEFER"
        alloc = "EXPLORATION" if len(fired) >= 2 else "NONE"
    else:
        cls, outcome, alloc = "D", "DEFER", "NONE"
    for c in sorted(fired, key=lambda c: -c.strength):
        ms = explained[c.name]
        reasons.append(f"{c.detail}; possible mechanism: {', '.join(m.label() for m in ms[:3])}" if ms
                       else f"{c.detail}; no mechanism identified")
    for c in unverified:
        reasons.append(f"data repair: {c.name.lower().replace('_', ' ')} not checked, {c.detail}")
    reasons += notes
    strength = max((c.strength for c in fired), default=Decimal(0))
    band = 3 if strength >= 2 else 2 if strength >= Decimal("1.5") else 1 if fired else 0
    tie = hashlib.sha256(f"{issuer_id}|{RULES_VERSION}".encode()).hexdigest()[:16]
    return dict(
        priority_class=cls, outcome=outcome, queue_allocation=alloc, reasons=reasons,
        fired=[c.name for c in fired], unverified=[c.name for c in unverified],
        mechanisms={k: [m.version_id for m in v] for k, v in explained.items()},
        without_mechanism=[c.name for c in fired if not explained[c.name]],
        trigger_versions=sorted({m.version_id for v in explained.values() for m in v}),
        # same shape as the commercial ranking: class, milestone-soon flag, -depth, -band, as_of, tie
        ranking=[CLASS_ORDER[cls], 1, -len(fired), -band, as_of.isoformat(), tie])


def comparable_window(period_end) -> tuple:
    """Year-earlier period ends accepted as comparable."""
    try:
        target = period_end.replace(year=period_end.year - 1)
    except ValueError:                                  # 29 February
        target = period_end.replace(year=period_end.year - 1, day=28)
    tol = timedelta(days=POLICY["comparable_tolerance_days"])
    return target - tol, target + tol
