"""Weekly allocation of the combined queue into a shortlist for AI triage (spec 5.2, 18.2, 18.3).

No fixed company count: by owner decision (10 Oct 2026) the 12-companies-a-week limit of spec
section 1 is dropped.  Every U0, P1 and P2 company is shortlisted unless ``ranked_cap`` is set;
over a cap the rest is deferred visibly and keeps its waiting time.  Aging works two ways: within a
class a longer wait ranks first among otherwise equal companies, and the exploration slots take
the oldest waiting companies whatever their materiality, so a poorly quantified disclosure is not
stuck at the bottom.  Nothing is ordered alphabetically and nothing expires into rejection: a
company waiting past ``stale_days`` is marked stale and stays in the queue.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Optional

from ..financial.rules import CLASS_ORDER

POLICY_VERSION = "triage-1"
POLICY = dict(
    ranked_cap=None,            # P1/P2 companies per week; None = all of them
    exploration=4,              # oldest waiting companies outside the ranked slots
    audit=2,                    # rotating sample of P3 (watch) companies, a false-negative check
    cooldown_days=30,           # after a triage, unless something material changed
    stale_days=90,              # waiting longer than this is STALE_UNRESEARCHED; still queued
)
SHORTLISTED = ("UPDATE", "RANKED", "EXPLORATION", "AUDIT")


def policy(**overrides) -> dict:
    unknown = set(overrides) - set(POLICY)
    if unknown:
        raise ValueError(f"unknown policy keys: {sorted(unknown)}")
    return {**POLICY, **{k: v for k, v in overrides.items() if v is not None or k == "ranked_cap"}}


def policy_hash(p: dict) -> str:
    return hashlib.sha256(json.dumps([POLICY_VERSION, p], sort_keys=True).encode()).hexdigest()


@dataclass
class Triaged:
    """The company's last triage: the shortlist cutoff it was read at, its class then, and the
    commercial event versions it saw."""
    cutoff: datetime
    priority_class: str
    triggers: set = field(default_factory=set)


def _tie(issuer_id, salt: str) -> str:
    return hashlib.sha256(f"{issuer_id}|{salt}".encode()).hexdigest()[:16]


def _cooldown(line: dict, last: Optional[Triaged], cutoff: datetime, p: dict) -> Optional[str]:
    """Why the company waits out its cooldown, or None.  A U0 update, a better class or a new
    commercial event version (stage advance, amendment, cancellation) bypasses it."""
    if last is None:
        return None
    until = last.cutoff + timedelta(days=p["cooldown_days"])
    if cutoff >= until or line["priority"] == "U0":
        return None
    if CLASS_ORDER[line["priority"]] < CLASS_ORDER[last.priority_class]:
        return None
    if CLASS_ORDER[line["priority"]] <= CLASS_ORDER["P2"] and set(line["commercial_triggers"]) - last.triggers:
        return None
    return f"triaged at {last.priority_class} for the week to {last.cutoff.date().isoformat()}; " \
           f"cooldown until {until.date().isoformat()} with no new stage or better class"


def allocate(lines: list[dict], week_start: date, cutoff: datetime, p: dict,
             triaged: Optional[dict] = None) -> list[dict]:
    """One item per queue line, each with its slot, in shortlist order first."""
    triaged = triaged or {}
    items, ranked, explore, watch = [], [], [], []
    for ln in lines:
        it = dict(ln, slot=None, position=None, note=None,
                  stale=ln["waiting_since"] < cutoff - timedelta(days=p["stale_days"]),
                  ranking=[CLASS_ORDER[ln["priority"]], *ln["within_class"], ln["waiting_since"].isoformat(),
                           _tie(ln["issuer_id"], POLICY_VERSION)])
        items.append(it)
        why = _cooldown(ln, triaged.get(ln["issuer_id"]), cutoff, p)
        if ln["priority"] == "D":
            it["slot"], it["note"] = "DATA_REPAIR", "figures or identity to repair; not a fundamental verdict"
        elif why:
            it["slot"], it["note"] = "COOLDOWN", why
        elif ln["priority"] == "U0":
            it["slot"] = "UPDATE"
        elif ln["priority"] in ("P1", "P2"):
            ranked.append(it)
        elif "EXPLORATION" in ln["allocations"]:
            explore.append(it)
        else:
            watch.append(it)

    ranked.sort(key=lambda i: i["ranking"])
    cap = p["ranked_cap"]
    over = ranked[cap:] if cap is not None else []
    for it in ranked[:len(ranked) - len(over)]:
        it["slot"] = "RANKED"
    pool = sorted(over + explore, key=lambda i: (i["waiting_since"], i["ranking"][-1]))
    for k, it in enumerate(pool):
        if k < p["exploration"]:
            it["slot"], it["note"] = "EXPLORATION", "oldest waiting outside the ranked slots"
        elif it["priority"] in ("P1", "P2"):
            it["slot"], it["note"] = "DEFERRED", f"over the ranked cap of {cap}; keeps its waiting time"
        else:
            watch.append(it)
    watch.sort(key=lambda i: _tie(i["issuer_id"], week_start.isoformat()))
    for k, it in enumerate(watch):
        if k < p["audit"]:
            it["slot"], it["note"] = "AUDIT", "rotating sample of watch companies (false-negative check)"
        else:
            it["slot"] = "WATCH"
    for it in items:
        if it["stale"]:
            days = (cutoff - it["waiting_since"]).days
            it["note"] = "; ".join(filter(None, [it["note"], f"STALE_UNRESEARCHED: waiting {days} days, "
                                                              "check the catalyst still holds"]))

    updates = sorted((i for i in items if i["slot"] == "UPDATE"), key=lambda i: i["ranking"])
    short = updates + [i for i in ranked if i["slot"] == "RANKED"] \
        + [i for i in pool if i["slot"] == "EXPLORATION"] + [i for i in watch if i["slot"] == "AUDIT"]
    for k, it in enumerate(short, 1):
        it["position"] = k
    rest = sorted((i for i in items if i["position"] is None), key=lambda i: (i["slot"], i["ranking"]))
    return short + rest


def summary(items: list[dict], week_start: date, cutoff: datetime, p: dict) -> dict:
    """Counts by slot, inflow and queue age; when a cap defers companies, the expected delay."""
    by: dict = {}
    for it in items:
        by[it["slot"]] = by.get(it["slot"], 0) + 1
    start = datetime.combine(week_start, datetime.min.time(), tzinfo=cutoff.tzinfo)
    waiting = sorted((cutoff - i["waiting_since"]).days for i in items if i["slot"] != "COOLDOWN")
    deferred = by.get("DEFERRED", 0)
    out = dict(
        companies_in_queue=len(items), shortlisted=sum(by.get(s, 0) for s in SHORTLISTED), slots=by,
        new_this_week=sum(1 for i in items if i["waiting_since"] >= start),
        stale=sum(1 for i in items if i["stale"]),
        oldest_waiting_days=waiting[-1] if waiting else None,
        median_waiting_days=waiting[len(waiting) // 2] if waiting else None,
        warnings=[])
    if deferred:
        weeks = -(-deferred // p["ranked_cap"]) if p["ranked_cap"] else None
        out["expected_delay_weeks"] = weeks
        out["warnings"].append(f"{deferred} P1/P2 companies over the ranked cap of {p['ranked_cap']}; "
                               f"about {weeks} more weeks at this cap. Raise the cap or narrow the universe.")
    return out
