"""NSE results XBRL: the listing of a company's results filings, and the figures in each filing.

Ported from MakroGraph at b31bdd0 (see docs/reuse_inventory.md):

* ``earnings_inflection/xbrl_results.py``: the tag map, the declared-period rule (a fact's period is
  its context group's ``DateOfStart/EndOfReportingPeriod``, because NSE files leave "OneD"/"FourD"
  undefined or give year-to-date contexts the quarter's dates), segment naming, and the statement
  arithmetic checks;
* ``evaluations/*/tools/fetch_xbrl*.py``: the ``corporates-financial-results`` listing
  (Quarterly, Half-Yearly, Annual) and the dissemination-time fields.

Changes in the port:

* values stay exact rupees as ``Decimal`` with currency and scale kept apart (spec section 17);
  MakroGraph converted to float crore;
* the totals MakroGraph read only for its checks (total income, employee cost, other expenses,
  continuing and discontinued profit, share of associates) are kept as figures too;
* a figure in a failed arithmetic check is kept with no value and ``UNVERIFIED`` (never repaired);
* listing uses the shared rate-limited ``HttpClient``; a blocked or non-JSON reply is BLOCKED.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Optional
from urllib.parse import urlencode

from .common import IST, WindowStatus, decode_json
from .http import HttpClient
from .nse import NSE_BASE

RESULTS_URL = f"{NSE_BASE}/api/corporates-financial-results"
REFERER = f"{NSE_BASE}/companies-listing/corporate-filings-financial-results"
ARCHIVES_PREFIX = "https://nsearchives.nseindia.com/"
PERIODS = ("Quarterly", "Half-Yearly", "Annual")
MAX_BYTES = 5_000_000          # results XBRL files are ~50-150 KB

# company-level tags -> metric
MONEY_TAGS = {
    "RevenueFromOperations": "revenue",
    "OtherIncome": "other_income",
    "Income": "total_income",
    "CostOfMaterialsConsumed": "cost_of_materials",
    "PurchasesOfStockInTrade": "purchases_stock_in_trade",
    "ChangesInInventoriesOfFinishedGoodsWorkInProgressAndStockInTrade": "inventory_change",
    "EmployeeBenefitExpense": "employee_cost",
    "FinanceCosts": "finance_cost",
    "DepreciationDepletionAndAmortisationExpense": "depreciation",
    "OtherExpenses": "other_expenses",
    "Expenses": "total_expenses",
    "ExceptionalItemsBeforeTax": "exceptional_items",
    "ProfitBeforeExceptionalItemsAndTax": "pbt_before_exceptional",
    "ProfitBeforeTax": "pbt",
    "TaxExpense": "tax",
    "ProfitLossForPeriodFromContinuingOperations": "pat_continuing",
    "ProfitLossFromDiscontinuedOperationsAfterTax": "pat_discontinued",
    "ShareOfProfitLossOfAssociatesAndJointVenturesAccountedForUsingEquityMethod": "share_of_associates",
    "ProfitLossForPeriod": "pat",
    "ProfitOrLossAttributableToOwnersOfParent": "pat_owners",
    "ProfitOrLossAttributableToNonControllingInterests": "pat_non_controlling",
    "PaidUpValueOfEquityShareCapital": "paid_up_capital",
}
PER_SHARE_TAGS = {
    "FaceValueOfEquityShareCapital": "face_value",
    "BasicEarningsLossPerShareFromContinuingAndDiscontinuedOperations": "eps_basic",
    "DilutedEarningsLossPerShareFromContinuingAndDiscontinuedOperations": "eps_diluted",
}
SEGMENT_TAGS = {
    "SegmentRevenue": "segment_revenue",
    "SegmentProfitLossBeforeTaxAndFinanceCosts": "segment_result",
}
_PERIOD_TYPES = {3: "QUARTER", 6: "HALF_YEAR", 9: "NINE_MONTHS", 12: "ANNUAL"}


# ---------------------------------------------------------------- listing

@dataclass(frozen=True)
class ResultEntry:
    """One results filing in NSE's listing for a symbol."""
    symbol: str
    xbrl_url: str
    listing_period: str                 # Quarterly / Half-Yearly / Annual
    from_date: Optional[date]
    to_date: Optional[date]
    consolidated: str                   # the listing's own text, e.g. "Consolidated" / "Non-Consolidated"
    disseminated_at: Optional[datetime] # IST; when the figures became public
    raw_time: str
    raw: dict = field(default_factory=dict, compare=False, repr=False)

    @property
    def external_id(self) -> str:
        return self.xbrl_url.rsplit("/", 1)[-1].removesuffix(".xml")


