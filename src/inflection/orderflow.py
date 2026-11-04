"""Order flow at a cutoff (triage rules 3.6.2, context only): firm orders over the last 12 months against the 12 months
before, the latest order-book and inflow growth, TTM revenue growth, and the credibility checks we can make.

Firm orders are counted as the dashboard counts its "12m orders" (ui/app.py order_inflow / orders_12m): firm, realised
BINDING_DEMAND order passages; an order repeated within 90 days at about the same value counts once; a company-stated
period total replaces the single orders it already contains; a figure above 4x TTM revenue is left out. Only passages
published by the cutoff are read (and, in ACTUAL_SYSTEM_REPLAY, only rows recorded by it).

Status (backtest 2021-25, ~/inflection-jobs/themes/order_acceleration_test_2026-11-04.md, rule "C + clean"):
  ACCELERATING             ((12m >= 1.5x prior 12m AND 12m >= 25% of revenue) OR book YoY >= 30% OR inflow YoY >= 50%)
                           AND TTM revenue growth > 0, and no credibility flag
  ACCELERATING_WITH_FLAGS  the same, with a credibility flag
  STEADY                   enough data, not accelerating
  UNKNOWN                  no TTM revenue (or no orders and no order-book growth figures)
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")

SCALE_CR = {"UNITS": 1e-7, "THOUSAND": 1e-4, "LAKH": 0.01, "MILLION": 0.1, "CRORE": 1, "BILLION": 100}
# A passage that reports orders won over a period, or several orders at once, rather than one order.
PERIOD_TOTAL = re.compile(r"\b(?:in|during|for|of|till|until|so far in)\s+(?:the\s+)?(?:H1|H2|9M|9 ?months|nine months|six months|"
    r"first half|second half|half[- ]year|first quarter|quarter|year|period|FY\s?'?\s?\d{2,4}|Q[1-4])\b|year[- ]to[- ]date|\bYTD\b|"
    r"\bso far\b|till date|\bto date\b|as (?:of|on) date|current (?:financial )?(?:year|quarter)|this (?:financial )?year|annual target|"
    r"during [A-Z][a-z]+(?: \d{4})? (?:to|-) [A-Z][a-z]+|cumulative|aggregat|\btotal\b|order inflow|\binflows?\b|"
    r"\b(?:\d+|two|three|four|five|six|seven|eight|nine|ten|several|multiple|various)\s+(?:new\s+|large\s+|long[- ]term\s+|major\s+)*"
    r"(?:contracts|orders|deals|projects|work orders)\b", re.I)
ORDER_BOOK = re.compile(r"order ?book|backlog|unexecuted|pending orders|outstanding orders|orders? in hand", re.I)
WON = re.compile(r"\b(?:secured|received|won|bagged|bags|awarded|order inflow)\b", re.I)
REPEAT_DAYS = 90
MAX_X_REVENUE = 4
ACCEL_RATIO, ACCEL_SHARE, BOOK_YOY, INFLOW_YOY = 1.5, 0.25, 30.0, 50.0
PLEDGE_FLAG = 20.0
BACKTEST_NOTE = ("Backtest 2021-25: +16% vs -1% median 12m excess, mostly 2021-23; also flags fake order stories "
                 "(no receivables/cash-flow check available).")


def order_inflow(conn, issuer_id, cutoff: datetime, mode: str = "PUBLIC_INFORMATION") -> list[dict]:
    """Firm orders published by the cutoff, each tagged single / period total / order book / repeat / no FX rate."""
    rows = conn.execute(
        """SELECT m.published_at, m.amount, m.scale, coalesce(m.currency,'INR'), r.event_id, m.quote,
                  CASE WHEN coalesce(m.currency,'INR') <> 'INR' THEN
                    (SELECT x.inr_per_unit FROM dashboard_fx_rates x WHERE x.currency=m.currency
                      AND x.rate_date <= (m.published_at AT TIME ZONE 'Asia/Kolkata')::date ORDER BY x.rate_date DESC LIMIT 1) END
             FROM commercial_mentions m LEFT JOIN commercial_resolutions r USING (mention_id)
            WHERE m.issuer_id=%(i)s AND m.family='ORDER' AND m.commercial_stage='BINDING_DEMAND' AND m.modality='REALIZED'
              AND m.amount_basis IN ('FIRM','EXECUTABLE_RELEASE') AND m.amount > 0
              AND m.lifecycle IS NULL AND coalesce(r.outcome,'') <> 'NOT_AN_EVENT'
              AND m.published_at <= %(c)s AND (%(mode)s <> 'ACTUAL_SYSTEM_REPLAY' OR m.created_at <= %(c)s)
            ORDER BY m.published_at""", dict(i=issuer_id, c=cutoff, mode=mode)).fetchall()
    out, seen = [], set()
    for at, amount, scale, cur, event_id, quote, fx in rows:
        fx = float(fx) if fx else None
        cr = float(amount) * SCALE_CR.get(scale, 1) * (fx if cur != "INR" else 1) if cur == "INR" or fx else None
        d, quote = at.date(), re.sub(r"\s+", " ", quote or "")
        if cr is None:
            out.append(dict(d=d, cr=None, kind="no FX rate", quote=quote, foreign=True)); continue
        kind = "order book" if ORDER_BOOK.search(quote) and not WON.search(quote) else "period total" if PERIOD_TOTAL.search(quote) else "single"
        if kind == "single" and (event_id in seen or any(
                o["kind"] == "single" and (d - o["d"]).days <= REPEAT_DAYS
                and abs(o["cr"] - cr) <= (0.05 if cur != "INR" or o["foreign"] else 0.02) * max(o["cr"], cr) for o in out)):
            kind = "repeat"
        if event_id:
            seen.add(event_id)
        out.append(dict(d=d, cr=cr, kind=kind, quote=quote, foreign=cur != "INR"))
    return out


def period_span(t: dict) -> tuple[date, date]:
    """Rough dates a stated period total covers (as on the dashboard)."""
    d, x = t["d"], t["quote"]
    fy_start = date(d.year if d.month >= 4 else d.year - 1, 4, 1)
    if re.search(r"so far|till date|to date|as (?:of|on) date|current (?:financial )?year|this (?:financial )?year|year[- ]to[- ]date|\bYTD\b", x, re.I):
        return fy_start, d
    for pat, days in ((r"\bQ[1-4]\b|quarter", 91), (r"\bH[12]\b|six months|half", 182), (r"9 ?M\b|9 ?months|nine months", 273)):
        if re.search(pat, x, re.I):
            return d - timedelta(days=60 + days), d - timedelta(days=60)
    if re.search(r"\bFY|during the year|for the year|annual", x, re.I):
        return d - timedelta(days=60 + 365), d - timedelta(days=60)
    return d, d + timedelta(days=1)


def orders_12m(orders: list[dict], asof: date, rev: Optional[float] = None) -> Optional[float]:
    """New firm order value over the 12 months to asof, INR crore (None when there is none)."""
    win = [o for o in orders if o["cr"] is not None and asof - timedelta(days=365) < o["d"] <= asof
           and not (rev and o["cr"] > MAX_X_REVENUE * rev)]
    singles = [o for o in win if o["kind"] == "single"]
    best = sum(o["cr"] for o in singles)
    for t in (o for o in win if o["kind"] == "period total"):
        start, end = period_span(t)
        inside = (end - max(start, asof - timedelta(days=365))).days / max((end - start).days, 1)
        best = max(best, t["cr"] * min(1, max(0, inside)) + sum(o["cr"] for o in singles if o["d"] > t["d"]))
    return best or None


def status(o12: Optional[float], prior: Optional[float], rev: Optional[float], book_yoy: Optional[float],
           inflow_yoy: Optional[float], growth: Optional[float], flags: list[str]) -> str:
    """ACCELERATING / ACCELERATING_WITH_FLAGS / STEADY / UNKNOWN. Pure. growth is TTM revenue growth in %."""
    if not rev or (o12 is None and book_yoy is None and inflow_yoy is None):
        return "UNKNOWN"
    orders = bool(o12 and o12 >= ACCEL_SHARE * rev and (not prior or o12 >= ACCEL_RATIO * prior))
    book = (book_yoy is not None and book_yoy >= BOOK_YOY) or (inflow_yoy is not None and inflow_yoy >= INFLOW_YOY)
    if (orders or book) and growth is not None and growth > 0:
        return "ACCELERATING_WITH_FLAGS" if flags else "ACCELERATING"
    return "STEADY"


def credibility(conn, issuer_id, cutoff: datetime) -> dict:
    """Checks we can make from data public by the cutoff: auditor resignation / modified opinion in the prior year and
    the latest promoter pledge. Receivables and operating cash flow are not in the database."""
    aud = conn.execute(
        """SELECT count(*) FROM document_publications WHERE issuer_id=%s
             AND coalesce(published_at, published_date::timestamp AT TIME ZONE 'Asia/Kolkata') BETWEEN %s AND %s
             AND (original_category ILIKE 'Resignation of Statutory Auditor%%'
                  OR title ~* 'resign\\w* (of )?(the )?(statutory )?auditor|auditor.{0,40}resign'
                  OR (title ~* '(qualified|modified|adverse) (audit )?opinion|disclaimer of opinion' AND title !~* 'unmodified'))""",
        (issuer_id, cutoff - timedelta(days=365), cutoff)).fetchone()[0]
    pl = conn.execute("""SELECT promoter_pledged_pct FROM shareholding_patterns WHERE issuer_id=%s AND broadcast_at <= %s
                         ORDER BY period_end DESC, broadcast_at DESC LIMIT 1""", (issuer_id, cutoff)).fetchone()
    pledge = float(pl[0]) if pl and pl[0] is not None else None
    flags = []
    if aud:
        flags.append(f"auditor resignation or modified opinion in the prior year ({aud} filing{'s' if aud > 1 else ''})")
    if pledge is not None and pledge > PLEDGE_FLAG:
        flags.append(f"promoter pledge {pledge:.0f}% of holding")
    return dict(flags=flags, auditor_filings=aud, pledge_pct=pledge)


def _num(v) -> Optional[float]:
    try:
        return float(str(v).replace(",", "")) if v not in (None, "", "–") else None
    except ValueError:
        return None


def compute(conn, issuer_id, cutoff: datetime, rev: Optional[float], growth_pct, order_book: Optional[list[dict]],
            mode: str = "PUBLIC_INFORMATION") -> dict:
    """The packet's order_flow block. rev: current TTM revenue (INR crore) or None; growth_pct: TTM revenue growth %."""
    asof = cutoff.astimezone(IST).date() - timedelta(days=1)       # orders published before the cutoff day
    orders = order_inflow(conn, issuer_id, cutoff, mode)
    o12, prior = orders_12m(orders, asof, rev), orders_12m(orders, asof - timedelta(days=365), rev)
    usable = [x for x in order_book or [] if x.get("quarter_end") and (not x.get("book_doubtful") or not x.get("inflow_doubtful"))]
    lat = max(usable, key=lambda x: x["quarter_end"]) if usable else None       # the latest quarter, not the first listed
    book = _num(lat.get("book_yoy_pct")) if lat and not lat.get("book_doubtful") else None
    inflow = _num(lat.get("inflow_yoy_pct")) if lat and not lat.get("inflow_doubtful") else None
    growth = _num(growth_pct)
    cred = credibility(conn, issuer_id, cutoff)
    pc = lambda v: round(100 * v / rev, 1) if v and rev else None
    return dict(
        orders_12m_cr=round(o12, 1) if o12 else None, orders_12m_pct_rev=pc(o12),
        orders_prior_12m_cr=round(prior, 1) if prior else None, orders_prior_12m_pct_rev=pc(prior),
        ratio=(round(o12 / prior, 2) if o12 and prior else "prior none" if o12 else None),
        order_book_quarter=lat.get("quarter_end") if lat else None, book_yoy_pct=book, inflow_yoy_pct=inflow,
        ttm_revenue_cr=round(rev, 1) if rev else None, revenue_growth_ttm_pct=growth,
        credibility_flags=cred["flags"], pledge_pct=cred["pledge_pct"],
        not_available=["receivables days", "operating cash flow"] + ([] if cred["pledge_pct"] is not None else ["promoter pledge"]),
        status=status(o12, prior, rev, book, inflow, growth, cred["flags"]), note=BACKTEST_NOTE)
