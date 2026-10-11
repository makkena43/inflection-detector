"""Shadow replay rules that need no database: the frozen execution rule, one outcome from a price
series, how a later large move is classified, and the summary tables (spec 12, 14 phase 2).

Returns are price returns on unadjusted closes, adjusted for splits and bonuses between entry and
exit.  Dividends are not included, so the return is labelled a price return and compared with the
median price return of the same exchange's universe over the same dates, never with a total-return
index.  A split or bonus with no known multiplier leaves the return unknown; one not reconciled
against the exchange's own adjustment, or a rights issue, merger or delisting in the window, makes
it UNVERIFIED (spec 12, 15.10).  Nothing here is a trading rule: the entry rule is the earliest
point the replay could have acted on, and the summaries describe the queue, not a portfolio.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from statistics import median
from typing import Iterable, Optional

from ..asof import IST

POLICY_VERSION = "replay-1"
POLICY = dict(
    entry_lag_days=7,           # entry at the first close on or after cutoff + this: the week triage takes
    entry_window_days=10,       # no close that soon after the target: NO_PRICE
    stopped_days=30,            # last close this far before the exit target: STOPPED_TRADING
    horizons={"3m": 91, "6m": 182, "12m": 365, "24m": 730},
    big_move="0.50",            # a price return at least this large counts as a big move
    big_move_horizon="12m",
    winner_min_traded_value="1000000",   # rupees a day, mean of the month before: no untradeable winners
    winner_lookback_days=182,   # a winner counts as caught when shortlisted from this long before
    winner_lookahead_days=91,   # ... to this long after the start of its move
)
SHORTLISTED = ("UPDATE", "RANKED", "EXPLORATION", "AUDIT")
UNVERIFYING = ("RIGHTS", "MERGER", "DELISTING", "DEMERGER")
MEASURED = ("VERIFIED", "UNVERIFIED", "STOPPED_TRADING")   # a stopped stock still counts
TWO = Decimal("0.0001")


def policy(**overrides) -> dict:
    unknown = set(overrides) - set(POLICY)
    if unknown:
        raise ValueError(f"unknown replay policy keys: {sorted(unknown)}")
    p = {**POLICY, **{k: v for k, v in overrides.items() if v is not None}}
    if p["big_move_horizon"] not in p["horizons"]:
        raise ValueError(f"big_move_horizon {p['big_move_horizon']} is not one of the horizons")
    return p


def policy_hash(p: dict) -> str:
    return hashlib.sha256(json.dumps([POLICY_VERSION, p], sort_keys=True, default=str).encode()).hexdigest()


def weeks(first: date, last: date) -> list[tuple[date, datetime]]:
    """(Monday, cutoff) for every week from the one holding ``first`` to the one holding ``last``."""
    start = first - timedelta(days=first.weekday())
    end = last - timedelta(days=last.weekday())
    out = []
    while start <= end:
        out.append((start, datetime.combine(start + timedelta(days=7), time(0), tzinfo=IST)))
        start += timedelta(days=7)
    return out


def period(week_start: date, holdout_from: Optional[date]) -> str:
    return "HOLDOUT" if holdout_from and week_start >= holdout_from else "DEVELOPMENT"


def entry_target(cutoff: datetime, p: dict) -> date:
    return cutoff.astimezone(IST).date() + timedelta(days=p["entry_lag_days"])


# ---------------------------------------------------------------- one outcome

@dataclass
class Outcome:
    status: str
    entry_date: Optional[date] = None
    entry_close: Optional[Decimal] = None
    exit_date: Optional[date] = None
    exit_close: Optional[Decimal] = None
    multiplier: Optional[Decimal] = None
    price_return: Optional[Decimal] = None
    max_drawdown: Optional[Decimal] = None
    notes: list = field(default_factory=list)


def outcome(series: list[tuple], actions: list[dict], target: date, horizon_days: int, last_market_day: date,
            p: dict) -> Outcome:
    """``series``: (trade date, close) sorted by date.  ``actions``: dicts with kind, ex_date,
    multiplier (or None) and reconciled.  ``last_market_day``: the latest close on the exchange."""
    entry = next(((d, c) for d, c in series if d >= target), None)
    if entry is None or (entry[0] - target).days > p["entry_window_days"]:
        return Outcome("NO_PRICE", notes=[f"no close within {p['entry_window_days']} days of {target.isoformat()}"])
    exit_target = entry[0] + timedelta(days=horizon_days)
    if exit_target > last_market_day:
        return Outcome("INCOMPLETE", entry[0], entry[1],
                       notes=[f"horizon ends {exit_target.isoformat()}, after the last close {last_market_day.isoformat()}"])
    window = [(d, c) for d, c in series if entry[0] <= d <= exit_target]
    exit_ = window[-1]
    notes, status = [], "VERIFIED"
    if (exit_target - exit_[0]).days > p["stopped_days"]:
        status = "STOPPED_TRADING"
        notes.append(f"last close {exit_[0].isoformat()}, before the horizon ends {exit_target.isoformat()}")
    inside = [a for a in actions if entry[0] < a["ex_date"] <= exit_[0]]
    adjusting = [a for a in inside if a["kind"] in ("SPLIT", "BONUS")]
    if any(a.get("multiplier") is None for a in adjusting):
        return Outcome("UNVERIFIED", entry[0], entry[1], exit_[0], exit_[1],
                       notes=notes + ["a split or bonus in the window has no known price multiplier"])
    if status == "VERIFIED" and any(not a.get("reconciled") for a in adjusting):
        status = "UNVERIFIED"
        notes.append("a split or bonus in the window is not reconciled with the exchange's prices")
    for a in inside:
        if a["kind"] in UNVERIFYING:
            status = "UNVERIFIED" if status == "VERIFIED" else status
            notes.append(f"{a['kind'].lower()} on {a['ex_date'].isoformat()}: price return alone is not the "
                         "shareholder's return")
    dividends = sum(1 for a in inside if a["kind"] == "DIVIDEND")
    if dividends:
        notes.append(f"{dividends} dividend(s) in the window, not included")

    def factor(d: date) -> Decimal:
        f = Decimal(1)
        for a in adjusting:
            if d < a["ex_date"]:
                f *= Decimal(a["multiplier"])
        return f

    mult = factor(entry[0])
    peak, worst = None, Decimal(0)
    for d, c in window:
        v = Decimal(c) * factor(d)
        peak = v if peak is None or v > peak else peak
        worst = min(worst, v / peak - 1)
    ret = Decimal(exit_[1]) / (Decimal(entry[1]) * mult) - 1
    return Outcome(status, entry[0], entry[1], exit_[0], exit_[1], mult, ret.quantize(TWO), worst.quantize(TWO), notes)


# ---------------------------------------------------------------- missed winners

def winner_status(shortlisted_weeks: list[date], queued_weeks: list[date], has_figures: bool, has_filings: bool,
                  move_start: date, p: dict) -> tuple[str, Optional[date]]:
    """Whether the replay had the company in time for a large move that began at ``move_start``."""
    lo = move_start - timedelta(days=p["winner_lookback_days"])
    hi = move_start + timedelta(days=p["winner_lookahead_days"])
    hits = sorted(w for w in shortlisted_weeks if lo <= w <= hi)
    if hits:
        return "SHORTLISTED", hits[0]
    if any(lo <= w <= hi for w in queued_weeks):
        return "QUEUED_NOT_SHORTLISTED", None
    if has_figures or has_filings:
        return "FIGURES_NO_NOMINATION", None
    return "NO_COVERAGE", None


# ---------------------------------------------------------------- summaries

def _pct(x: Optional[Decimal]) -> Optional[str]:
    return None if x is None else str((Decimal(x) * 100).quantize(Decimal("0.1")))


def stats(rows: Iterable[dict], p: dict) -> dict:
    """Return statistics for the outcome rows of one group and one horizon."""
    rows = list(rows)
    by: dict = defaultdict(int)
    for r in rows:
        by[r["status"]] += 1
    measured = [r for r in rows if r["status"] in MEASURED and r["price_return"] is not None]
    rets = [Decimal(r["price_return"]) for r in measured]
    exc = [Decimal(r["excess_return"]) for r in measured if r.get("excess_return") is not None]
    dd = [Decimal(r["max_drawdown"]) for r in measured if r.get("max_drawdown") is not None]
    big = Decimal(p["big_move"])
    out = dict(items=len(rows), by_status=dict(sorted(by.items())), measured=len(measured),
               unverified=sum(1 for r in measured if r["status"] == "UNVERIFIED"),
               stopped_trading=sum(1 for r in measured if r["status"] == "STOPPED_TRADING"),
               companies=len({r["issuer_id"] for r in measured}))
    if not measured:
        return out
    out.update(
        mean_return_pct=_pct(sum(rets) / len(rets)), median_return_pct=_pct(median(rets)),
        median_excess_pct=_pct(median(exc)) if exc else None,
        beat_universe_median_pct=_pct(Decimal(sum(1 for e in exc if e > 0)) / len(exc)) if exc else None,
        big_move_pct=_pct(Decimal(sum(1 for x in rets if x >= big)) / len(rets)),
        lost_half_pct=_pct(Decimal(sum(1 for x in rets if x <= Decimal("-0.5"))) / len(rets)),
        median_max_drawdown_pct=_pct(median(dd)) if dd else None)
    return out


def _groups(item: dict) -> list[str]:
    g = ["shortlisted" if item["shortlisted"] else "not_shortlisted_new_evidence",
         f"slot:{item['slot']}", f"class:{item['priority_class']}", f"routes:{'+'.join(item['routes'])}",
         f"year:{item['week_start'].year}"]
    if item["shortlisted"] and item.get("first_time"):
        g.append("shortlisted_first_time")
    return g


def summarise(items: list[dict], outcomes: list[dict], p: dict, include_holdout: bool = False) -> dict:
    """Outcome statistics by group and horizon.  Holdout weeks are counted but their returns are left
    out unless ``include_holdout`` (spec 12: fix thresholds before reviewing holdout returns)."""
    key = {(i["week_start"], i["issuer_id"]): i for i in items}
    cells: dict = defaultdict(list)
    held = defaultdict(int)
    for o in outcomes:
        it = key[(o["week_start"], o["issuer_id"])]
        if it["period"] == "HOLDOUT" and not include_holdout:
            held[o["horizon"]] += 1
            continue
        row = dict(o, issuer_id=o["issuer_id"])
        for g in _groups(it):
            cells[(g, o["horizon"])].append(row)
    out: dict = {}
    for (g, h), rows in sorted(cells.items(), key=lambda kv: (kv[0][0], p["horizons"].get(kv[0][1], 0))):
        out.setdefault(g, {})[h] = stats(rows, p)
    return dict(groups=out, holdout_outcomes_hidden=dict(held) if held else {},
                return_basis="price return adjusted for splits and bonuses, dividends excluded; benchmark is "
                             "the median price return of the same exchange's securities over the same dates")


def mark_first_time(items: list[dict]) -> None:
    """Flag each company's first shortlisting in the replay."""
    seen: set = set()
    for it in sorted(items, key=lambda i: i["week_start"]):
        if it["shortlisted"]:
            it["first_time"] = it["issuer_id"] not in seen
            seen.add(it["issuer_id"])
