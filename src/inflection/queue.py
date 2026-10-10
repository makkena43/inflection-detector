"""One line per company across the discovery routes (spec 18.2: one issuer-level case, not one per
filing or per route).

Each company takes its best priority class from its candidate evaluations in the window.  A
financial nomination with no mechanism of its own (P3) is raised to P2 when the same company also
has, in the window, and for an operating check (not the interest check), a commercial evaluation carrying an observed operating event that the
financial rules accept as a mechanism: the commercial event may have come after the results, which
the point-in-time financial evaluation could not see.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from typing import Optional

from .financial import rules as FR
from .financial.pipeline import _SYMBOL, _day_bounds


def _operating(evt: dict) -> bool:
    m = FR.Mechanism("", "", evt.get("event_type") or "", evt.get("stage") or "UNKNOWN",
                     _rank(evt.get("stage")), evt.get("observation") or "OBSERVED", None, {})
    if m.event_type == "CAPACITY":
        return False                    # commissioning is not visible in the evaluation summary
    return m.explains("OPERATING")


def _rank(stage: Optional[str]) -> int:
    from .commercial.vocabulary import STAGE_RANK
    return STAGE_RANK.get(stage or "", 0)


def companies(conn, start: Optional[date] = None, end: Optional[date] = None, top: int = 50) -> list[dict]:
    lo, hi = _day_bounds(start, end)
    rows = conn.execute(
        f"""SELECT c.issuer_id, {_SYMBOL.format(col='c.issuer_id')}, i.legal_name, c.route, c.as_of,
                   c.priority_class, c.outcome, c.reasons, c.components, c.ranking_tuple
              FROM candidate_evaluations c JOIN issuers i USING (issuer_id)
             WHERE (%(lo)s::timestamptz IS NULL OR c.as_of >= %(lo)s)
               AND (%(hi)s::timestamptz IS NULL OR c.as_of < %(hi)s)
             ORDER BY c.issuer_id, c.as_of""", dict(lo=lo, hi=hi)).fetchall()
    by: dict = defaultdict(list)
    for r in rows:
        by[r[0]].append(r)
    out = []
    for issuer_id, evs in by.items():
        best = min(evs, key=lambda r: (FR.CLASS_ORDER[r[5]], -r[4].timestamp()))
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
            symbol=best[1], name=best[2], priority=cls, routes=routes, corroborated=corroborated,
            latest=max(r[4] for r in evs).isoformat(), reason=why,
            evaluations=[dict(route=r[3], as_of=r[4].isoformat(), priority=r[5], outcome=r[6], reason=r[7][0])
                         for r in evs[-6:]]))
    out.sort(key=lambda d: d["latest"], reverse=True)
    out.sort(key=lambda d: (FR.CLASS_ORDER[d["priority"]], not d["corroborated"]))
    return out[:top]
