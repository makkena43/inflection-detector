"""Building and rendering a triage packet, as pure functions (spec 5.3, 6, 15 tests 6, 7, 12).

``build`` takes what ``pipeline`` gathered at the shortlist's cutoff (every input already passed
the shared as-of predicate) and returns the packet content and its Markdown, fitted to the token
budget.  Cuts are made in a fixed order and each one is listed in the packet with how to get the
rest: earlier comparable passages go first (oldest first), then trigger passages beyond the first
two per event.  Contradicting evidence is never cut (spec 6: all known contradictory evidence).

Money is shown in INR crore (a presentation convention; the stored figures keep their own scale),
one statement scope per table (consolidated when the company files it, else standalone, never
mixed), and growth on a zero or negative base is left blank with the reason (``units.growth``).
Prices are unadjusted in the database; returns and highs/lows here are adjusted for splits and
bonuses with a known price multiplier, and left blank across one without.
"""

from __future__ import annotations

import hashlib
import json
import calendar
import math
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Optional

from ..asof import IST
from ..units import Money, Scale, growth, inr_base, finite_decimal
from ..periods import consecutive_quarters
from . import rules as R

PACKET_VERSION = "triage-packet-13" if R.WITH_VALUATION else "triage-packet-2"
SCHEMA_VERSION = "1"
TOKEN_BUDGET = 12_000                 # spec 5.3: initial packet target
CHARS_PER_TOKEN = 4                   # rough estimate for English and figures; stated in the packet
QUOTE_CHARS = 700                     # longer passages are cut; the page is retrievable
TRIGGER_KEEP_PER_EVENT = 2            # when over budget, trigger passages kept per event
QUARTERS, YEARS = 8, 3
MAX_PAGES_PER_RETRIEVAL = 5           # the bounded retrieval pass (spec 5.3)
SNAPSHOT_METRICS = ("revenue", "other_income", "total_expenses", "finance_cost", "depreciation", "pbt",
                    "exceptional_items", "pat", "pat_owners", "eps_diluted")
SHARE_METRICS = ("paid_up_capital", "face_value")
MAX_PRICE_TO_SALES = 500               # beyond this the inputs are in the wrong unit
PRICE_JUMP = Decimal("3.5")      # a one-day close ratio beyond this without a recorded action
SHARE_JUMP = Decimal(25)              # a year's share-count change beyond this factor is a unit error, not dilution
ACTIONS = ("DEEP_RESEARCH", "WATCH_MILESTONE", "REJECT_WITH_REASON", "DATA_REPAIR", "DEFER_BUDGET")
STAGES = ("AMBITION", "FUNDED_PLAN", "QUALIFIED", "BINDING_DEMAND", "COMMERCIAL_SHIPMENT", "REPEAT_SHIPMENT",
          "CANCELLED", "UNKNOWN")
RETURN_FIELDS = ("issuer_id", "as_of", "event_ids", "mechanism", "what_changed", "commercial_stage",
                 "materiality_status", "next_milestone", "funding_status", "contradictions",
                 "missing_information", "evidence_refs", "size_pct_of_revenue", "size_basis", "firm", "routine",
                 "disqualifier", "pass_through", "triage_action", "confidence", "rationale", "triage_rules_version")


def estimate_tokens(text: str) -> int:
    return math.ceil(len(text) / CHARS_PER_TOKEN)


def content_hash(content: dict) -> str:
    return hashlib.sha256(json.dumps(content, sort_keys=True, default=str).encode()).hexdigest()


def utc(ts: Optional[datetime]) -> Optional[str]:
    """Timestamps in the packet are stored in UTC, so its hash does not depend on the session time zone."""
    return None if ts is None else ts.astimezone(timezone.utc).isoformat()


def ist(ts) -> Optional[str]:
    if ts is None:
        return None
    if isinstance(ts, str):
        ts = datetime.fromisoformat(ts)
    return ts.astimezone(IST).strftime("%Y-%m-%d %H:%M IST")


def _crore(value: Optional[Decimal], currency: Optional[str], scale: Optional[str]) -> Optional[Decimal]:
    amount=inr_base(value,currency,scale)
    return amount/Scale.CRORE.factor if amount is not None else None


def _fmt(d: Optional[Decimal], places: int = 1) -> Optional[str]:
    return None if d is None else f"{d:,.{places}f}"


# ---------------------------------------------------------------- financial snapshot

