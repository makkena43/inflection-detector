"""One line per company across the discovery routes (spec 18.2: one issuer-level case, not one per
filing or per route).

Each company takes its best priority class from its candidate evaluations in the window.  A
financial nomination with no mechanism of its own (P3) is raised to P2 when the same company also
has, in the window, and for an operating check (not the interest check), a commercial evaluation carrying an observed operating event that the
financial rules accept as a mechanism: the commercial event may have come after the results, which
the point-in-time financial evaluation could not see.

Each line also says how long the company has waited: ``waiting_since`` is its oldest evaluation in
the window, so a company passed over keeps its original waiting time (spec 18.3).  ``lines`` takes,
per company, the time after which evaluations count (its last triage), which is how the weekly
triage shortlist (``inflection.triage``) leaves out evaluations a triage already saw.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime
from typing import Optional

from .commercial import vocabulary as CV
from .financial import rules as FR
from .financial.pipeline import _SYMBOL, _day_bounds


# The company's exchange symbol, or its ISIN when no symbol is on record (an issuer known only from
# a filing or an ISIN-bearing price row, or a suspended or delisted name), so it can still be named.
LABEL = "coalesce(" + _SYMBOL + ", (SELECT s.isin FROM securities s WHERE s.issuer_id = {col} ORDER BY s.isin LIMIT 1))"


def _operating(evt: dict) -> bool:
    m = FR.Mechanism("", "", evt.get("event_type") or "", evt.get("stage") or "UNKNOWN",
                     _rank(evt.get("stage")), evt.get("observation") or "OBSERVED", None, {})
    if m.event_type == "CAPACITY":
        return False                    # commissioning is not visible in the evaluation summary
    return m.explains("OPERATING")


def _rank(stage: Optional[str]) -> int:
    from .commercial.vocabulary import STAGE_RANK
    return STAGE_RANK.get(stage or "", 0)


def _within_class(r) -> tuple:
    """Milestone-soon flag, -stage (or -checks fired), -materiality band from the ranking tuple."""
    t = r[9] or []
    return tuple(int(x) for x in t[1:4]) if len(t) >= 4 else (1, 0, 0)


def lines(conn, start: Optional[datetime] = None, end: Optional[datetime] = None,
          since: Optional[dict] = None) -> list[dict]:
    """Every company with an evaluation in [start, end), unsorted.  ``since`` maps issuer_id to a
    time: only that company's evaluations after it count, and a company with none is left out."""
    return from_rows(evaluation_rows(conn, start, end), since)


# A commercial evaluation made under older rules whose filing has since been read under the current
# rules: the re-read replaces it (evaluations are append-only, so it stays stored but out of the queue).
_SUPERSEDED = """c.route = 'COMMERCIAL' AND c.policy_version <> %(cv)s AND EXISTS (
    SELECT 1 FROM commercial_scans s WHERE s.rules_version = %(cv)s
       AND s.text_artifact_id = (c.components->'filing'->>'text_artifact_id')::uuid)"""


def evaluation_rows(conn, start: Optional[datetime] = None, end: Optional[datetime] = None,
                    include_superseded: bool = False) -> list[tuple]:
    """The evaluations with ``as_of`` in [start, end), as ``from_rows`` reads them, by company and time.
    Commercial evaluations superseded by a re-read under the current rules are left out unless
    ``include_superseded`` (an actual-system replay, which must see what was stored at the time)."""
    return conn.execute(
        f"""SELECT c.issuer_id, {LABEL.format(col='c.issuer_id')}, i.legal_name, c.route, c.as_of,
                   c.priority_class, c.outcome, c.reasons, c.components, c.ranking_tuple,
                   c.evaluation_id, c.queue_allocation, c.trigger_event_version_ids,
                   {_SYMBOL.format(col='c.issuer_id')} IS NOT NULL, c.created_at
              FROM candidate_evaluations c JOIN issuers i USING (issuer_id)
             WHERE (%(lo)s::timestamptz IS NULL OR c.as_of >= %(lo)s)
               AND (%(hi)s::timestamptz IS NULL OR c.as_of < %(hi)s)
               AND (%(all)s OR NOT ({_SUPERSEDED}))
             ORDER BY c.issuer_id, c.as_of""",
        dict(lo=start, hi=end, all=include_superseded, cv=CV.RULES_VERSION)).fetchall()


def from_rows(rows: list[tuple], since: Optional[dict] = None) -> list[dict]:
    """Queue lines from ``evaluation_rows`` (already cut to the window); ``since`` as in ``lines``."""
    since = since or {}
    by: dict = defaultdict(list)
    for r in rows:
        if r[0] in since and r[4] <= since[r[0]]:
            continue
        by[r[0]].append(r)
    out = []
    for issuer_id, evs in by.items():
        best = min(evs, key=lambda r: (FR.CLASS_ORDER[r[5]], _within_class(r), -r[4].timestamp()))
        cls, why = best[5], best[7][0]
        fin = [r for r in evs if r[3] == "FINANCIAL"
               and set(r[8].get("without_mechanism", [])) - {"FINANCE_COST_DROP", "WORKING_CAPITAL_DAYS"}]
        com = [r for r in evs if r[3] == "COMMERCIAL"
               and any(_operating(e) for e in r[8].get("events", []))]
        corroborated = bool(fin and com)
        if corroborated and FR.CLASS_ORDER[cls] > FR.CLASS_ORDER["P2"]:
            cls = "P2"
            why = f"{fin[-1][7][0]}; commercial event in the same window: {com[-1][7][0]}"
        routes = sorted({r[3] for r in evs})
        out.append(dict(
            issuer_id=issuer_id, symbol=best[1], has_symbol=best[13], name=best[2], priority=cls,
            routes=routes,
            corroborated=corroborated, waiting_since=evs[0][4], latest=max(r[4] for r in evs), reason=why,
            within_class=_within_class(best),
            allocations=sorted({r[11] for r in evs}),
            evaluation_ids=[str(r[10]) for r in evs],
            trigger_event_version_ids=sorted({str(v) for r in evs for v in (r[12] or [])}),
            commercial_triggers=sorted({str(v) for r in evs if r[3] == "COMMERCIAL" for v in (r[12] or [])}),
            evaluations=[dict(route=r[3], as_of=r[4].isoformat(), priority=r[5], outcome=r[6], reason=r[7][0])
                         for r in evs[-6:]]))
    return out


def companies(conn, start: Optional[date] = None, end: Optional[date] = None, top: int = 50) -> list[dict]:
    lo, hi = _day_bounds(start, end)
    out = lines(conn, lo, hi)
    out.sort(key=lambda d: d["latest"], reverse=True)
    out.sort(key=lambda d: (FR.CLASS_ORDER[d["priority"]], not d["corroborated"]))
    for d in out:
        d["waiting_since"], d["latest"] = d["waiting_since"].isoformat(), d["latest"].isoformat()
        for k in ("issuer_id", "has_symbol", "within_class", "allocations", "evaluation_ids", "trigger_event_version_ids",
                  "commercial_triggers"):
            d.pop(k)
    return out[:top]
