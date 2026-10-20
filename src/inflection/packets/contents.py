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
import math
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional

from ..asof import IST
from ..units import Money, Scale, growth
from . import rules as R

PACKET_VERSION = "triage-packet-3" if R.WITH_VALUATION else "triage-packet-2"            # 2: carries the triage decision rule (rules.py)
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
    if value is None or scale is None:
        return None
    return Money(Decimal(value), currency or "INR", Scale(scale)).to(Scale.CRORE).value


def _fmt(d: Optional[Decimal], places: int = 1) -> Optional[str]:
    return None if d is None else f"{d:,.{places}f}"


# ---------------------------------------------------------------- financial snapshot

def financial_snapshot(facts: list[dict]) -> dict:
    """The latest eight quarters and three years in one scope, with year-on-year growth, trailing
    twelve months and the share count.  ``facts`` holds, per (metric, period type, period end,
    scope), the latest version public by the cutoff."""
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
        if f["value_kind"] == "MONEY":
            return dict(value=_fmt(_crore(f["value"], f["currency"], f["scale"]), 2))
        return dict(value=_fmt(Decimal(f["value"]), 2))

    def money(metric, ptype, end) -> Optional[Money]:
        f = at.get((metric, ptype, end))
        if f is None or f["value"] is None or f["value_kind"] != "MONEY":
            return None
        return Money(Decimal(f["value"]), f["currency"] or "INR", Scale(f["scale"]))

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

    def ttm(metric: str) -> dict:
        last = quarters[-4:]
        months = [q.year * 12 + q.month for q in last]
        if len(last) < 4 or any(b - a != 3 for a, b in zip(months, months[1:])):
            return dict(value=None, why="four consecutive quarters not available")
        vals = [money(metric, "QUARTER", q) for q in last]
        if any(v is None for v in vals):
            return dict(value=None, why="a quarter's figure is missing")
        return dict(value=_fmt(sum(v.to(Scale.CRORE).value for v in vals), 2), period_end=last[-1].isoformat())

    shares = _shares(mine, at)
    pubs = sorted({str(f["publication_id"]) for f in mine if f["publication_id"] and
                   f["period_end"] in set(quarters) | set(years)})
    return dict(
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


def _shares(mine: list[dict], at: dict) -> dict:
    """Share count from paid-up capital / face value in the latest filing that has both, and the
    change against a year earlier (a dilution check)."""
    periods = ("QUARTER", "ANNUAL")
    counts = {}
    for end in sorted({f["period_end"] for f in mine if f["metric"] == "paid_up_capital"}):
        cap = next((at[("paid_up_capital", p, end)] for p in periods if ("paid_up_capital", p, end) in at), None)
        fv = next((at[("face_value", p, end)] for p in periods if ("face_value", p, end) in at), None)
        if cap and fv and cap["value"] is not None and cap["scale"] and fv["value"]:
            counts[end] = Money(Decimal(cap["value"]), cap["currency"] or "INR", Scale(cap["scale"])).to_base() \
                / Decimal(fv["value"])
    if not counts:
        return dict(value=None, why="paid-up capital or face value not filed")
    end = max(counts)
    prior = [e for e in counts if (end - e).days >= 330]
    out = dict(value=_fmt(counts[end] / Decimal(10) ** 7, 3), unit="crore shares", period_end=end.isoformat(),
               base=counts[end])
    if prior:
        p = max(prior)
        out["change_pct_vs_year_earlier"] = _fmt((counts[end] / counts[p] - 1) * 100, 1)
    return out


# ---------------------------------------------------------------- price and liquidity

def price_summary(prices: list[tuple], actions: list[dict], cutoff_day: date,
                  shares: Optional[Decimal] = None) -> dict:
    """``prices``: (trade date, close, volume) public by the cutoff, any order.  ``actions``: splits,
    bonuses and other actions on the same security (kind, ex_date, multiplier or None, subject)."""
    rows = sorted((d, Decimal(c), Decimal(v) if v is not None else None) for d, c, v in prices if c is not None)
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
                if a.get("multiplier") is None:
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

    returns = {}
    for label, days in (("1m", 30), ("3m", 91), ("6m", 182), ("12m", 365)):
        r = on_or_before(last_d - timedelta(days=days))
        if r is None:
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
               adjustment="unadjusted closes; returns, highs and lows adjusted for splits and bonuses")
    if shares:
        out["market_cap_cr"] = _fmt(shares * last_c / Decimal(10) ** 7, 0)
    return out