def financial_snapshot(facts: list[dict], cutoff: Optional[datetime] = None) -> dict:
    """The latest eight quarters and three years in one scope, with year-on-year growth, trailing
    twelve months and the share count.  ``facts`` holds, per (metric, period type, period end,
    scope), the latest version public by the cutoff."""
    if cutoff is not None:
        day=cutoff.astimezone(IST).date()
        facts=[f for f in facts if f['period_end']<=day and f.get('available_at') is not None
               and f['available_at']<=cutoff]
    quarter_scopes = {f["scope"] for f in facts if f["period_type"] == "QUARTER"}
    any_scopes = {f["scope"] for f in facts}
    if not any_scopes:
        return dict(status="MISSING", reason="no results figures public by the cutoff")
    scope = "CONSOLIDATED" if "CONSOLIDATED" in (quarter_scopes or any_scopes) else "STANDALONE"
    mine = [f for f in facts if f["scope"] == scope]
    at = {(f["metric"], f["period_type"], f["period_end"]): f for f in mine}
    quarters = sorted({f["period_end"] for f in mine if f["period_type"] == "QUARTER"})[-QUARTERS:]
    years = sorted({f["period_end"] for f in mine if f["period_type"] == "ANNUAL"})[-YEARS:]

    def cell(metric, ptype, end) -> dict:
        f = at.get((metric, ptype, end))
        if f is None:
            return dict(value=None, why="not in any filing public by the cutoff")
        if f["value"] is None:
            return dict(value=None, why=f["missing_reason"])
        expected='PER_SHARE' if metric in ('eps_diluted','eps_basic','face_value') else 'MONEY'
        if f['value_kind']!=expected:
            return dict(value=None,why='source value has the wrong unit kind for this metric')
        if f["value_kind"] == "MONEY":
            value=_crore(f['value'],f['currency'],f['scale'])
        else:
            value=finite_decimal(f['value']) if f['value_kind']=='PER_SHARE' and f['currency']=='INR' and f.get('scale') in (None,'UNITS') else None
        return dict(value=_fmt(value,2),publication_id=str(f["publication_id"]) if f.get("publication_id") else None,**({'why':'currency, scale or numeric value is not proved for INR arithmetic'} if value is None else {}))

    def money(metric, ptype, end) -> Optional[Money]:
        f = at.get((metric, ptype, end))
        if f is None or f["value"] is None or f["value_kind"] != "MONEY":
            return None
        value=inr_base(f['value'],f['currency'],f['scale'],f['value_kind'])
        return Money(value,'INR',Scale.UNITS) if value is not None else None

    def year_before(end: date) -> Optional[date]:
        for q in quarters + sorted({f["period_end"] for f in mine if f["period_type"] == "QUARTER"}):
            if (q.year, q.month) == (end.year - 1, end.month):
                return q
        return None

    def yoy(metric: str) -> list[dict]:
        out = []
        for end in quarters:
            prev = year_before(end)
            cur, base = money(metric, "QUARTER", end), money(metric, "QUARTER", prev) if prev else None
            if cur is None or base is None:
                out.append(dict(value=None, why="no same quarter a year earlier" if cur else "figure missing"))
                continue
            g = growth(cur, base)
            out.append(dict(value=_fmt(g.pct, 1), why=None if g.pct is not None else g.reason))
        return out

    def quarter_ttm(metric: str) -> dict:
        last = quarters[-4:]
        if not consecutive_quarters(last):
            return dict(value=None, why="four consecutive quarters not available")
        vals = [money(metric, "QUARTER", q) for q in last]
        if any(v is None for v in vals):
            return dict(value=None, why="a quarter's figure is missing")
        return dict(value=_fmt(sum(v.to(Scale.CRORE).value for v in vals), 2), period_end=last[-1].isoformat())

    # The company's own fiscal year (most Indian companies close in March; Castrol and others in December)
    fy_months = Counter(f["period_end"].month for f in mine if f["period_type"] == "ANNUAL")
    fy_month = fy_months.most_common(1)[0][0] if fy_months else 3

    def ytd_ttm(metric: str) -> Optional[dict]:
        """Latest year-to-date figure + the prior full year - the same year-to-date a year earlier:
        half-yearly filers never have four quarters."""
        after = lambda n: (fy_month + n - 1) % 12 + 1           # noqa: E731  month n months after the year end
        ytd = {after(3): "QUARTER", after(6): "HALF_YEAR", after(9): "NINE_MONTHS", fy_month: "ANNUAL"}
        ends = sorted({f["period_end"] for f in mine if f["metric"] == metric and ytd.get(f["period_end"].month) ==
                       f["period_type"]}, reverse=True)
        for end in ends:
            cur = money(metric, ytd[end.month], end)
            if cur is None:
                continue
            if end.month == fy_month:
                return dict(value=_fmt(cur.to(Scale.CRORE).value, 2), period_end=end.isoformat(), basis="full year")
            fy_year = end.year if end.month > fy_month else end.year - 1
            fy_end = date(fy_year, fy_month, calendar.monthrange(fy_year, fy_month)[1])
            year_ago = date(end.year - 1, end.month, calendar.monthrange(end.year - 1, end.month)[1])
            annual, base = money(metric, "ANNUAL", fy_end), money(metric, ytd[end.month], year_ago)
            if annual is not None and base is not None:
                v = cur.to(Scale.CRORE).value + annual.to(Scale.CRORE).value - base.to(Scale.CRORE).value
                return dict(value=_fmt(v, 2), period_end=end.isoformat(), basis="year to date + prior full year "
                            "- same period a year earlier")
        return None

    def ttm(metric: str) -> dict:
        q = quarter_ttm(metric)
        if q.get("value") is None and q.get("why") != "four consecutive quarters not available":
            return q                                 # a missing or unproved quarter is not papered over
        y = ytd_ttm(metric)
        if y and (q.get("value") is None or y["period_end"] > q["period_end"]):
            return y
        return q

    shares = _shares(mine, at)
    pubs = sorted({str(f["publication_id"]) for f in mine if f["publication_id"] and
                   f["period_end"] in set(quarters) | set(years)})
    result = dict(
        status="FOUND", scope=scope, other_scope_available=sorted(any_scopes - {scope}),
        unit="INR crore; eps in INR per share",
        quarters=[q.isoformat() for q in quarters],
        rows={m: [cell(m, "QUARTER", q) for q in quarters] for m in SNAPSHOT_METRICS},
        yoy={m: yoy(m) for m in ("revenue", "pat")},
        ttm={m: ttm(m) for m in ("revenue", "pat")},
        years=[y.isoformat() for y in years],
        annual={m: [cell(m, "ANNUAL", y) for y in years] for m in ("revenue", "pat", "eps_diluted")},
        shares=shares, publication_ids=pubs,
        latest_available_at=utc(max(f["available_at"] for f in mine)))
    if cutoff is not None:
        from ..freshness import revenue_basis
        basis=revenue_basis(result,cutoff)
        result['freshness']={k:v for k,v in basis.items() if k!='value'}
    return result


def _shares(mine: list[dict], at: dict) -> dict:
    """Share count from paid-up capital / face value in the latest filing that has both, and the
    change against a year earlier (a dilution check)."""
    periods = ("QUARTER", "ANNUAL")
    counts = {}
    for end in sorted({f["period_end"] for f in mine if f["metric"] == "paid_up_capital"}):
        for ptype in periods:
            cap, fv = (at.get((m, ptype, end)) for m in ('paid_up_capital', 'face_value'))
            if (not cap or not fv or not cap.get('publication_id')
                    or cap.get('publication_id') != fv.get('publication_id')):
                continue
            if (finite_decimal(cap['value']) is None or finite_decimal(fv['value']) is None
                    or cap.get('value_kind')!='MONEY' or fv.get('value_kind')!='PER_SHARE'
                    or cap.get('scale') not in Scale._value2member_map_ or fv.get('scale') not in (None,'UNITS')
                    or cap['value'] <= 0 or fv['value'] <= 0
                    or not cap.get('currency') or cap.get('currency') != fv.get('currency')):
                continue
            counts[end] = Money(Decimal(cap['value']), cap['currency'] or 'INR', Scale(cap['scale'])).to_base() / Decimal(fv['value'])
            break
    if not counts:
        return dict(value=None, why="paid-up capital or face value not filed")
    end = max(counts)
    prior = [e for e in counts if 330 <= (end - e).days <= 400]
    out = dict(value=_fmt(counts[end] / Decimal(10) ** 7, 3), unit="crore shares", period_end=end.isoformat(),
               base=counts[end])
    if prior:
        p = max(prior)
        if counts[p]:                                   # a zero share count (bad filing) gives no change, not a crash
            out["change_pct_vs_year_earlier"] = _fmt((counts[end] / counts[p] - 1) * 100, 1)
            ratio = counts[end] / counts[p]
            if not Decimal(1) / SHARE_JUMP <= ratio <= SHARE_JUMP:
                # No split or bonus moves a share count this far: paid-up capital filed in the wrong unit
                # (11,710,800,000,000 rupees for an 11.7 crore capital) would give a market cap 100,000x too large.
                return dict(value=None, why=f"paid-up capital implies {_fmt(ratio, 0)}x the share count of a year "
                            "earlier; likely a filing unit error", period_end=end.isoformat())
    return out


# ---------------------------------------------------------------- price and liquidity

