"""Income-statement figures read from the text of a company's results filing (owner decision 2026-11-01:
no company may be left without financials).

Exchange XBRL covers NSE filings only, and BSE's results snapshot keeps five quarters.  Every listed
company still files its results statement as a PDF, and its text is often already extracted.  This
reads the main column of that statement:

* the unit must be stated on the page ("(Rs. in Lakhs)", "₹ in crore"); a page without one is skipped;
* the first date of the column header is the period of the first column; its kind (quarter, half
  year, year) comes from the first period label in the header;
* scope is the statement's own label (standalone or consolidated) nearest before the header;
* a figure is the first number on its line; parentheses are negative;
* a statement whose figures do not hang together (expenses or profit wildly beyond revenue) is dropped.

Figures are public from the filing's publication time.  A figure already filed in XBRL for the same
issuer, period, scope and metric is never written again (XBRL wins).

    python -m inflection.results_text check [--limit N]     # agreement with XBRL on filings that have both
    python -m inflection.results_text load [--limit N]      # write figures for filings without XBRL
"""
from __future__ import annotations

import argparse
import calendar
import hashlib
import json
import os
import re
from collections import Counter
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Optional

PROVIDER = "results_text"
PROVIDER_VERSION = "results-text-1"
CREATED_BY = "inflection.results_text"
I = re.I

UNIT = re.compile(r"(?:rs\.?|₹|inr|rupees|`|amount|amt\.?|figures|\(\s*r|\br)\s*\.?\s*(?:in\s+)?(lakhs?|lacs?|crores?|cr\.?|millions?|mn|"
                  r"thousands?|'000)\b", I)
UNIT_SCALE = {"lakh": Decimal(10) ** 5, "lac": Decimal(10) ** 5, "crore": Decimal(10) ** 7, "cr": Decimal(10) ** 7,
              "million": Decimal(10) ** 6, "mn": Decimal(10) ** 6, "thousand": Decimal(10) ** 3, "'000": Decimal(10) ** 3}
MONTH = {m.lower(): i for i, m in enumerate(calendar.month_name) if m} | {
    m.lower(): i for i, m in enumerate(calendar.month_abbr) if m}
DATE = re.compile(r"\b(\d{1,2})(?:st|nd|rd|th)?[.\-/ ·](\d{1,2}|[A-Za-z]{3,9})[.\-/ ,·]{1,2}(\d{4}|\d{2})\b")
DATE_MONTH_FIRST = re.compile(r"\b([A-Za-z]{3,9})\.?\s+(\d{1,2})(?:st|nd|rd|th)?\s*,?\s*(\d{4})\b")
BARE_UNIT = re.compile(r"\bin\s+(lakhs?|lacs?|crores?|millions?|thousands?)\b", I)
PERIOD_LABEL = re.compile(r"\b(quarter|three months|half[- ]?year|six months|nine months|year)\s*(?:ended|ending)\b", I)
SCOPE = re.compile(r"\b(standalone|consolidated)\b", I)
NUMBER = re.compile(r"\(\s*-?[\d,]+(?:\.\d+)?\s*\)|-?[\d,]*\d(?:\.\d+)?")
LINES = (  # metric, line start (after an optional row number), words that disqualify the line
    ("revenue", re.compile(r"(?:revenue from operations|[il1]ncome from operations?|net sales|sales\s*/\s*[il1]ncome from operations?|"
                           r"total revenue from operations)\b", I), re.compile(r"other income|total income|total revenue \(", I)),
    ("other_income", re.compile(r"o[l1]?ther [il1]ncome\b", I), None),
    ("_total_income", re.compile(r"total [il1]ncome\b|total revenue\b", I), re.compile(r"comprehensive", I)),
    ("total_expenses", re.compile(r"total (?:expenses|expenditure)\b", I), None),
    ("_pbt_before_exceptional", re.compile(r"(?:net )?profit\s*/?\s*\(?loss\)?\s*before exceptional", I), None),
    ("finance_cost", re.compile(r"finance costs?\b", I), re.compile(r"relating to|nbfc|hfc", I)),
    ("depreciation", re.compile(r"depreciation\b", I), re.compile(r"\band tax\b|\(\d\s*-\s*\d\)", I)),
    ("pat", re.compile(r"(?:net )?profit\s*/?\s*\(?loss\)?\s*(?:after tax\s*)?for the (?:period|quarter|year)\b|"
                       r"net profit\s*/?\s*\(?loss\)?\s*after tax\b|profit after tax\b", I),
     re.compile(r"before tax|other comprehensive|attributable|owners|non[- ]controlling|discontinu", I)),
)
ROW_PREFIX = re.compile(r"^[\W\d]*(?:(?:[ivxl]+|[a-z])[\W]{1,3})?\s*", I)


