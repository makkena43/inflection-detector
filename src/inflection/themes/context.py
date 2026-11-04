"""Theme assessment for one company at one cutoff: the evidence a reviewer needs, computed, not guessed.

For each emergent theme the company belongs to in the newest snapshot on or before the cutoff:
  * theme strength: stage, companies now vs a year ago, momentum (companies now vs the same theme 13 weeks earlier,
    followed by its carried-over key), weeks since first detected, total firm order value;
  * the company's place in it: role (maker / supplier / EPC / buyer), passages, firm value, rank by value among the
    theme's companies, share of the theme's value, and whether it was an early entrant (first seen within
    EARLY_DAYS of the theme's first detection, or before it);
  * the link to this packet: which of the packet's own events have a passage that uses one of the theme's phrases;
  * supply-gap confirmation: a MakroGraph supply-gap product of the company with an evidenced maker/supplier/EPC role
    whose words match the theme's phrases.
Informational, not yet used by the grade: crowding (the equal-weight 3- and 6-month return of the theme's companies,
split/bonus adjusted, minus the Nifty Smallcap 250 over the same days, priced on or before the snapshot date) and
the company's firm theme order value as % of its trailing-twelve-month revenue (when the caller passes a current
revenue). Then a grade with its reasons (see GRADES). The grade is a summary for the reviewer and for backtests; the rules
decide how much it may count. Everything uses only snapshots and passages public by the cutoff.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Optional

from . import emergent

EARLY_DAYS = 90
MOMENTUM_DAYS = 91
SUPPLY_ROLES = ("MAKER", "SUPPLIER", "EPC")
CROWD_INDEX = "Nifty Smallcap 250"
CROWD_DAYS = (91, 182)          # 3 and 6 months
CROWD_GAP = 10                  # a member's or the index's close must fall within this many days before each anchor
GRADES = {
    "A": "strong tailwind: maker/supplier/EPC in an emerging or accelerating theme (or consensus still growing 50%+), "
         "not losing companies over 13 weeks, and one of this packet's events is in the theme",
    "B": "tailwind: maker/supplier/EPC in a theme at stage 1-3 that is growing, but the packet's events are not in "
         "it (or it is losing companies over 13 weeks)",
    "CROWDED": "saturating theme (stage 4): many companies, no growth left",
    "HEADWIND": "buyer/user in the theme (a shortage raises its costs), or a declining theme (stage 5)",
    "NONE": "role not stated, or the theme is forming / not growing",
}
GRADE_ORDER = ("A", "B", "NONE", "CROWDED", "HEADWIND")


def _stem(w: str) -> str:
    return w[:-1] if len(w) > 3 and w.endswith("s") else w


def _words(text: str) -> set:
    return {_stem(w) for w in re.findall(r"[a-z][a-z\-]+", (text or "").lower()) if w not in emergent.STOP}


def grade(stage: int, growth: Optional[float], momentum: Optional[int], role: Optional[str], in_packet: bool) -> tuple:
    """(grade, reasons) for one company in one theme. Pure."""
    if role == "BUYER":
        return "HEADWIND", ["company is a buyer/user in this theme"]
    if stage == 5:
        return "HEADWIND", ["theme is declining (companies down a third or more on a year ago)"]
    if stage == 4:
        return "CROWDED", ["theme is saturating (25+ companies, not growing)"]
    if role not in SUPPLY_ROLES:
        return "NONE", ["company's role in the theme is not stated in its own filings"]
    growing = growth is None or growth > 0
    hot = stage in (1, 2) or (stage == 3 and growth is not None and growth >= 50)
    if not growing or stage == 0:
        return "NONE", ["theme is forming (under 4 companies) or not growing"]
    why = [f"company is a {role.lower()} in a stage-{stage} theme"
           + (f" growing {growth:+.0f}% on a year ago" if growth is not None else " that is new this year")]
    if hot and in_packet and (momentum is None or momentum >= 0):
        return "A", why + ["one of this packet's events is in the theme"]
    if momentum is not None and momentum < 0:
        why.append(f"theme lost {-momentum} companies over 13 weeks")
    if not in_packet:
        why.append("none of this packet's events is in the theme")
    return "B", why


_CROWD_CACHE: dict = {}


def _last_close(rows, anchor: date) -> Optional[float]:
    """Close of the last row on or before anchor, within CROWD_GAP days. rows: (trade_date, close) sorted by date."""
    best = None
    for d, c in rows:
        if d > anchor:
            break
        if (anchor - d).days <= CROWD_GAP:
            best = float(c)
    return best


def crowding(conn, as_of: date, theme_key: str) -> dict:
    """Equal-weight 3/6-month return of the theme's companies at as_of minus the Smallcap 250 return, in % points.
    Members whose adjusted price is unverified (an unreconciled split/bonus) or missing at either end are left out."""
    k = (as_of, theme_key)
    if k in _CROWD_CACHE:
        return _CROWD_CACHE[k]
    start = as_of - timedelta(days=max(CROWD_DAYS) + CROWD_GAP)
    px = conn.execute(
        """SELECT DISTINCT ON (s.issuer_id, p.trade_date) s.issuer_id, p.trade_date, p.close, p.unverified
             FROM emergent_theme_companies c JOIN securities s USING (issuer_id)
             JOIN prices_split_bonus_adjusted p USING (security_id)
            WHERE c.as_of = %s AND c.theme_key = %s AND p.trade_date BETWEEN %s AND %s AND p.close > 0
            ORDER BY s.issuer_id, p.trade_date, (p.provider = 'nse_bhavcopy') DESC, p.provider_version DESC""",
        (as_of, theme_key, start, as_of)).fetchall()
    idx = conn.execute("SELECT trade_date, close FROM index_closes WHERE index_name = %s AND trade_date BETWEEN %s AND %s"
                       " ORDER BY trade_date", (CROWD_INDEX, start, as_of)).fetchall()
    by: dict = {}
    bad = {i for i, _, _, u in px if u}
    for i, d, c, _ in px:
        if i not in bad:
            by.setdefault(i, []).append((d, c))
    out = {}
    for days in CROWD_DAYS:
        a0 = as_of - timedelta(days=days)
        i0, i1 = _last_close(idx, a0), _last_close(idx, as_of)
        rets = []
        for rows in by.values():
            c0, c1 = _last_close(rows, a0), _last_close(rows, as_of)
            if c0 and c1:
                rets.append(c1 / c0 - 1)
        m = f"{round(days / 30.4)}m"
        out[f"crowding_return_{m}"] = (round(100 * (sum(rets) / len(rets) - (i1 / i0 - 1)), 1)
                                       if rets and i0 and i1 else None)
        out[f"crowding_priced_{m}"] = len(rets)
    _CROWD_CACHE[k] = out
    return out


def assess(conn, issuer_id, cutoff: datetime, passages: list[dict], supply_gap: Optional[dict] = None,
           mode: str = "PUBLIC_INFORMATION", limit: int = 5, ttm_revenue_cr: Optional[float] = None) -> dict:
    """Theme assessment for a packet. passages: the packet's passages (dicts with event_id and quote).
    ttm_revenue_cr: the packet's current trailing-twelve-month revenue, if known."""
    if cutoff.tzinfo is None:
        raise ValueError("cutoff must be timezone-aware")
    p = dict(i=issuer_id, d=cutoff.astimezone(emergent.IST).date(), c=cutoff, v=emergent.VERSION,
             replay=mode == "ACTUAL_SYSTEM_REPLAY")
    latest = conn.execute("""SELECT max(as_of) FROM emergent_theme_snapshots
                              WHERE version = %(v)s AND as_of <= %(d)s AND (NOT %(replay)s OR recorded_at <= %(c)s)""",
                          p).fetchone()[0]
    sg = [t for t in (supply_gap or {}).get("themes", []) if t.get("company_role") in SUPPLY_ROLES]
    if latest is None:
        return {"snapshot": None, "themes": [], "best_grade": "NONE", "grades": GRADES}
    p["l"] = latest
    rows = conn.execute(
        """SELECT s.theme_key, s.name, s.stage, s.companies, s.companies_prior, s.growth_pct, s.first_detected,
                  s.order_value_cr, s.phrases, c.role, c.mentions, c.value_cr, c.first_seen,
                  (SELECT count(*) + 1 FROM emergent_theme_companies o
                    WHERE o.as_of = c.as_of AND o.theme_key = c.theme_key AND o.value_cr > c.value_cr)
             FROM emergent_theme_companies c JOIN emergent_theme_snapshots s USING (as_of, theme_key)
            WHERE c.as_of = %(l)s AND c.issuer_id = %(i)s AND s.version = %(v)s""", p).fetchall()
    pas_words = [(x.get("event_id"), _words(x.get("quote", ""))) for x in passages or []]
    out = []
    for key, name, stage, cos, prior, growth, first_det, tval, phrases, role, ment, val, first_seen, rank in rows:
        growth = float(growth) if growth is not None else None
        before = conn.execute(
            """SELECT companies FROM emergent_theme_snapshots WHERE theme_key = %s AND version = %s
                AND as_of <= %s ORDER BY as_of DESC LIMIT 1""",
            (key, emergent.VERSION, latest - timedelta(days=MOMENTUM_DAYS))).fetchone()
        momentum = cos - before[0] if before else None
        theme_words = [_words(ph) for ph in phrases or []]
        events = sorted({str(e) for e, w in pas_words if e and any(tw and tw <= w for tw in theme_words)})
        tw_all = set().union(*theme_words) if theme_words else set()
        confirmed = [t["product"] for t in sg if _words(t["product"]) & tw_all - {"system", "equipment", "manufacturing"}]
        g, why = grade(stage, growth, momentum, role, bool(events))
        if confirmed and g in ("A", "B"):
            why.append("confirmed by supply-gap theme " + ", ".join(confirmed))
        tval = Decimal(tval or 0)
        out.append(dict(
            theme=name, stage=stage, companies=cos, companies_year_ago=prior, growth_pct=growth,
            momentum_13w=momentum, weeks_tracked=(latest - first_det).days // 7, theme_value_cr=float(tval),
            role=role, company_passages=ment, company_value_cr=float(val), company_rank=rank,
            company_value_share_pct=round(float(Decimal(val) / tval * 100), 1) if tval else None,
            entrant="EARLY" if first_seen <= first_det + timedelta(days=EARLY_DAYS) else "LATER",
            company_first_seen=first_seen.isoformat(), packet_events_in_theme=events,
            company_value_pct_ttm_revenue=(round(float(val) / ttm_revenue_cr * 100, 1)
                                           if ttm_revenue_cr and ttm_revenue_cr > 0 and val is not None else None),
            **crowding(conn, latest, key),
            supply_gap_confirmed=confirmed, grade=g, reasons=why, phrases=list(phrases or [])[:5]))
    out.sort(key=lambda t: (GRADE_ORDER.index(t["grade"]), -t["company_value_cr"], t["theme"]))
    best = out[0]["grade"] if out else "NONE"
    if any(t["grade"] == "HEADWIND" for t in out) and best not in ("A", "B"):
        best = "HEADWIND"
    return {"snapshot": latest.isoformat(), "themes": out[:limit], "best_grade": best, "grades": GRADES}