def price_summary(prices: list[tuple], actions: list[dict], cutoff_day: date,
                  shares: Optional[Decimal] = None, shares_asof: Optional[date] = None) -> dict:
    """``prices``: (trade date, close, volume) public by the cutoff, any order.  ``actions``: splits,
    bonuses and other actions on the same security (kind, ex_date, multiplier or None, subject)."""
    rows = sorted((d, Decimal(c), Decimal(v) if v is not None else None) for d, c, v in prices
                  if c is not None and d<=cutoff_day and Decimal(c)>0)
    acts = sorted(actions, key=lambda a: a["ex_date"])
    listed = [dict(kind=a["kind"], ex_date=a["ex_date"].isoformat(), subject=a.get("subject"),
                   price_multiplier=str(a["multiplier"]) if a.get("multiplier") is not None else None)
              for a in acts if a["ex_date"] <= cutoff_day and a["ex_date"] > cutoff_day - timedelta(days=400)]
    if not rows:
        return dict(status="MISSING", reason="no prices public by the cutoff", corporate_actions=listed)
    last_d, last_c, _ = rows[-1]
    adjusting = [a for a in acts if a["kind"] in ("SPLIT", "BONUS") and a["ex_date"] <= last_d]

    def factor(d: date) -> Optional[Decimal]:
        f = Decimal(1)
        for a in adjusting:
            if d < a["ex_date"]:
                if a.get("multiplier") is None or a.get("reconciled") is False or Decimal(a["multiplier"])<=0:
                    return None
                f *= Decimal(a["multiplier"])
        return f

    def adj(d: date, c: Decimal) -> Optional[Decimal]:
        f = factor(d)
        return None if f is None else c * f

    def on_or_before(d: date):
        best = None
        for r in rows:
            if r[0] > d:
                break
            best = r
        return best

    # A one-day move of this size with no recorded split or bonus is an unrecorded action (Remsons' July
    # 2024 split took 999 to 187): returns, highs and lows across it would be wrong, so none are given.
    known = {a["ex_date"] for a in acts if a["kind"] in ("SPLIT", "BONUS")}
    jumps = [d for (_, c0, _), (d, c1, _) in zip(rows, rows[1:])
             if d > last_d - timedelta(days=400) and (c0 / c1 >= PRICE_JUMP or c1 / c0 >= PRICE_JUMP)
             and not any(abs((d - k).days) <= 3 for k in known)]
    if jumps:
        adjusting = adjusting + [dict(kind="UNRECORDED", ex_date=jumps[-1], multiplier=None)]
    returns = {}
    for label, days in (("1m", 30), ("3m", 91), ("6m", 182), ("12m", 365)):
        r = on_or_before(last_d - timedelta(days=days))
        if r is None or (last_d-timedelta(days=days)-r[0]).days>7:
            returns[label] = dict(value=None, why="no price that far back")
            continue
        base = adj(r[0], r[1])
        returns[label] = dict(value=_fmt((last_c / base - 1) * 100, 1), since=r[0].isoformat()) if base \
            else dict(value=None, why="a split or bonus in between has no known price multiplier")
    year = [(d, adj(d, c)) for d, c, _ in rows if d > last_d - timedelta(days=365)]
    known = [x for _, x in year if x is not None]
    hi_lo = dict(high=_fmt(max(known), 2), low=_fmt(min(known), 2)) if known and len(known) == len(year) \
        else dict(high=None, low=None, why="a split or bonus in the year has no known price multiplier")
    recent = [(c, v) for d, c, v in rows if d > last_d - timedelta(days=91)]
    traded = [c * v for c, v in recent if v is not None]
    months: dict = {}
    for d, c, _ in rows:
        if d > last_d - timedelta(days=400):
            months[f"{d.year}-{d.month:02d}"] = (d, c)
    monthly = [dict(month=k, close=_fmt(adj(d, c), 2)) for k, (d, c) in sorted(months.items())][-13:]
    stale_days = (cutoff_day - last_d).days
    out = dict(status="FOUND" if stale_days <= 7 else "STALE", last_close=_fmt(last_c, 2), last_date=last_d.isoformat(),
               days_before_cutoff=stale_days, returns_pct=returns, high_low_52w=hi_lo,
               avg_daily_traded_value_cr_3m=_fmt(sum(traded) / len(traded) / Decimal(10) ** 7, 2) if traded else None,
               trading_days_3m=len(recent), monthly_closes=monthly, corporate_actions=listed,
               adjustment="unadjusted closes; returns, highs and lows adjusted for splits and bonuses"
               + (f"; a {PRICE_JUMP}x one-day move on {jumps[-1].isoformat()} has no recorded split or bonus, so "
                  "returns, highs and lows across it are not given" if jumps else ""))
    if shares and shares_asof:
        from ..freshness import period_age, QUARTER_MAX_AGE_DAYS
        status,_=period_age(shares_asof,cutoff_day,QUARTER_MAX_AGE_DAYS)
        if status!='CURRENT':shares=None
        else:
            for a in adjusting:
                if shares_asof<a['ex_date']:
                    m=a.get('multiplier')
                    if not m or Decimal(m)<=0 or a.get('reconciled') is False:
                        shares=None;break
                    shares/=Decimal(m)
    if shares and out['status']=='FOUND':
        out["market_cap_cr"] = _fmt(shares * last_c / Decimal(10) ** 7, 0)
    return out


def valuation(fin: dict, price: dict) -> dict:
    """P/S (market cap / TTM revenue), TTM operating margin and its change on a year earlier, TTM revenue growth.
    Operating profit = revenue - total expenses + finance cost + depreciation, matching financial nominations."""
    if fin.get("status") != "FOUND":
        return dict(status="MISSING", reason="no financial snapshot")
    def num(v):
        try:
            value = Decimal(str(v).replace(",", "")) if v not in (None, "", "–", "-") else None
            return value if value is not None and value.is_finite() else None
        except InvalidOperation:
            return None

    def col(metric):
        return [num(c.get("value")) for c in fin["rows"].get(metric, [])]
    rev, expenses, fc, dep = (col(m) for m in ("revenue", "total_expenses", "finance_cost", "depreciation"))
    ends = [date.fromisoformat(q) for q in fin.get('quarters', [])]
    def ttm_opm(sl):
        if not consecutive_quarters(ends[sl]):
            return None, None
        revenues = rev[sl]
        r = sum(revenues) if len(revenues) == 4 and all(v is not None for v in revenues) else None
        q = list(zip(*(x[sl] for x in (rev, expenses, fc, dep))))
        if len(q) < 4 or any(None in t for t in q):
            return None, r
        sources=[fin['rows'].get(m,[])[sl] for m in ('revenue','total_expenses','finance_cost','depreciation')]
        if any(len(cells)!=4 for cells in sources):return None,r
        for cells in zip(*sources):
            pubs={cell.get('publication_id') for cell in cells}
            if None in pubs or len(pubs)!=1:return None,r
        op = sum(t[0] - t[1] + t[2] + t[3] for t in q)
        return (op / r if r else None), r
    now, r_now = ttm_opm(slice(-4, None))
    before, r_before = ttm_opm(slice(-8, -4)) if consecutive_quarters(ends[-8:], 8) else (None, None)
    freshness=fin.get('freshness') or {}
    if freshness.get('freshness') in ('STALE','FUTURE','UNKNOWN','MISSING'):
        return dict(status=freshness.get('freshness'),reason='financial reporting period is not current at cutoff')
    mcap = num(price.get("market_cap_cr")) if price.get('status')=='FOUND' else None
    if r_now is None and (fin.get('ttm') or {}).get('revenue', {}).get('basis'):
        r_now = num(fin['ttm']['revenue'].get('value'))   # half-yearly filer: year-to-date trailing revenue
    if mcap and r_now and mcap / r_now > MAX_PRICE_TO_SALES:
        # 14,330,606 crore on 104 crore of revenue: a share count or price in the wrong unit, not a valuation
        return dict(status="DOUBTFUL", reason=f"market cap {_fmt(mcap, 0)} crore is over {MAX_PRICE_TO_SALES}x TTM "
                    f"revenue of {_fmt(r_now, 2)} crore; share count or price unit needs checking",
                    ttm_revenue_cr=_fmt(r_now, 2))
    return dict(status="FOUND",
                price_to_sales=_fmt(mcap / r_now, 2) if mcap and r_now else None,
                market_cap_cr=_fmt(mcap, 0) if mcap else None, ttm_revenue_cr=_fmt(r_now, 2) if r_now else None,
                opm_ttm_pct=_fmt(now * 100, 1) if now is not None else None,
                opm_change_pts=_fmt((now - before) * 100, 1) if now is not None and before is not None else None,
                revenue_growth_ttm_pct=_fmt((r_now / r_before - 1) * 100, 1) if r_now is not None and r_before is not None and r_before > 0 else None,
                note="computed from the financial snapshot and the last close; operating margin = revenue + finance cost "
                     "+ depreciation, minus total expenses, over revenue")