@dataclass(frozen=True)
class Figure:
    metric: str
    period_type: str
    period_start: Optional[date]
    period_end: date
    scope: str
    value: Decimal                      # rupees
    original_text: str
    page_no: int


def _dates(line: str) -> list[date]:
    """Column dates in reading order, day-first (30.06.2020, 31-Dec-25) or month-first (September 30, 2023)."""
    found = [(m.start(), _date(m)) for m in DATE.finditer(line)]
    found += [(m.start(), _date_month_first(m)) for m in DATE_MONTH_FIRST.finditer(line)]
    return [d for _, d in sorted(found, key=lambda t: t[0]) if d]


def _date_month_first(m: re.Match) -> Optional[date]:
    mo, d, y = m.groups()
    key = mo.lower()
    month = MONTH.get(key) or MONTH.get(key[:3])
    try:
        return date(int(y), month, int(d)) if month else None
    except ValueError:
        return None


def _date(m: re.Match) -> Optional[date]:
    d, mo, y = m.groups()
    month = int(mo) if mo.isdigit() else MONTH.get(mo.lower()[:3] if mo.lower()[:3] in MONTH else mo.lower())
    year = int(y) + (2000 if len(y) == 2 else 0)
    try:
        return date(year, month, int(d)) if month else None
    except ValueError:
        return None


def _number(token: str) -> Optional[Decimal]:
    neg = token.strip().startswith("(") or token.strip().startswith("-")
    try:
        v = Decimal(re.sub(r"[^\d.]", "", token))
    except InvalidOperation:
        return None
    return -v if neg else v


def _first_number(rest: str) -> Optional[tuple[Decimal, str]]:
    # skip roman/row references like "(I+II)" or "(IV)"; take the first figure with digits
    for m in NUMBER.finditer(rest):
        tok = m.group(0)
        if not re.search(r"\d", tok):
            continue
        if re.fullmatch(r"\d{1,2}", tok.strip("() ")) and not re.search(r"\.", tok):
            continue                                   # a note number ("Note 3"), not a figure
        v = _number(tok)
        if v is not None:
            return v, tok
    return None


def _period_type(label: str) -> str:
    label = label.lower()
    if label.startswith(("quarter", "three")):
        return "QUARTER"
    if label.startswith(("half", "six")):
        return "HALF_YEAR"
    if label.startswith("nine"):
        return "NINE_MONTHS"
    return "ANNUAL"


def _start(ptype: str, end: date) -> Optional[date]:
    """First day of the column's period, counted back from its end (any fiscal year)."""
    months = {"QUARTER": 3, "HALF_YEAR": 6, "NINE_MONTHS": 9, "ANNUAL": 12}[ptype]
    m = end.month - months + 1
    y = end.year + (m - 1) // 12
    return date(y, (m - 1) % 12 + 1, 1)