def valuation(fin: dict, price: dict) -> dict:
    """P/S (market cap / TTM revenue), TTM operating margin and its change on a year earlier, TTM revenue growth.
    Operating profit = profit before tax + finance cost + depreciation - other income (exceptional items included)."""
    if fin.get("status") != "FOUND":
        return dict(status="MISSING", reason="no financial snapshot")
    def col(metric):
        return [Decimal(c["value"]) if c.get("value") is not None else None for c in fin["rows"].get(metric, [])]
    rev, pbt, fc, dep, oi = (col(m) for m in ("revenue", "pbt", "finance_cost", "depreciation", "other_income"))
    def ttm_opm(sl):
        q = list(zip(*(x[sl] for x in (rev, pbt, fc, dep))))
        o = oi[sl]
        if len(q) < 4 or any(None in t for t in q): return None, None
        r = sum(t[0] for t in q)
        op = sum(t[1] + t[2] + t[3] for t in q) - sum(x or 0 for x in o)
        return (op / r if r else None), r
    now, r_now = ttm_opm(slice(-4, None))
    before, r_before = ttm_opm(slice(-8, -4)) if len(rev) >= 8 else (None, None)
    mcap = Decimal(price["market_cap_cr"]) if price.get("market_cap_cr") else None
    return dict(status="FOUND",
                price_to_sales=_fmt(mcap / r_now, 2) if mcap and r_now else None,
                market_cap_cr=_fmt(mcap, 0) if mcap else None, ttm_revenue_cr=_fmt(r_now, 2) if r_now else None,
                opm_ttm_pct=_fmt(now * 100, 1) if now is not None else None,
                opm_change_pts=_fmt((now - before) * 100, 1) if now is not None and before is not None else None,
                revenue_growth_ttm_pct=_fmt((r_now / r_before - 1) * 100, 1) if r_now and r_before else None,
                note="computed from the financial snapshot and the last close; operating margin = PBT + finance cost "
                     "+ depreciation - other income, over revenue")


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


def build(head: dict, identity: dict, evaluations: list[dict], prior_triage: Optional[dict], events: list[dict],
          passages: list[dict], documents: list[dict], fin: dict, price: dict, excluded: dict,
          budget: int = TOKEN_BUDGET, order_book: Optional[list[dict]] = None) -> tuple[dict, str]:
    """(content, markdown).  ``passages`` carry kind TRIGGER, CONTRADICTS or PRIOR, newest first."""
    trig = [_passage(p) for p in passages if p["kind"] == "TRIGGER"]
    contra = [_passage(p) for p in passages if p["kind"] == "CONTRADICTS"]
    prior = [_passage(p) for p in passages if p["kind"] == "PRIOR"]
    flags = risk_flags(head, evaluations, events, documents, fin, price, contra)
    missing = []
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
                      sources=sorted(({k: d.get(k) for k in ("publication_id", "sha256", "text_sha256")}
                                      for d in documents), key=lambda d: d["publication_id"]),
                      token_budget=budget, token_estimate=None, token_rule=f"characters / {CHARS_PER_TOKEN}",
                      completeness=None, missing_evidence=missing, truncation=[]),
        company=identity,
        why_now=dict(reason=head["reason"], note=head.get("note"), corroborated=head.get("corroborated", False),
                     waiting_since=ist(head["waiting_since"]), prior_triage=prior_triage,
                     evaluations=[dict(route=e["route"], as_of=ist(e["as_of"]), priority=e["priority"],
                                       outcome=e["outcome"], reasons=e["reasons"], detail=_why(e))
                                  for e in evaluations]),
        risk_flags=flags, events=events, trigger_passages=trig, contradicting_passages=contra,
        prior_passages=prior, documents=documents, financials=fin, price=price,
        **({"valuation": valuation(fin, price), "order_book": order_book or []} if R.WITH_VALUATION else {}))


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
                      f"{e['stage']} ({e.get('previous_stage') or 'new'})", e.get("amount") or "–", e["amount_basis"],
                      f"{e.get('counterparty') or 'unnamed'} [{e.get('relationship') or 'UNKNOWN'}]",
                      e.get("deadline") or "–", e["contradiction_status"]] for e in c["events"]]) + [""]
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
        L.append(f"Trailing twelve months: revenue {_cellv(f['ttm']['revenue'])}, PAT {_cellv(f['ttm']['pat'])}. "
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
                        [[x["quarter_end"], x["order_book_cr"] or "–", x["book_yoy_pct"] if x["book_yoy_pct"] is not None else "–",
                          x["order_inflow_cr"] or "–", x["inflow_yoy_pct"] if x["inflow_yoy_pct"] is not None else "–"] for x in ob])
            L += ["Figures are extracted by rules from company documents and may be a segment's book or a pipeline; "
                  "use them as context for how normal the trigger order is, not as a size.", ""]
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


def result_template(content: dict, packet_hash: str) -> dict:
    """The triage return schema (spec 5.3), pre-filled with identity, cutoff and the packet hash."""
    return dict(issuer_id=content["company"]["issuer_id"], as_of=content["manifest"]["cutoff"],
                packet_hash=packet_hash,
                event_ids=sorted({e["event_id"] for e in content["events"]}), mechanism="", what_changed="",
                commercial_stage="UNKNOWN", materiality_status="", next_milestone=None, funding_status="",
                contradictions=[], missing_information=[], evidence_refs=[], size_pct_of_revenue=None,
                size_basis="UNKNOWN", firm=None, routine=None, disqualifier=None, pass_through=False,
                triage_action="", confidence="", rationale="", triage_rules_version=R.TRIAGE_RULES_VERSION)