# ---------------------------------------------------------------- risk flags

def risk_flags(item: dict, evaluations: list[dict], events: list[dict], documents: list[dict], fin: dict,
               price: dict, contradictions: list[dict]) -> list[dict]:
    flags: list[dict] = []

    def add(flag: str, detail: str):
        if not any(f["flag"] == flag and f["detail"] == detail for f in flags):
            flags.append(dict(flag=flag, detail=detail))

    if item["slot"] == "UPDATE":
        add("OPEN_CASE", "the company has an open research case; this is an update to it")
    if not item.get("has_symbol", True):
        add("NO_SYMBOL", "no exchange symbol on record; check the security still trades")
    if item.get("stale"):
        add("STALE_UNRESEARCHED", "waiting past the stale limit; check the catalyst still holds")
    for e in events:
        label = f"{e['event_type']} {e['stage']}" + (f" ({e['counterparty']})" if e.get("counterparty") else "")
        if e.get("relationship") == "CONFIRMED_RELATED" or e.get("ownership_scope") in ("SUBSIDIARY", "JOINT_VENTURE",
                                                                                        "ASSOCIATE"):
            add("RELATED_OR_GROUP", f"{label}: counterparty {e.get('relationship') or 'UNKNOWN'}, "
                                    f"ownership {e.get('ownership_scope')}")
        if e.get("amount_basis") in ("CEILING", "NON_BINDING"):
            add("NOT_FIRM_AMOUNT", f"{label}: amount basis {e['amount_basis']} (not committed revenue)")
        if e.get("observation_status") == "FORECAST":
            add("FORECAST_ONLY", f"{label}: management expectation, not an observed event")
        if e.get("contradiction_status") not in (None, "NONE_KNOWN"):
            add("CONTRADICTED", f"{label}: {e['contradiction_status']}")
        if e.get("stage") == "CANCELLED":
            add("CANCELLED", f"{label}: cancelled")
    if contradictions:
        add("CONTRADICTING_EVIDENCE", f"{len(contradictions)} contradicting passage(s) below")
    for ev in evaluations:
        c = ev.get("components") or {}
        if c.get("equity_financing_within_lookback"):
            add("EQUITY_FINANCING", "equity raised within the lookback; check dilution and use of funds")
        for note in c.get("cautions") or []:
            add("FINANCIAL_CAUTION", note)
        for name in c.get("unverified") or []:
            add("UNVERIFIED_CHECK", f"{name}: inputs failed the statement arithmetic")
        if (ev.get("coverage") or {}).get("revenue") == "MISSING":
            add("MATERIALITY_UNKNOWN", "no annual revenue public by then; materiality not measured")
        if ev.get("priority") == "D":
            add("DATA_REPAIR", ev["reason"])
    for d in documents:
        if d.get("text_status") and d["text_status"] != "COMPLETE":
            add("TEXT_INCOMPLETE", f"{d.get('title') or d['publication_id']}: text {d['text_status']}"
                                   + (f", missing pages {d['missing_pages']}" if d.get("missing_pages") else ""))
    if fin.get("status") != "FOUND":
        add("NO_FINANCIALS", fin.get("reason", "no results figures"))
    else:
        if fin["other_scope_available"] and fin["scope"] == "STANDALONE":
            add("SCOPE", "standalone figures shown; consolidated exists for other periods only")
        pat = fin["ttm"]["pat"].get("value")
        if pat is not None and Decimal(pat.replace(",", "")) < 0:
            add("LOSS_MAKING", f"trailing twelve-month PAT INR {pat} crore")
        chg = fin["shares"].get("change_pct_vs_year_earlier")
        if chg is not None and Decimal(chg.replace(",", "")) > 5:
            add("DILUTION", f"share count up {chg}% against a year earlier")
    if price.get("status") == "MISSING":
        add("NO_PRICES", price["reason"])
    elif price.get("status") == "STALE":
        add("PRICE_STALE", f"last trade {price['last_date']}, {price['days_before_cutoff']} days before the cutoff")
    if price.get("status") != "MISSING":
        if any(a["kind"] in ("SPLIT", "BONUS") and a["price_multiplier"] is None for a in price["corporate_actions"]):
            add("UNADJUSTED_ACTION", "a split or bonus without a known price multiplier; returns across it are blank")
        tv = price.get("avg_daily_traded_value_cr_3m")
        if tv is not None and Decimal(tv.replace(",", "")) < Decimal("0.5"):
            add("ILLIQUID", f"average daily traded value INR {tv} crore over three months")
    return flags


# ---------------------------------------------------------------- packet

def _passage(p: dict) -> dict:
    q = p["quote"]
    out = {k: p[k] for k in ("evidence_id", "event_id", "version_no", "event_type", "stage", "relation",
                             "assertion_type", "title", "source_url", "page_no", "text_artifact_id",
                             "document_version_id", "publication_id")}
    out["published_at"] = ist(p["published_at"])
    if len(q) > QUOTE_CHARS:
        out["quote"] = q[:QUOTE_CHARS].rstrip() + f" ...[cut {len(q) - QUOTE_CHARS} characters; read page {p['page_no']}]"
    else:
        out["quote"] = q
    return out


def evaluation_summaries(evaluations):
    return [dict(route=e['route'],as_of=ist(e['as_of']),priority=e['priority'],outcome=e['outcome'],
                 reasons=e['reasons'],detail=_why(e),fired=(e.get('components') or {}).get('fired',[]),
                 unverified=(e.get('components') or {}).get('unverified',[])) for e in evaluations]