def read_page(page_no: int, body: str, unlabelled_scope: Optional[str] = None) -> list[Figure]:
    if not (UNIT.search(body) or BARE_UNIT.search(body)):
        return []
    lines = body.splitlines()
    out: list[Figure] = []
    header_at = None
    for i, line in enumerate(lines):
        dates = _dates(line)
        if len(dates) < 2 and i + 1 < len(lines):
            dates = _dates(line + " " + lines[i + 1])          # a header wrapped over two lines
            dates = dates if len(dates) >= 3 else []
        if len(dates) >= 2 and dates[0].day == calendar.monthrange(dates[0].year, dates[0].month)[1] \
                and dates[0].month in (3, 6, 9, 12):
            header_at = i
            break
    title_period = None
    if header_at is None:
        # OCR often loses the column dates ("31, 2020. 30, 2020"); the statement's own title still states the
        # period ("RESULTS FOR THE QUARTER AND NINE MONTHS ENDED DECEMBER 31, 2020"): its first period is column one
        for i, line in enumerate(lines):
            m = re.search(r"\b(?:results?|statement)\b.{0,60}?\b(quarter|half[- ]?year|six months|nine months|year)\b"
                          r".{0,40}\bended\b(?:\s+on)?\s*(.{6,25})", line, I)
            when = _dates(m.group(2)) if m else []
            if when and when[0].day == calendar.monthrange(when[0].year, when[0].month)[1]:
                header_at, title_period = i, (m.group(1).lower(), when[0])
                break
    if header_at is None:
        return []
    header_dates = _dates(lines[header_at])
    if len(header_dates) < 2 and header_at + 1 < len(lines):
        header_dates = _dates(lines[header_at] + " " + lines[header_at + 1])
    if title_period:
        header_dates = [title_period[1]]
    end = header_dates[0]
    # the unit stated nearest above the column header (a page can carry two tables in different units)
    units = [m for m in UNIT.finditer("\n".join(lines[:header_at + 1]))] or \
        [m for m in UNIT.finditer("\n".join(lines[header_at:header_at + 4]))] or \
        [m for m in BARE_UNIT.finditer("\n".join(lines[max(0, header_at - 15):header_at + 4]))]
    if not units:
        return []
    word = units[-1].group(1).lower()
    scale = UNIT_SCALE["'000" if word == "'000" else word.rstrip(".").rstrip("s") if word not in ("lacs",) else "lac"]
    above = "\n".join(lines[max(0, header_at - 25):header_at + 3])
    # the first column's own label: the first period word on the nearest label line above the dates
    # ("Quarter Ended Nine Months Ended Year Ended" -> quarter; Castrol's "Nine Months Nine Months Quarter")
    token = re.compile(r"\b(quarter|qtr\.?|three months|3 months|half[- ]?year|six months|6 months|nine months|"
                       r"9 months|year)\b", I)
    # the leftmost label on the label lines just above the dates stands over the first column
    found = [(m.start(), -k, m.group(1).lower()) for k, line in enumerate(lines[max(0, header_at - 4):header_at + 1])
             for m in token.finditer(line)]
    if not found and not title_period:
        return []
    w = title_period[0] if title_period else min(found)[2]
    ptype = ("QUARTER" if w.startswith(("quarter", "qtr", "three", "3")) else
             "HALF_YEAR" if w.startswith(("half", "six", "6")) else
             "NINE_MONTHS" if w.startswith(("nine", "9")) else "ANNUAL")
    # the column dates settle it where the labels are garbled: a first column compared with the period
    # three months earlier is a quarter, six months earlier a half year (SME format)
    gap = (header_dates[0].year - header_dates[1].year) * 12 + header_dates[0].month - header_dates[1].month \
        if len(header_dates) > 1 else 0
    if gap == 3:
        ptype = "QUARTER"
    elif gap == 6:
        ptype = "HALF_YEAR"
    elif gap not in (0, 12):
        return []
    scopes = SCOPE.findall("\n".join(lines[max(0, header_at - 25):header_at + 1]))
    if not scopes:
        if not unlabelled_scope:
            return []                   # an unlabelled statement could be either; never guess
        scopes = [unlabelled_scope]     # the filing never mentions consolidated figures: a standalone company
    scope = scopes[-1].upper()          # the label nearest the table
    for line in lines[max(0, header_at - 4):header_at + 1]:
        both = SCOPE.findall(line)
        if len({b.lower() for b in both}) == 2:
            scope = both[0].upper()     # side-by-side columns: the first block is the first label
    if len(header_dates) >= 8 and len({x.lower() for x in scopes}) == 2:
        scope = scopes[0].upper()       # two blocks of dates: standalone and consolidated side by side
    seen = set()
    for line in lines[header_at + 1:header_at + 80]:
        text = ROW_PREFIX.sub("", line.strip(" |"))
        for metric, start, veto in LINES:
            m = start.match(text)
            if not m or metric in seen or (veto and veto.search(text)):
                continue
            # row references are not figures: "(1+11)", "(I+II)", "(III-IV)", "(a to g)", "[4(a) to 4(g)]"
            rest = re.sub(r"[\(\[]\s*[\divxl]{1,4}\s*(?:[+\-–]|to)\s*[\divxl]{1,4}\s*[\)\]]|[\(\[][^\d\)\]]{0,12}[\)\]]", " ",
                          text[m.end():], flags=I)
            rest = re.sub(r"^(\W*)(\d{1,3}) (\d{2,3}\.\d{2})\b", r"\1\2\3", rest)   # OCR "9 74.00" = 974.00
            if re.match(r"^[\s|]*[\-–—](?:\s|$)", rest) and re.search(r"\d", rest):
                seen.add(metric)        # a dash then figures: which column is nil cannot be told
                continue
            first = _first_number(rest)
            if first is None and metric in ("revenue", "other_income", "finance_cost", "depreciation") \
                    and re.match(r"^[\s\-–—·|]+$", rest) and rest.count("-") + rest.count("–") >= 2:
                first = (Decimal(0), "-")      # a row of dashes: nil for every period
            if first is None:
                continue
            figures = [t for t in NUMBER.findall(rest) if re.search(r"\d", t)]
            if first[1] == "-":
                figures = []
            decimals = {bool(re.search(r"\.\d", t)) for t in figures}
            if len(figures) >= 3 and len(decimals) > 1:
                seen.add(metric)        # "20431 21148 197.12": columns in mixed formats, not one table
                continue
            ptype_line = ptype
            columns = 12 if title_period else len(header_dates)   # dates lost to OCR: the column count is unknown
            if figures and (len(figures) > 1.5 * max(columns, 2) or not re.search(r"[.,]", first[1]) and len(figures) > columns):
                seen.add(metric)        # "109 19 120 30": decimals read as spaces, the columns cannot be trusted
                continue
            seen.add(metric)
            out.append(Figure(metric, ptype_line, _start(ptype_line, end), end, scope, first[0] * scale, line.strip()[:300], page_no))
    if not _coherent(out):
        return []
    if title_period:
        # without column dates only the self-checked lines are trusted
        out = [f for f in out if f.metric in ("revenue", "other_income", "_total_income")]
    by = {f.metric: f.value for f in out}
    pbt, total, exp = by.get("_pbt_before_exceptional"), by.get("_total_income"), by.get("total_expenses")
    if pbt is None or exp is None or abs(total - exp - pbt) > max(Decimal("0.005") * abs(total), Decimal(10) ** 4):
        # expenses are kept only when total income - total expenses = profit before exceptional items
        out = [f for f in out if f.metric not in ("total_expenses", "finance_cost", "depreciation")]
    return [f for f in out if not f.metric.startswith("_")]