@dataclass
class ListingResult:
    symbol: str
    index: str
    status: WindowStatus
    entries: list[ResultEntry] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    requests: int = 0


def _dmy(s: Optional[str]) -> Optional[date]:
    try:
        return datetime.strptime((s or "").strip(), "%d-%b-%Y").date()
    except ValueError:
        return None


def _dissemination(e: dict) -> tuple[Optional[datetime], str]:
    for key in ("exchdisstime", "broadCastDate", "filingDate"):
        s = (e.get(key) or "").strip()
        for fmt in ("%d-%b-%Y %H:%M:%S", "%d-%b-%Y %H:%M"):
            try:
                return datetime.strptime(s, fmt).replace(tzinfo=IST), s      # exchange times are IST
            except ValueError:
                continue
    return None, ""


def parse_entry(e: dict, symbol: str, period: str) -> Optional[ResultEntry]:
    url = (e.get("xbrl") or "").strip()
    if not url.startswith(ARCHIVES_PREFIX) or not re.search(r"/[A-Za-z0-9_\-]+\.xml$", url):
        return None
    when, raw_time = _dissemination(e)
    return ResultEntry(symbol, url, period, _dmy(e.get("fromDate")), _dmy(e.get("toDate")),
                       str(e.get("consolidated") or ""), when, raw_time, e)


class NSEResultsListing:
    def __init__(self, client: Optional[HttpClient] = None):
        self.client = client or HttpClient()
        self._warmed = False

    def _warm(self) -> None:
        if not self._warmed:
            for url in (NSE_BASE, REFERER):
                self.client.get(url, referer=NSE_BASE, accept="text/html,application/xhtml+xml")
            self._warmed = True

    def list_symbol(self, symbol: str, index: str = "equities") -> ListingResult:
        """All results filings NSE lists for ``symbol`` (every listing period).  A period that is
        blocked or fails makes the whole listing BLOCKED / PARTIAL, never silently shorter."""
        before = self.client.requests
        self._warm()
        out = ListingResult(symbol, index, WindowStatus.COMPLETE)
        statuses = []
        seen: set[str] = set()
        no_xbrl = 0
        for period in PERIODS:
            q = urlencode({"index": index, "symbol": symbol, "period": period})
            status, data, note = decode_json(self.client.get(f"{RESULTS_URL}?{q}", referer=REFERER))
            statuses.append(status)
            if note:
                out.notes.append(f"{period}: {note}")
            if status != WindowStatus.COMPLETE:
                continue
            items = data if isinstance(data, list) else ((data or {}).get("data") or [])
            for item in items:
                entry = parse_entry(item, symbol, period) if isinstance(item, dict) else None
                if entry is None:
                    no_xbrl += 1
                elif entry.xbrl_url not in seen:
                    seen.add(entry.xbrl_url)
                    out.entries.append(entry)
        if no_xbrl:
            out.notes.append(f"{no_xbrl} listed filings have no XBRL file")
        ok = [s == WindowStatus.COMPLETE for s in statuses]
        if all(ok):
            out.status = WindowStatus.COMPLETE if out.entries or no_xbrl else WindowStatus.EMPTY_UNVERIFIED
        elif any(ok):
            out.status = WindowStatus.PARTIAL
        elif WindowStatus.BLOCKED in statuses:
            out.status = WindowStatus.BLOCKED
        else:
            out.status = WindowStatus.FAILED
        out.requests = self.client.requests - before
        return out


# ---------------------------------------------------------------- parsing one filing

@dataclass
class Figure:
    metric: str
    period_start: date
    period_end: date
    period_type: str                    # QUARTER / HALF_YEAR / NINE_MONTHS / ANNUAL
    cumulative: bool                    # longer than the filing's own reporting period (year to date)
    scope: str                          # CONSOLIDATED / STANDALONE / UNKNOWN
    segment: Optional[str]
    value: Optional[Decimal]            # rupees (or rupees per share); None when it fails a check
    value_kind: str                     # MONEY / PER_SHARE
    original_text: str
    tag: str
    context: str
    unverified: bool = False


@dataclass
class ParsedFiling:
    figures: list[Figure]
    issues: list[str]
    symbol: Optional[str] = None
    scope: str = "UNKNOWN"