def build(head: dict, identity: dict, evaluations: list[dict], prior_triage: Optional[dict], events: list[dict],
          passages: list[dict], documents: list[dict], fin: dict, price: dict, excluded: dict,
          budget: int = TOKEN_BUDGET, order_book: Optional[list[dict]] = None,
          ownership: Optional[dict] = None, order_flow: Optional[dict] = None) -> tuple[dict, str]:
    """(content, markdown).  ``passages`` carry kind TRIGGER, CONTRADICTS or PRIOR, newest first."""
    trig = [_passage(p) for p in passages if p["kind"] == "TRIGGER"]
    contra = [_passage(p) for p in passages if p["kind"] == "CONTRADICTS"]
    prior = [_passage(p) for p in passages if p["kind"] == "PRIOR"]
    flags = risk_flags(head, evaluations, events, documents, fin, price, contra)
    missing = list(head.get('nomination_issues') or [])
    if not trig and any(e["route"] == "COMMERCIAL" for e in evaluations):
        missing.append("trigger passages: none public by the cutoff for the trigger events")
    if any(e["route"] == "COMMERCIAL" for e in evaluations) and not any(d.get("text_artifact_id") for d in documents):
        missing.append("trigger document text: none on record")
    if fin.get("status") != "FOUND":
        missing.append(f"financial snapshot: {fin.get('reason')}")
    if price.get("status") == "MISSING":
        missing.append(f"price: {price.get('reason')}")
    for reason, n in sorted(excluded.items()):
        missing.append(f"{n} passage(s) left out by the as-of check: {reason}")
    content = dict(
        manifest=dict(packet_version=PACKET_VERSION, schema_version=SCHEMA_VERSION,
                      cutoff=utc(head["cutoff"]), cutoff_ist=ist(head["cutoff"]), mode=head["mode"],
                      week_start=head["week_start"].isoformat(), shortlist_policy=head["policy_version"],
                      shortlist_policy_hash=head.get("policy_hash"),
                      slot=head["slot"], position=head["position"], priority=head["priority"],
                      evaluation_ids=sorted(str(e["evaluation_id"]) for e in evaluations),
                      nomination_status='VERIFICATION_REQUIRED' if head.get('nomination_issues') else 'CONSISTENT',
                      nomination_issues=head.get('nomination_issues') or [],
                      sources=sorted(({k: d.get(k) for k in ("publication_id", "document_version_id","text_artifact_id","sha256", "text_sha256")}
                                      for d in documents), key=lambda d: (d['publication_id'],d.get('document_version_id') or '',d.get('text_artifact_id') or '')),
                      token_budget=budget, token_estimate=None, token_rule=f"characters / {CHARS_PER_TOKEN}",
                      completeness=None, missing_evidence=missing, truncation=[]),
        company=identity,
        why_now=dict(reason=head["reason"], note=head.get("note"), corroborated=head.get("corroborated", False),
                     waiting_since=ist(head["waiting_since"]), prior_triage=prior_triage,
                     evaluations=evaluation_summaries(evaluations)),
        risk_flags=flags, events=events, trigger_passages=trig, contradicting_passages=contra,
        prior_passages=prior, documents=documents, financials=fin, price=price,
        **({"valuation": valuation(fin, price), "order_book": order_book or []} if R.WITH_VALUATION else {}),
        **({"ownership": ownership or {}} if R.WITH_SOURCES else {}),
        **({"order_flow": order_flow or {}} if R.WITH_ORDER_FLOW else {}))


    def fits() -> bool:
        return estimate_tokens(render(content)) <= budget

    keep = len(prior)
    while keep > 0 and not fits():
        keep -= max(1, keep // 10)
        content["prior_passages"] = prior[:keep]
        content["manifest"]["truncation"] = _cuts(prior, keep, trig, trig)
    if not fits():
        kept, per = [], {}
        for p in trig:
            per[p["event_id"]] = per.get(p["event_id"], 0) + 1
            if per[p["event_id"]] <= TRIGGER_KEEP_PER_EVENT:
                kept.append(p)
        content["trigger_passages"] = kept
        content["manifest"]["truncation"] = _cuts(prior, keep, kept, trig)
    if not fits():
        content["manifest"]["truncation"].append(dict(
            section="packet", omitted=0, note="still over the token budget after the cuts; contradicting "
                                              "evidence, the snapshot and the price summary are never cut"))
    gaps = missing or content["manifest"]["truncation"]
    content["manifest"]["completeness"] = ("COMPLETE" if not gaps else
                                           "PARTIAL" if trig or fin.get("status") == "FOUND" else "MINIMAL")
    md = render(content)
    content["manifest"]["token_estimate"] = estimate_tokens(md)
    return content, md


def _cuts(prior: list, kept_prior: int, kept_trig: Optional[list], trig: list) -> list[dict]:
    out = []
    if kept_prior < len(prior):
        dropped = prior[kept_prior:]
        out.append(dict(section="prior_passages", omitted=len(dropped),
                        note=f"older comparable passages from {dropped[-1]['published_at']} to "
                             f"{dropped[0]['published_at']}; read with the page command",
                        pages=sorted({(p["text_artifact_id"], p["page_no"]) for p in dropped})))
    if kept_trig is not None and len(kept_trig) < len(trig):
        dropped = [p for p in trig if p not in kept_trig]
        out.append(dict(section="trigger_passages", omitted=len(dropped),
                        note=f"kept the first {TRIGGER_KEEP_PER_EVENT} per event; read the rest with the page command",
                        pages=sorted({(p["text_artifact_id"], p["page_no"]) for p in dropped})))
    return out


def _why(e: dict) -> list[str]:
    """One line per commercial event or fired financial check in an evaluation."""
    c = e.get("components") or {}
    out = []
    for ev in c.get("events") or []:
        amt = " ".join(ev["amount"]) if ev.get("amount") else "unquantified"
        out.append(f"{ev['event_type']} {ev['stage']} (was {ev.get('previous_stage') or 'none'}, {ev.get('novelty')}); "
                   f"{amt} {ev.get('basis') or ''}; counterparty {ev.get('counterparty') or 'unnamed'} "
                   f"[{ev.get('relationship')}]; materiality {ev.get('materiality')}: {ev.get('materiality_reason')}"
                   + (f"; milestone {ev['milestone']}" if ev.get("milestone") else ""))
    for ch in c.get("checks") or []:
        if ch.get("status") == "FIRED":
            out.append(f"{ch.get('name')}: {ch.get('detail') or ch.get('reason') or ''}".strip())
    if c.get("without_mechanism"):
        out.append("no commercial event explains: " + ", ".join(c["without_mechanism"]))
    return out


# ---------------------------------------------------------------- markdown

def amount_cell(e: dict) -> str:
    """An event amount as read: rupee units in crore, and a tax-inclusive value with its estimated net."""
    raw = e.get("amount")
    if not raw:
        return "–"
    parts = raw.split()
    try:
        value = Decimal(parts[0]) if len(parts) == 3 else None
    except InvalidOperation:
        value = None
    crore = _crore(value, parts[1], parts[2]) if value is not None and parts[1] == "INR" else None
    text = raw
    if crore is not None and parts[2] != "CRORE":
        text = f"{_fmt(crore, 2)} INR CRORE ({raw})"
    fx = (e.get("details") or {}).get("fx") or {}
    if fx.get("status") == "CONVERTED":
        crore = Decimal(fx["inr_crore"])
        text = (f"{_fmt(crore, 2)} INR CRORE ({raw} at {fx['rate']} INR per {fx['currency']}, "
                f"reference rate of {fx['rate_date']})")
    elif fx.get("status") == "NO_DATED_RATE":
        text = f"{raw} (no dated {fx['currency']} rate; not converted)"
    details = e.get("details") or {}
    if details.get("size_needs_filing"):
        text += " (stated only on a call or in a deck, over 10x annual revenue; needs a filing)"
    if details.get("duplicate_of"):
        text += f" (same disclosure as event {str(details['duplicate_of'])[:8]})"
    if (e.get("details") or {}).get("tax_basis") == "INCLUSIVE":
        from ..commercial.vocabulary import GST_ASSUMED_RATE
        rate = Decimal(GST_ASSUMED_RATE)
        net = f"; about {_fmt(crore / (1 + rate), 2)} INR CRORE net at an assumed {rate * 100:.0f}% GST" if crore else ""
        text += f" incl. tax{net}"
    return text


def _table(header: list[str], rows: list[list]) -> list[str]:
    out = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    out += ["| " + " | ".join("" if v is None else str(v) for v in r) + " |" for r in rows]
    return out


def _cellv(c: dict) -> str:
    return c["value"] if c.get("value") is not None else "–"


def render(c: dict) -> str:
    m, co, w = c["manifest"], c["company"], c["why_now"]
    L = [f"# Triage packet: {co['name']} ({co['label']})", "",
         f"Cutoff {m['cutoff_ist']} ({m['mode']}). Week of {m['week_start']}, shortlist position {m['position']}, "
         f"slot {m['slot']}, class {m['priority']}. Packet {m['packet_version']}, completeness {m['completeness']}.",
         "", "Everything below was public by the cutoff. Nothing after it may be used.", ""]
    L += ["## Company", "",
          f"Issuer {co['issuer_id']}; ISIN {', '.join(co['isins']) or 'none'}; "
          f"symbols at the cutoff: {', '.join(co['symbols']) or 'none'}.", ""]
    L += ["## Why now", "", f"{w['reason']}" + (f" ({w['note']})" if w.get("note") else ""),
          f"Waiting since {w['waiting_since']}" + ("; financial change corroborated by a commercial event"
                                                  if w["corroborated"] else "") + "."]
    if w.get("prior_triage"):
        p = w["prior_triage"]
        L.append(f"Last triaged the week of {p['week_start']}: {p['action']}" + (f" ({p['note']})" if p.get("note") else ""))
    for e in w["evaluations"]:
        L.append(f"- {e['as_of']} {e['route']} {e['priority']} {e['outcome']}: {'; '.join(e['reasons'])}")
        L += [f"  - {d}" for d in e["detail"]]
    L.append("")
    L += ["## Risk flags", ""] + ([f"- {f['flag']}: {f['detail']}" for f in c["risk_flags"]] or ["None found."]) + [""]
    if c["events"]:
        L += ["## Trigger events", ""]
        L += _table(["event", "type", "stage (before)", "amount", "basis", "counterparty", "deadline", "contradiction"],
                    [[f"{e['event_id'][:8]} v{e['version_no']}", e["event_type"],
                      f"{e['stage']} ({e.get('previous_stage') or 'new'})", amount_cell(e), e["amount_basis"],
                      f"{e.get('counterparty') or 'unnamed'} [{e.get('relationship') or 'UNKNOWN'}]",
                      e.get("deadline") or "–", e["contradiction_status"]] for e in c["events"]]) + [""]
        fixes = (c.get("source_recheck") or {}).get("figure_corrections") or []
        if fixes:
            L += ["Source recheck: " + "; ".join(f"event {x['event_id'][:8]}'s {x['amount']} is {x.get('note') or x['kind']}"
                                                 for x in fixes) + ". These figures do not size any event.", ""]
    for title, key in (("Trigger passages", "trigger_passages"), ("Contradicting evidence", "contradicting_passages"),
                       ("Earlier comparable disclosures", "prior_passages")):
        L += [f"## {title}", ""]
        if not c[key]:
            L += ["None public by the cutoff.", ""]
        for p in c[key]:
            L += [f"[{p['evidence_id']}] {p['published_at']}, {p['title'] or 'filing'}, page {p['page_no']} "
                  f"({p['event_type']} {p['stage']}, {p['relation']}, {p['assertion_type']})",
                  f"> {p['quote']}", ""]
    f = c["financials"]
    L += ["## Financial snapshot", ""]
    if f.get("status") != "FOUND":
        L += [f"Missing: {f.get('reason')}.", ""]
    else:
        L.append(f"{f['scope'].capitalize()} figures, {f['unit']}. Latest filing public "
                 f"{ist(f['latest_available_at'])}." + (f" Also filed: {', '.join(f['other_scope_available']).lower()}."
                                                       if f["other_scope_available"] else ""))
        L.append("")
        L += _table(["quarter ending", *f["quarters"]],
                    [[k, *[_cellv(x) for x in v]] for k, v in f["rows"].items() if any(x.get("value") for x in v)]
                    + [[f"{k} YoY %", *[x["value"] if x["value"] is not None else "–" for x in v]]
                       for k, v in f["yoy"].items() if any(x.get("value") for x in f["rows"][k])])
        blank = sorted({x["why"] for k, v in f["yoy"].items() for x in v if x.get("value") is None and x.get("why")
                        and any(y.get("value") for y in f["rows"][k])})
        if blank:
            L.append(f"Blank growth: {'; '.join(blank)}.")
        basis = f['ttm']['revenue'].get('basis')
        L.append(f"Trailing twelve months{' to ' + f['ttm']['revenue']['period_end'] if f['ttm']['revenue'].get('period_end') else ''}"
                 f"{' (' + basis + ')' if basis else ''}: revenue {_cellv(f['ttm']['revenue'])}, PAT {_cellv(f['ttm']['pat'])}. "
                 f"Shares {f['shares'].get('value') or '–'} crore"
                 + (f" ({f['shares']['change_pct_vs_year_earlier']}% on a year earlier)"
                    if f["shares"].get("change_pct_vs_year_earlier") else "") + ".")
        if f["years"]:
            L += [""] + _table(["year ending", *f["years"]], [[k, *[_cellv(x) for x in v]] for k, v in f["annual"].items()])
        L.append("")
    p = c["price"]
    L += ["## Price and liquidity", ""]
    if p.get("status") == "MISSING":
        L += [f"Missing: {p.get('reason')}.", ""]
    else:
        r = p["returns_pct"]
        L += [f"Last close INR {p['last_close']} on {p['last_date']} ({p['days_before_cutoff']} days before the cutoff)"
              + (f", market cap about INR {p['market_cap_cr']} crore" if p.get("market_cap_cr") else "") + ".",
              "Returns: " + ", ".join(f"{k} {v['value'] + '%' if v['value'] else '– (' + v['why'] + ')'}"
                                      for k, v in r.items()) + ".",
              f"52-week high {p['high_low_52w'].get('high') or '–'}, low {p['high_low_52w'].get('low') or '–'}. "
              f"Average daily traded value INR {p['avg_daily_traded_value_cr_3m'] or '–'} crore over "
              f"{p['trading_days_3m']} trading days. {p['adjustment'].capitalize()}.",
              "Month-end closes: " + ", ".join(f"{x['month']} {x['close'] or '–'}" for x in p["monthly_closes"]) + "."]
        if p["corporate_actions"]:
            L.append("Corporate actions: " + "; ".join(
                f"{a['ex_date']} {a['kind']}" + (f" x{a['price_multiplier']}" if a["price_multiplier"] else "")
                for a in p["corporate_actions"]) + ".")
        L.append("")
    v = c.get("valuation")
    if v is not None:
        L += ["## Valuation and margin (computed)", ""]
        if v.get("status") != "FOUND":
            L += [f"Missing: {v.get('reason')}.", ""]
        else:
            L += [f"Price to sales (market cap / TTM revenue): {v['price_to_sales'] or '–'} "
                  f"(market cap INR {v['market_cap_cr'] or '–'} crore, TTM revenue INR {v['ttm_revenue_cr'] or '–'} crore). "
                  f"TTM operating margin {v['opm_ttm_pct'] or '–'}%"
                  + (f", {v['opm_change_pts']} points on a year earlier" if v['opm_change_pts'] else "")
                  + (f"; TTM revenue growth {v['revenue_growth_ttm_pct']}%" if v['revenue_growth_ttm_pct'] else "") + ".",
                  f"({v['note']}.)", ""]
    ob = c.get("order_book")
    if ob is not None:
        L += ["## Order book and order inflow (extracted from presentations and concalls)", ""]
        if not ob:
            L += ["None reported in documents public by the cutoff.", ""]
        else:
            L += _table(["quarter ending", "order book (INR crore)", "book YoY %", "order inflow (INR crore)", "inflow YoY %"],
                        [[x["quarter_end"], f"{x['order_book_cr'] or '–'}{' (doubtful)' if x.get('book_doubtful') else ''}",
                          x["book_yoy_pct"] if x["book_yoy_pct"] is not None else "–",
                          f"{x['order_inflow_cr'] or '–'}{' (doubtful)' if x.get('inflow_doubtful') else ''}",
                          x["inflow_yoy_pct"] if x["inflow_yoy_pct"] is not None else "–"] for x in ob])
            L += ["Figures are extracted by rules from company documents and may be a segment's book or a pipeline "
                  "('doubtful' = breaks sharply from the neighbouring quarters); use them as context for how normal the "
                  "trigger order is, not as a size. If you are making a DEEP_RESEARCH call, confirm the latest company-total "
                  "order book and quarterly order inflow from the documents and report them in order_book_check.", ""]
    L += order_flow_section(c["order_flow"]) if "order_flow" in c else []
    L += ownership_section(c.get("ownership")) if "ownership" in c else []
    L += ["## Full documents on demand", "",
          f"Read up to {MAX_PAGES_PER_RETRIEVAL} pages at a time, once, for context this packet lacks:",
          "`python -m inflection.packets page PACKET_ID TEXT_ARTIFACT_ID PAGES` (for example `3` or `2-4`).", ""]
    for d in c["documents"]:
        L.append(f"- {d.get('title') or d['category'] or 'filing'}, {ist(d['published_at']) or d.get('published_date')}: "
                 f"text {d.get('text_artifact_id') or 'none'}, {d.get('pages') or '?'} pages, "
                 f"text {d.get('text_status') or 'not extracted'}. {d['source_url']}")
    L += ["" if c["documents"] else "None.", ""]
    L += ["## Missing evidence and cuts", ""]
    L += [f"- {x}" for x in m["missing_evidence"]]
    L += [f"- {t['section']}: {t['omitted']} left out. {t['note']}" for t in m["truncation"]]
    if not m["missing_evidence"] and not m["truncation"]:
        L.append("None.")
    L += ["", "## Your task", "", f"Triage rules {R.TRIAGE_RULES_VERSION}.", "", R.RULES, "",
          f"Return JSON with exactly these fields: {', '.join(RETURN_FIELDS)}. "
          f"Keep issuer_id, as_of, packet_hash, event_ids and triage_rules_version as given."]
    return "\n".join(L) + "\n"


def order_flow_section(o: Optional[dict]) -> list[str]:
    """3.6.2 'Order flow (computed, context only)' section (inflection.orderflow)."""
    o = o or {}
    f = lambda v, s="": "–" if v is None else f"{v}{s}"
    if not o:
        return ["## Order flow (computed, context only)", "", "Not computed.", ""]
    ratio = o.get("ratio")
    return ["## Order flow (computed, context only)", "",
            f"Status: **{o.get('status', 'UNKNOWN')}**.", "",
            f"- Firm orders, last 12 months: INR {f(o.get('orders_12m_cr'))} crore ({f(o.get('orders_12m_pct_rev'), '%')} of TTM "
            f"revenue); prior 12 months: INR {f(o.get('orders_prior_12m_cr'))} crore ({f(o.get('orders_prior_12m_pct_rev'), '%')}); "
            f"ratio {ratio if isinstance(ratio, str) else f(ratio, 'x')}. Counted as the dashboard counts 12-month orders "
            "(repeats within 90 days once, stated period totals replace the orders they contain).",
            f"- Latest non-doubtful order book quarter {f(o.get('order_book_quarter'))}: book YoY {f(o.get('book_yoy_pct'), '%')}, "
            f"inflow YoY {f(o.get('inflow_yoy_pct'), '%')}. TTM revenue INR {f(o.get('ttm_revenue_cr'))} crore, growth "
            f"{f(o.get('revenue_growth_ttm_pct'), '%')}.",
            "- Credibility: " + ("; ".join(o.get("credibility_flags") or []) or "no auditor resignation or modified opinion in "
            "the prior year" + (f"; promoter pledge {o['pledge_pct']:.0f}%" if o.get("pledge_pct") is not None else ""))
            + ". Not available: " + ", ".join(o.get("not_available") or []) + ".",
            f"- {o.get('note', '')}", ""]


def ownership_section(o: Optional[dict]) -> list[str]:
    """Markdown for the 3.5 'Ownership and other signals' section: shareholding by quarter, PLI approvals, government
    programmes named in the company's filings, and capacity / production / rating / preferential / acquisition
    filings in the year before the cutoff."""
    o = o or {}
    f = lambda v: "–" if v is None else v
    L = ["## Ownership and other signals (context only)", ""]
    sh = o.get("shareholding") or []
    if sh:
        L += ["Shareholding pattern (% of shares; change on a year earlier in brackets):", ""]
        L += _table(["quarter ending", "promoter", "promoter pledged (% of promoter)", "mutual funds", "foreign inst.",
                     "domestic inst.", "retail (< Rs 2 lakh)"],
                    [[x["period_end"], f"{f(x['promoter_pct'])} ({f(x.get('promoter_chg_yoy'))})", f(x["promoter_pledged_pct"]),
                      f"{f(x['mf_pct'])} ({f(x.get('mf_chg_yoy'))})", f"{f(x['fii_pct'])} ({f(x.get('fii_chg_yoy'))})",
                      f(x["dii_pct"]), f(x["retail_pct"])] for x in sh])
    else:
        L += ["Shareholding pattern: none public by the cutoff in our data.", ""]
    pli = o.get("pli") or []
    L += (["PLI scheme approvals public by the cutoff:"] + [
        f"- {x['approval_date']}: {x['scheme']}{' ' + x['tranche'] if x.get('tranche') else ''}"
        + (f", committed investment INR {x['committed_investment_cr']} crore" if x.get("committed_investment_cr") else "")
        + (f", {x['product_segment']}" if x.get("product_segment") else "") + f". {x['source_url']}" for x in pli] + [""]
          if pli else ["PLI scheme approvals: none found for this company.", ""])
    pr = o.get("programmes") or []
    L += (["Government programmes (Rs 10,000 crore+ outlay) the company had named in its filings by the cutoff:", ""]
          + _table(["programme (announced, outlay INR crore)", "first mention", "first order mention", "documents (order)", "latest passage"],
                   [[f"{x['programme']} ({x['announced']}, {f(x['outlay_cr'])})", f(x["first_mention"]),
                     f(x["first_order_mention"]) + (" (early in the programme)" if x.get("early_cycle") else ""),
                     f"{x['documents']} ({x['order_documents']})", x["snippet"][:200]] for x in pr])
          if pr else ["Government programmes: the company's filings name none of the listed programmes by the cutoff.", ""])
    if "themes" in o:
        L += themes_section(o["themes"])
    if "theme_assessment" in o:
        L += theme_assessment_section(o["theme_assessment"])
    elif "emergent_themes" in o:
        L += emergent_section(o["emergent_themes"])
    sig = o.get("signal_filings") or []
    L += (["Capacity, production, rating, fund-raising and acquisition filings in the 12 months before the cutoff "
           "(read with the page command when they matter):"] + [
        f"- {x['published_at']} {x['category']}: {x.get('title') or ''} (text {x.get('text_artifact_id') or 'not extracted'})"
        for x in sig] + [""] if sig else ["Capacity, production, rating, fund-raising and acquisition filings: none in the 12 months before the cutoff.", ""])
    return L


SUPPLY_ROLE_LABEL = {"MAKER": "maker (manufacturing evidence)", "SUPPLIER": "supplier (evidenced)",
                     "EPC": "EPC contractor (own filings mostly EPC work)",
                     "MENTION_ONLY": "mention only (no maker/supplier evidence)"}


def themes_section(t: Optional[dict]) -> list[str]:
    """MakroGraph supply-gap themes: the company's rows in the newest theme snapshot on or before the cutoff."""
    t = t or {}
    rows = t.get("themes") or []
    if not t.get("snapshot"):
        return ["Supply-gap themes: no theme snapshot on or before the cutoff.", ""]
    if not rows:
        return [f"Supply-gap themes (snapshot {t['snapshot']}): the company is not a flagged supplier to any tracked "
                "supply gap.", ""]
    return ([f"Supply-gap themes (MakroGraph method, snapshot {t['snapshot']}; filings in the year before it showed "
             "capex / supply / demand language next to the product):", ""]
            + _table(["constrained product (theme)", "role", "evidenced company role", "conviction 0-1", "signals",
                      "order-book language", "import substitute", "flagged since (snapshots)"],
                     [[f"{x['product']} ({x['theme']})", x["role"], SUPPLY_ROLE_LABEL.get(x.get("company_role"), "–"),
                       f"{x['conviction']:.2f}", x["signals"],
                       "yes" if x["order_book"] else "no", "yes" if x["import_substitution"] else "no",
                       f"{x['first_flagged']} ({x['snapshots_flagged']})"] for x in rows]) + [""])


STAGE_LABEL = {0: "forming", 1: "emerging", 2: "accelerating", 3: "consensus", 4: "saturating", 5: "declining"}


ROLE_LABEL = {"MAKER": "maker", "SUPPLIER": "supplier", "EPC": "EPC contractor", "BUYER": "buyer/user"}


def theme_assessment_section(t: Optional[dict]) -> list[str]:
    """Computed theme assessment (inflection.themes.context): one row per theme the company is in, with a grade."""
    t = t or {}
    rows = t.get("themes") or []
    if not t.get("snapshot"):
        return ["Theme assessment: no theme snapshot on or before the cutoff.", ""]
    if not rows:
        return [f"Theme assessment (snapshot {t['snapshot']}): the company's order, capacity and launch passages of "
                "the last 180 days fall in no theme shared by 3+ companies. Theme grade: NONE.", ""]
    f = lambda v: "–" if v is None else v
    L = [f"Theme assessment (snapshot {t['snapshot']}; computed from all companies' order, capacity and launch "
         f"filings before the cutoff). Overall theme grade: **{t.get('best_grade', 'NONE')}**.", "",
         "Grades: " + "; ".join(f"{k} = {v}" for k, v in (t.get("grades") or {}).items()) + ".", ""]
    L += _table(["theme (key phrases)", "grade", "stage", "companies now (yr ago), 13-wk change", "weeks tracked",
                 "company: role, rank, value share %, entrant", "this packet's events in the theme", "why"],
                [[f"{x['theme']} ({', '.join(x['phrases'][:3])})", x["grade"],
                  f"{x['stage']} {STAGE_LABEL.get(x['stage'], '')}",
                  f"{x['companies']} ({x['companies_year_ago']}), {f(x['momentum_13w'])}", x["weeks_tracked"],
                  f"{ROLE_LABEL.get(x.get('role'), 'role not stated')}, #{x['company_rank']}, "
                  f"{f(x['company_value_share_pct'])}, {x['entrant'].lower()}",
                  ", ".join(e[:8] for e in x["packet_events_in_theme"]) or "none", "; ".join(x["reasons"])]
                 for x in rows])
    return L + [""]


def emergent_section(t: Optional[dict]) -> list[str]:
    """Emergent themes discovered from order / capacity / launch passages across all companies."""
    t = t or {}
    rows = t.get("themes") or []
    if not t.get("snapshot"):
        return ["Emerging themes: no snapshot on or before the cutoff.", ""]
    if not rows:
        return [f"Emerging themes (snapshot {t['snapshot']}): the company's recent order, capacity and launch "
                "passages fall in no theme shared by 3+ companies.", ""]
    f = lambda v: "–" if v is None else v
    return ([f"Emerging themes (snapshot {t['snapshot']}; phrases several companies used in order, capacity and "
             "launch filings in the last 180 days, compared with the same 180 days a year earlier):", ""]
            + _table(["theme (key phrases)", "stage", "companies now (a year ago)", "growth %", "theme first seen",
                      "this company: role, passages, firm value INR crore, first seen"],
                     [[f"{x['theme']} ({', '.join(x['phrases'][:4])})", f"{x['stage']} {STAGE_LABEL.get(x['stage'], '')}",
                       f"{x['companies']} ({x['companies_year_ago']})", f(x["growth_pct"]), x["theme_first_detected"],
                       f"{ROLE_LABEL.get(x.get('company_role'), 'role not stated')}, {x['company_mentions']}, "
                       f"{x['company_value_cr']:.0f}, {x['company_first_seen']}"] for x in rows])
            + [""])


def result_template(content: dict, packet_hash: str) -> dict:
    """The triage return schema (spec 5.3), pre-filled with identity, cutoff and the packet hash."""
    return dict(issuer_id=content["company"]["issuer_id"], as_of=content["manifest"]["cutoff"],
                packet_hash=packet_hash,
                event_ids=sorted({e["event_id"] for e in content["events"]}), mechanism="", what_changed="",
                commercial_stage="UNKNOWN", materiality_status="", next_milestone=None, funding_status="",
                contradictions=[], missing_information=[], evidence_refs=[], size_pct_of_revenue=None,
                size_basis="UNKNOWN", firm=None, routine=None, disqualifier=None, pass_through=False,
                triage_action="", confidence="", rationale="", triage_rules_version=R.TRIAGE_RULES_VERSION,
                **({"theme_signal": "", "theme_used": None} if R.WITH_THEMES else {}),
                **({"order_flow_noted": None} if R.WITH_ORDER_FLOW else {}))