def _coherent(figs: list[Figure]) -> bool:
    by = {f.metric: f.value for f in figs}
    rev, exp, pat = by.get("revenue"), by.get("total_expenses"), by.get("pat")
    if rev is None or rev < 0:
        return False
    # the first column must add up: revenue + other income = total income (proves the column and the row reading)
    oi, total = by.get("other_income"), by.get("_total_income")
    if oi is None or total is None or abs(rev + oi - total) > max(Decimal("0.005") * abs(total), Decimal(10) ** 4):
        return False
    if len({(f.period_type, f.period_end) for f in figs if f.metric in ("revenue", "other_income", "_total_income")}) != 1:
        return False
    base = max(abs(rev), abs(exp or 0), Decimal(1))
    if exp is not None and (exp < 0 or (rev > 0 and exp > 50 * rev and exp > 10 ** 8)):
        return False
    return pat is None or abs(pat) <= 5 * base


def read_document(pages: list[tuple[int, str]]) -> list[Figure]:
    """The first coherent statement per scope in the filing."""
    out, scopes = [], set()
    single = None if any(re.search(r"\bconsolidat", b or "", I) for _, b in pages) else "STANDALONE"
    for page_no, body in pages:
        figs = read_page(page_no, body or "", single)
        if figs and figs[0].scope not in scopes:
            scopes.add(figs[0].scope)
            out += figs
    return out


# ---------------------------------------------------------------- database

RESULT_FILINGS = """SELECT p.publication_id, p.issuer_id, p.published_at, ta.text_artifact_id, ta.document_version_id
      FROM document_publications p JOIN text_artifacts ta USING (document_version_id)
     WHERE (p.title ~* 'financial results?|\\s-\\s*results\\s*-|\\mresults? for the|unaudited|audited'
            OR p.original_category ~* '^\\s*results?\\s*$|financial result'
            -- results are often filed as the board meeting's outcome ("Outcome Of The Board Meeting For The Half Year")
            OR (p.title ~* 'board meeting outcome|outcome of (the )?board meeting'
                AND p.title ~* 'results?|quarter|half[- ]?year|year ended|financial'))
       AND p.title !~* 'voting|ballot|scrutini|intimation|newspaper|trading window|press release|clarification|postpone' AND coalesce(p.original_category,'') !~* 'clarification|xbrl'
       AND p.pipeline_state IN ('TEXT_READY','PARTIAL_TEXT') AND p.issuer_id IS NOT NULL AND p.published_at IS NOT NULL
       AND ta.status IN ('COMPLETE','PARTIAL')"""


def _pages(conn, tid) -> list[tuple[int, str]]:
    return conn.execute("SELECT page_no, body FROM text_pages WHERE text_artifact_id=%s ORDER BY page_no", (tid,)).fetchall()