def _local(tag: str) -> tuple[str, str]:
    if tag.startswith("{"):
        ns, name = tag[1:].split("}", 1)
        return ns, name
    return "", tag


def _group(context_id: str) -> str:
    """'FourReportableSegmentRevenue01D' -> 'Four' (NSE context naming: group word, then detail)."""
    m = re.match(r"[A-Z][a-z]+", context_id or "")
    return m.group(0) if m else context_id


def _iso(s: Optional[str]) -> Optional[date]:
    try:
        return date.fromisoformat((s or "").strip()[:10])
    except ValueError:
        return None


def _months(start: date, end: date) -> int:
    return (end.year - start.year) * 12 + end.month - start.month + 1


def parse_results_xbrl(body: bytes) -> ParsedFiling:
    """Figures from one results XBRL filing.  Fails closed: anything unreadable is an issue, not a figure."""
    if not body or len(body) > MAX_BYTES or b"<!ENTITY" in body[:5000]:
        return ParsedFiling([], ["not a results XBRL file (empty, oversized or declares entities)"])
    try:
        root = ET.fromstring(body)
    except ET.ParseError as e:
        return ParsedFiling([], [f"XBRL not well-formed ({str(e)[:80]})"])

    contexts: dict[str, dict] = {}
    units: dict[str, str] = {}
    facts: list[tuple[str, str, Optional[str], str]] = []      # (name, contextRef, unitRef, text)
    fin_ns = None
    for el in root:
        ns, name = _local(el.tag)
        if name == "context":
            start = end = None
            dims: dict[str, str] = {}
            for sub in el.iter():
                _, sname = _local(sub.tag)
                if sname == "startDate":
                    start = _iso(sub.text)
                elif sname == "endDate":
                    end = _iso(sub.text)
                elif sname == "instant":
                    start = end = _iso(sub.text)
                elif sname in ("explicitMember", "typedMember"):
                    dims[sub.get("dimension", "")] = (sub.text or "").strip() or "".join(
                        (c.text or "").strip() for c in sub)
            contexts[el.get("id", "")] = {"start": start, "end": end, "dims": dims}
        elif name == "unit":
            units[el.get("id", "")] = "/".join((m.text or "").strip() for m in el.iter() if _local(m.tag)[1] == "measure")
        else:
            if fin_ns is None and (ns.endswith("/in-bse-fin") or ns.endswith("/in-capmkt")):
                fin_ns = ns
            if ns and ns == fin_ns:
                facts.append((name, el.get("contextRef", ""), el.get("unitRef"), (el.text or "").strip()))
    if fin_ns is None:
        return ParsedFiling([], ["no in-bse-fin / in-capmkt facts; not a results XBRL file"])

    def first(tag: str) -> Optional[str]:
        return next((v for n, _, _, v in facts if n == tag and v), None)

    nature = (first("NatureOfReportStandaloneConsolidated") or "").lower()
    scope = "CONSOLIDATED" if nature.startswith("consolidated") else (
        "STANDALONE" if nature.startswith("standalone") else "UNKNOWN")
    issues: list[str] = []

    seg_names: dict[tuple, str] = {}
    for n, cref, _, v in facts:
        if n == "DescriptionOfReportableSegment" and cref in contexts:
            seg_names[tuple(sorted(contexts[cref]["dims"].items()))] = v

    declared: dict[str, dict] = {}
    for n, cref, _, v in facts:
        if n in ("DateOfStartOfReportingPeriod", "DateOfEndOfReportingPeriod"):
            declared.setdefault(_group(cref), {})["start" if "Start" in n else "end"] = _iso(v)

    def period(cref: str) -> tuple[Optional[date], Optional[date]]:
        d = declared.get(_group(cref))
        if d and d.get("start") and d.get("end"):
            return d["start"], d["end"]
        if declared:
            return None, None           # declarations exist but not for this group: unknown period
        ctx = contexts.get(cref) or {}
        return ctx.get("start"), ctx.get("end")

    spans = [(d["start"], d["end"]) for d in declared.values() if d.get("start") and d.get("end")]
    shortest = min((_months(s, e) for s, e in spans), default=None)

    figures: list[Figure] = []
    for n, cref, uref, v in facts:
        metric = MONEY_TAGS.get(n) or PER_SHARE_TAGS.get(n) or SEGMENT_TAGS.get(n)
        if metric is None:
            continue
        start, end = period(cref)
        if not start or not end:
            issues.append(f"{n} in context {cref} has no declared period; not used")
            continue
        ptype = _PERIOD_TYPES.get(_months(start, end))
        if ptype is None:
            continue
        try:
            value = Decimal(v.replace(",", ""))
        except InvalidOperation:
            issues.append(f"{n} in context {cref}: {v!r} is not a number; not used")
            continue
        ctx = contexts.get(cref) or {"dims": {}}
        unit_name = units.get(uref or "", "")
        segment = None
        if n in SEGMENT_TAGS:
            segment = seg_names.get(tuple(sorted(ctx["dims"].items())))
            if not segment:
                continue
        elif ctx["dims"]:
            continue                    # company-level tags only from contexts without dimensions
        if n in PER_SHARE_TAGS:
            if "INR" not in unit_name:
                continue
            kind = "PER_SHARE"
        else:
            if unit_name != "iso4217:INR":
                issues.append(f"{n} in unit {unit_name or '?'}, not INR; not used")
                continue
            kind = "MONEY"
        figures.append(Figure(metric, start, end, ptype, shortest is not None and _months(start, end) > shortest,
                              scope, segment, value, kind, v, n, cref))
    _check_arithmetic(figures, issues)
    return ParsedFiling(figures, issues, first("Symbol"), scope)


def _check_arithmetic(figures: list[Figure], issues: list[str]) -> None:
    """The statement's own arithmetic, per period.  Figures in a failed identity lose their value and
    become UNVERIFIED (the original text stays).  Nothing is repaired: a sign the filer dropped stays
    an error.  Ported from MakroGraph ``_check_identities``."""
    by = {(f.metric, f.period_type, f.period_end): f for f in figures if f.segment is None}
    periods = {(f.period_type, f.period_end) for f in figures if f.segment is None}

    def ok(a: Decimal, b: Decimal) -> bool:
        return abs(a - b) <= max(Decimal(500000), Decimal("0.005") * max(abs(a), abs(b)))   # ₹5 lakh or 0.5%

    failed: set[int] = set()
    for pt, end in sorted(periods):
        def g(m):
            return by.get((m, pt, end))

        def val(m, default=None):
            f = g(m)
            return f.value if f is not None else default

        checks = []
        rev, oi, income = g("revenue"), g("other_income"), g("total_income")
        if rev and income:
            checks.append(("revenue + other income = total income", [rev, oi, income],
                           ok(rev.value + val("other_income", Decimal(0)), income.value)))
        parts = ["cost_of_materials", "purchases_stock_in_trade", "inventory_change", "employee_cost",
                 "finance_cost", "depreciation", "other_expenses"]
        exp_ = g("total_expenses")
        if exp_ and all(g(m) for m in ("employee_cost", "other_expenses", "depreciation", "finance_cost")):
            checks.append(("expense lines sum to total expenses", [g(m) for m in parts] + [exp_],
                           ok(sum((val(m, Decimal(0)) for m in parts), Decimal(0)), exp_.value)))
        pre = g("pbt_before_exceptional")
        if income and exp_ and pre:
            checks.append(("total income - expenses = profit before exceptional items", [exp_, pre],
                           ok(income.value - exp_.value, pre.value)))
        pbt = g("pbt")
        if pre and pbt:
            checks.append(("profit before exceptional items + exceptional items = PBT", [pre, g("exceptional_items"), pbt],
                           ok(pre.value + val("exceptional_items", Decimal(0)), pbt.value)))
        tax, cont = g("tax"), g("pat_continuing")
        if pbt and tax and cont:
            checks.append(("PBT - tax = profit from continuing operations", [pbt, tax, cont],
                           ok(pbt.value - tax.value, cont.value)))
        pat = g("pat")
        if pat and cont:
            base = cont.value + val("pat_discontinued", Decimal(0))
            checks.append(("continuing + discontinued = profit for the period", [pat],
                           ok(base, pat.value) or ok(base + val("share_of_associates", Decimal(0)), pat.value)))
        own, nci = g("pat_owners"), g("pat_non_controlling")
        if pat and own and nci:
            checks.append(("owners' share + non-controlling share = profit for the period", [own, nci],
                           ok(own.value + nci.value, pat.value)))
        for name, members, good in checks:
            if not good:
                failed.update(id(m) for m in members if m is not None)
                issues.append(f"fails '{name}' for {pt} ending {end}; those figures are UNVERIFIED")
    for f in figures:
        if id(f) in failed:
            f.value, f.unverified = None, True