def check(conn, limit: int = 300) -> dict:
    """Agreement with XBRL figures for the same issuer, period, scope and metric (filings that have both)."""
    rows = conn.execute(RESULT_FILINGS + """ AND EXISTS (SELECT 1 FROM financial_facts x WHERE x.issuer_id=p.issuer_id
            AND x.provider='nse_xbrl' AND x.period_end BETWEEN p.published_at::date - 100 AND p.published_at::date)
         ORDER BY md5(p.publication_id::text) LIMIT %s""", (limit,)).fetchall()
    c = Counter(); bad = []
    for pid, iss, at, tid, _ in rows:
        figs = read_document(_pages(conn, tid))
        c['filings'] += 1; c['filings_read'] += bool(figs)
        for f in figs:
            x = conn.execute("""SELECT value FROM financial_facts WHERE issuer_id=%s AND provider='nse_xbrl' AND metric=%s
                AND period_type=%s AND period_end=%s AND scope=%s AND value IS NOT NULL
                AND (period_type<>'QUARTER' OR NOT cumulative) LIMIT 1""",
                             (iss, f.metric, f.period_type, f.period_end, f.scope)).fetchone()
            if not x:
                c['no_xbrl_twin'] += 1; continue
            ok = abs(f.value - x[0]) <= max(Decimal('0.01') * abs(x[0]), Decimal(10) ** 5)
            c['compared'] += 1; c['agree'] += ok
            c['compared_' + f.metric] += 1; c['agree_' + f.metric] += ok
            if not ok and len(bad) < 15:
                bad.append(dict(publication_id=str(pid), metric=f.metric, end=str(f.period_end), scope=f.scope,
                                text=str(f.value), xbrl=str(x[0]), line=f.original_text[:120]))
    c = dict(c); c['agreement'] = round(c.get('agree', 0) / c['compared'], 4) if c.get('compared') else None
    return dict(counts=c, disagreements=bad)


def _hash(pid, f: Figure) -> str:
    key = "|".join(str(x) for x in (PROVIDER_VERSION, pid, f.metric, f.period_type, f.period_end, f.scope, f.original_text))
    return hashlib.sha256(key.encode()).hexdigest()


def load(conn, limit: Optional[int] = None, issuers: Optional[list[str]] = None, dry_run: bool = False) -> dict:
    """Write figures from results filings for cells no XBRL figure covers.  Idempotent per filing figure."""
    sql = RESULT_FILINGS + (" AND p.issuer_id = ANY(%(iss)s::uuid[])" if issuers else "") + \
        " ORDER BY p.published_at" + (" LIMIT %(limit)s" if limit else "")
    rows = conn.execute(sql, dict(iss=issuers, limit=limit)).fetchall()
    c = Counter()
    for pid, iss, at, tid, vid in rows:
        figs = read_document(_pages(conn, tid))
        c['filings'] += 1; c['filings_read'] += bool(figs)
        for f in figs:
            if f.period_end >= at.date():
                c['skipped_period_not_ended'] += 1; continue
            h = _hash(pid, f)
            exists = conn.execute("""SELECT 1 FROM financial_facts WHERE issuer_id=%s AND metric=%s AND period_type=%s
                AND period_end=%s AND scope=%s AND (provider='nse_xbrl' OR content_hash=%s) LIMIT 1""",
                                  (iss, f.metric, f.period_type, f.period_end, f.scope, h)).fetchone()
            if exists:
                c['skipped_already_known'] += 1; continue
            c['issuers'] = c.get('issuers', 0)
            if dry_run:
                c['would_write'] += 1; c.setdefault('_issuers', set()).add(str(iss)); continue
            conn.execute("""INSERT INTO financial_facts (issuer_id, metric, period_start, period_end, scope, value, value_kind,
                currency, scale, original_text, period_type, cumulative, available_at, provider, provider_version,
                document_version_id, publication_id, content_hash, created_by)
                VALUES (%s,%s,%s,%s,%s,%s,'MONEY','INR','UNITS',%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                         (iss, f.metric, f.period_start, f.period_end, f.scope, f.value, f.original_text, f.period_type,
                          f.period_type in ('HALF_YEAR', 'NINE_MONTHS'),
                          at, PROVIDER, PROVIDER_VERSION, vid, pid, h, CREATED_BY))
            c['written'] += 1
    out = {k: v for k, v in c.items() if not k.startswith('_')}
    out['issuers_gaining'] = len(c.get('_issuers', ()))
    return out


def main(argv: Optional[list[str]] = None) -> int:
    import psycopg
    ap = argparse.ArgumentParser(prog="python -m inflection.results_text")
    ap.add_argument("command", choices=["check", "load"])
    ap.add_argument("--limit", type=int)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    with psycopg.connect(os.environ["INFLECTION_DSN"], autocommit=True) as conn:
        res = check(conn, a.limit or 300) if a.command == "check" else load(conn, a.limit, dry_run=a.dry_run)
    print(json.dumps(res, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
