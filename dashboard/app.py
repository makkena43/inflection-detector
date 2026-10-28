"""Local dashboard for the inflection backtest: run progress, picks by year, and a company page.

    ~/PycharmProjects/inflection-detector/.venv/bin/python ~/inflection-jobs/ui/app.py   ->  http://127.0.0.1:8765
Reads the local Postgres database (read-only queries) and the job logs; serves on localhost only.
"""
import json, math, os, re, statistics, subprocess, time
from datetime import date, datetime, timedelta
from decimal import Decimal
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import psycopg
import combo_flags
import sys
sys.path.insert(0, os.path.expanduser("~/PycharmProjects/inflection-detector/src"))
from inflection import orderbook, shareholding, audit, process_health, snapshots   # noqa: E402

DSN = os.environ.get("INFLECTION_DSN", "postgresql:///inflection")
J = os.path.expanduser(os.environ.get("INFLECTION_JOB_ROOT", "~/inflection-jobs")) + "/"
HERE = os.path.dirname(os.path.abspath(__file__))
KEEP = ['updates', 'press release', 'investor presentation', 'analysts/institutional investor meet/con. call updates',
        'company update', 'analyst / investor meet', 'press release / media release', 'award of order / receipt of order',
        'memorandum of understanding /agreements']
KEEP_2026 = KEEP + ['result', 'financial result updates', 'financial results',
        'outcome of board meeting', 'integrated filing- financial', 'board meeting outcome']
_cache = {}
OUTLOOK = J + "insights/outlook_2021_2026.csv"


def outlook(iss):
    """Management guidance sentences for one company (insights/outlook_extract.py output)."""
    def load():
        import csv
        by = {}
        if os.path.exists(OUTLOOK):
            for r in csv.DictReader(open(OUTLOOK)):
                by.setdefault(r["issuer_id"], []).append({k: r[k] for k in ("published_at", "category", "kind", "sentence")})
        return by
    return sorted(cached("outlook", 3600, load).get(iss, []), key=lambda r: r["published_at"], reverse=True)


def cached(key, ttl, fn):
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < ttl:
        return hit[1]
    val = fn(); _cache[key] = (time.time(), val); return val


def q(sql, args=()):
    with psycopg.connect(DSN) as c:
        cur = c.execute(sql, args)
        cols = [d.name for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]


def enc(o):
    if isinstance(o, Decimal): return float(o)
    if isinstance(o, (date, datetime)): return o.isoformat()
    return str(o)


def json_safe(value):
    """Emit valid JSON: missing/non-finite financial numbers are null, never NaN/Infinity."""
    if isinstance(value, Decimal):
        return float(value) if value.is_finite() else None
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {key: json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    return value


def log_months(path, pat):
    out = {}
    if os.path.exists(path):
        for line in open(path, errors="ignore"):
            m = re.search(pat, line)
            if m: out[m.group(1)] = line[:19]
    return out


JOBS = {"weekly_loop.sh": "Weekly triage (local engine)", "run_downloads.sh": "Downloads",
        "run_backfill": "Monthly processing", "run_2026.sh": "2026 run", "run_resume.sh": "Resume run",
        "run_bse_backfill.sh": "BSE-only backfill", "fill_fin_2526.sh": "Financials 2025-26 load",
        "inflection.ingest": "Listing filings", "inflection.financials": "Financials (XBRL)", "outlook_extract": "Guidance extraction"}


def running():
    try:
        ps = subprocess.run(["ps", "-axo", "command"], capture_output=True, text=True, timeout=5).stdout
    except Exception:
        return []
    return sorted({label for key, label in JOBS.items() if any(key in line and "caffeinate" not in line for line in ps.splitlines())})


def resume():
    if "Resume run" in running() or "2026 run" in running():
        return {"started": False, "message": "A run is already going; nothing new was started."}
    subprocess.Popen(["caffeinate", "-ims", "zsh", J + "run_resume.sh"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     start_new_session=True)
    _cache.pop("status", None)
    return {"started": True, "message": "Started: list new filings, download, then process complete months."}


def status():
    sql = """SELECT to_char(p.published_at AT TIME ZONE 'Asia/Kolkata', 'YYYY-MM') AS month, count(*) AS listed,
                    count(*) FILTER (WHERE lower(coalesce(p.original_category, p.original_subcategory, '')) = ANY(%(k)s)
                                       OR lower(coalesce(p.original_subcategory, '')) = ANY(%(k)s)) AS key_files,
                    count(*) FILTER (WHERE (lower(coalesce(p.original_category, p.original_subcategory, '')) = ANY(%(k)s)
                                       OR lower(coalesce(p.original_subcategory, '')) = ANY(%(k)s))
                                       AND p.pipeline_state <> 'DISCOVERED') AS key_downloaded,
                    max(p.published_at) AS last_filing
               FROM document_publications p JOIN sources s USING (source_id)
              WHERE s.name LIKE '%%announce%%' AND p.published_at >= %(lo)s AND p.published_at < %(hi)s
              GROUP BY 1 ORDER BY 1"""
    # key files: the fast-mode download list for 2021-2025; 2026 also downloads results and board outcomes
    rows = q(sql, {"k": KEEP, "lo": "2021-01-01", "hi": "2026-01-01"}) + q(sql, {"k": KEEP_2026, "lo": "2026-01-01", "hi": "2100-01-01"})
    processed = log_months(J + "logs/backfill.log", r" (\d{4}-\d{2}) done")
    for m in ("2021-01", "2021-02", "2021-03", "2021-04", "2021-05"):    # run by hand before the month driver existed
        processed.setdefault(m, "manual run")
    weeks = log_months(J + "logs/weekly.log", r"^(\d{4}-\d{2}-\d{2}) done")
    reviewed = {r["m"]: r["n"] for r in q("""SELECT to_char(week_start, 'YYYY-MM') m, count(*) n FROM triage_review_results
                                              WHERE decided_by NOT LIKE 'local engine%%' GROUP BY 1""")}
    picks = {r["m"]: r["n"] for r in q("""SELECT to_char(week_start, 'YYYY-MM') m, count(*) n FROM triage_review_results
                                           WHERE is_pick GROUP BY 1""")}
    for r in rows:
        m = r["month"]
        r["processed"] = processed.get(m)
        r["weeks_triaged"] = sum(1 for w in weeks if w.startswith(m))
        r["model_reviewed"] = reviewed.get(m, 0)
        r["picks"] = picks.get(m, 0)
    last = lambda d: max(d) if d else None
    px = q("SELECT max(trade_date) d FROM prices WHERE provider = 'nse_bhavcopy'")[0]["d"]
    fin = q("SELECT max(period_end) d FROM financial_facts_asof WHERE value IS NOT NULL")[0]["d"]
    return {"months": rows, "summary": {
        "last_filing_listed": last([r["last_filing"] for r in rows if r["last_filing"]]),
        "last_month_processed": last([m for m in processed]),
        "last_week_triaged": last(list(weeks)),
        "last_prices": px, "last_financial_quarter": fin,
        "generated": datetime.now().isoformat(timespec="seconds"), "running": running()}}


def runup(sec, d):
    r = q("""SELECT (SELECT close FROM prices_split_bonus_adjusted WHERE security_id=%(s)s AND provider='nse_bhavcopy' AND close>0
                       AND trade_date BETWEEN %(d)s AND %(d)s::date+10 ORDER BY trade_date LIMIT 1) p0,
                    (SELECT close FROM prices_split_bonus_adjusted WHERE security_id=%(s)s AND provider='nse_bhavcopy' AND close>0
                       AND trade_date BETWEEN %(d)s::date-192 AND %(d)s::date-182 ORDER BY trade_date DESC LIMIT 1) pm""",
          {"s": sec, "d": d})[0]
    return float(r["p0"]) / float(r["pm"]) - 1 if r["p0"] and r["pm"] else None


def financial_metrics(iss, cutoff):
    def calculate():
        with psycopg.connect(DSN, options='-c default_transaction_read_only=on') as conn:
            return snapshots.metrics(conn, iss, cutoff)
    return cached(f'financial-metrics:{iss}:{cutoff}', 1800, calculate)


def ttm_margin(iss, wk):
    return financial_metrics(iss, wk)['pat_margin']


def category(size, ru, m0):
    size = size or 0
    if size >= 100: return "A: order ≥100% of revenue"
    if size >= 25 and ru is not None and ru > 0.6: return "B: order ≥25% + run-up >60%"
    if size >= 25 and m0 is not None and m0 < 0.05: return "C: low margin + order ≥25%"
    return "Other pick"


def mcap_cr(sec, iss, wk, e):
    fin = financial_metrics(iss, wk)['snapshot']
    shares = fin.get('shares', {}).get('base')
    if shares is None: return None
    rows = q("""SELECT close FROM prices WHERE security_id=%s AND provider='nse_bhavcopy'
        AND adjustment='UNADJUSTED' AND trade_date BETWEEN %s AND %s::date+10 AND close>0
        ORDER BY trade_date,recorded_at DESC,provider_version DESC LIMIT 1""", (sec,e,e))
    return float(rows[0]['close']) * float(shares) / 1e7 if rows else None


def ttm_revenue_cr(iss, wk):
    return financial_metrics(iss, wk)['revenue_cr']


SCALE_CR = {"UNITS": 1e-7, "THOUSAND": 1e-4, "LAKH": 0.01, "MILLION": 0.1, "CRORE": 1, "BILLION": 100}
# A passage that reports orders won over a period, or several orders at once, rather than one order.
PERIOD_TOTAL = re.compile(r"\b(?:in|during|for|of|till|until|so far in)\s+(?:the\s+)?(?:H1|H2|9M|9 ?months|nine months|six months|"
    r"first half|second half|half[- ]year|first quarter|quarter|year|period|FY\s?'?\s?\d{2,4}|Q[1-4])\b|year[- ]to[- ]date|\bYTD\b|"
    r"\bso far\b|till date|\bto date\b|as (?:of|on) date|current (?:financial )?(?:year|quarter)|this (?:financial )?year|annual target|"
    r"during [A-Z][a-z]+(?: \d{4})? (?:to|-) [A-Z][a-z]+|cumulative|aggregat|\btotal\b|order inflow|\binflows?\b|"
    r"\b(?:\d+|two|three|four|five|six|seven|eight|nine|ten|several|multiple|various)\s+(?:new\s+|large\s+|long[- ]term\s+|major\s+)*"
    r"(?:contracts|orders|deals|projects|work orders)\b", re.I)
# Order book / backlog figures are not orders won in the period.
ORDER_BOOK = re.compile(r"order ?book|backlog|unexecuted|pending orders|outstanding orders|orders? in hand", re.I)
WON = re.compile(r"\b(?:secured|received|won|bagged|bags|awarded|order inflow)\b", re.I)
REPEAT_DAYS = 90
MAX_X_REVENUE = 4   # a figure above 4x TTM revenue is almost always another company's, an order book, or a size band


def order_inflow(iss):
    """Firm orders found in filings, each tagged as a single order, a period/aggregate total, or a repeat.

    Single orders repeated within 90 days at about the same value (exchange letter, then presentation) count once.
    Foreign-currency orders are converted at the last ECB rate on or before publication (dashboard_fx_rates); one
    with no rate is kept as kind 'no FX rate' with cr None, so it is listed but never counted."""
    rows = q("""SELECT m.published_at, m.amount, m.scale, coalesce(m.currency,'INR') currency, r.event_id, m.quote, m.source_url, m.page_no,
                       coalesce(t.months, (m.details->>'duration_months')::numeric) duration_months,
                       CASE WHEN coalesce(m.currency,'INR') <> 'INR' THEN
                         (SELECT x.inr_per_unit FROM dashboard_fx_rates x WHERE x.currency=m.currency
                           AND x.rate_date <= (m.published_at AT TIME ZONE 'Asia/Kolkata')::date ORDER BY x.rate_date DESC LIMIT 1) END fx
                  FROM commercial_mentions m LEFT JOIN commercial_resolutions r USING (mention_id)
                  LEFT JOIN dashboard_order_terms t USING (mention_id)
                 WHERE m.issuer_id=%s AND m.family='ORDER' AND m.commercial_stage='BINDING_DEMAND' AND m.modality='REALIZED'
                   AND m.amount_basis IN ('FIRM','EXECUTABLE_RELEASE') AND m.amount > 0
                   AND m.lifecycle IS NULL AND coalesce(r.outcome,'') <> 'NOT_AN_EVENT'
                 ORDER BY m.published_at""", (iss,))
    out, seen_events = [], set()
    for r in rows:
        cur, fx = r["currency"], float(r["fx"]) if r["fx"] else None
        cr = float(r["amount"]) * SCALE_CR.get(r["scale"], 1) * (fx if cur != "INR" else 1) if cur == "INR" or fx else None
        d = r["published_at"].date()
        quote = re.sub(r"\s+", " ", r["quote"])
        orig = {} if cur == "INR" else {"currency": cur, "orig_amount": float(r["amount"]), "orig_scale": r["scale"], "fx_rate": fx}
        if cr is None:
            out.append(dict(orig, d=d, cr=None, kind="no FX rate", months=None, quote=quote[:300], source_url=r["source_url"], page_no=r["page_no"]))
            continue
        kind = "order book" if ORDER_BOOK.search(quote) and not WON.search(quote) else "period total" if PERIOD_TOTAL.search(quote) else "single"
        # a converted figure drifts with the rate and the company's own rounding, so foreign orders match within 5%
        if kind == "single" and (r["event_id"] in seen_events or any(
                o["kind"] == "single" and (d - o["d"]).days <= REPEAT_DAYS
                and abs(o["cr"] - cr) <= (0.05 if orig or o.get("currency") else 0.02) * max(o["cr"], cr)
                for o in out)):
            kind = "repeat"
        if r["event_id"]: seen_events.add(r["event_id"])
        # a term only means something for one order; "9 months FY26" on a period total is the reporting period
        months = None if kind != "single" else float(r["duration_months"]) if r["duration_months"] else term_months(quote)
        out.append(dict(orig, d=d, cr=cr, kind=kind, months=months, quote=quote[:300], source_url=r["source_url"], page_no=r["page_no"]))
    return out


NUM = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
       "twelve": 12, "fifteen": 15, "eighteen": 18, "twenty": 20, "twenty four": 24, "thirty six": 36}
_N = r"(\d{1,3}|" + "|".join(sorted(NUM, key=len, reverse=True)) + r")"
TERM = re.compile(r"\b(?:over|within|in|for|spread over|period of|tenure of|term of|duration of|ranging from|from)\s+(?:a\s+|the\s+)?(?:next\s+)?"
                  r"(?:period\s+of\s+)?(?:" + _N.replace("(", "(?:", 1) + r"\s*(?:to|-|–)\s*)?" + _N + r"\s*(?:\([^)]{1,15}\)\s*)?(months?|years?)\b", re.I)


def term_months(quote):
    """Execution period stated in the passage ("over five years", "within 18 months"), in months; the upper end of a range."""
    m = TERM.search(quote)
    if not m: return None
    n = int(m.group(1)) if m.group(1).isdigit() else NUM[m.group(1).lower()]
    n = n * 12 if m.group(2).lower().startswith("year") else n
    return n if 0 < n <= 240 else None


def execution_years(counted, rev, assume=24):
    """Split counted orders (item, Rs crore) into what is executable in years 1, 2, 3 and later from the order date,
    evenly over the stated term. Orders with no stated term are shown apart and assumed to run `assume` months
    in the year-1 figure used on the picks table."""
    yrs, unknown = [0.0, 0.0, 0.0, 0.0], 0.0
    for o, cr in counted:
        if not o.get("months"):
            unknown += cr; continue
        m = o["months"]
        for k in range(3): yrs[k] += cr * max(0.0, min(12 * (k + 1), m) - 12 * k) / m
        yrs[3] += cr * max(0.0, m - 36) / m
    pc = lambda v: round(100 * v / rev, 1) if rev else None
    y1_est = yrs[0] + unknown * min(12, assume) / assume
    return {"y1_cr": yrs[0], "y2_cr": yrs[1], "y3_cr": yrs[2], "later_cr": yrs[3], "unknown_term_cr": unknown,
            "y1_pct": pc(yrs[0]), "y2_pct": pc(yrs[1]), "y3_pct": pc(yrs[2]), "later_pct": pc(yrs[3]), "unknown_pct": pc(unknown),
            "y1_est_pct": pc(y1_est) if (yrs[0] or unknown) else None}


def period_span(t):
    """Rough dates a stated period total covers: a full year ends about two months before it is published (FY25 total
    in May 2025); H1/9M/quarter likewise; year-to-date runs from 1 April to publication."""
    d, x = t["d"], t["quote"]
    fy_start = date(d.year if d.month >= 4 else d.year - 1, 4, 1)
    if re.search(r"so far|till date|to date|as (?:of|on) date|current (?:financial )?year|this (?:financial )?year|year[- ]to[- ]date|\bYTD\b", x, re.I):
        return fy_start, d
    for pat, days in ((r"\bQ[1-4]\b|quarter", 91), (r"\bH[12]\b|six months|half", 182), (r"9 ?M\b|9 ?months|nine months", 273)):
        if re.search(pat, x, re.I): return d - timedelta(days=60 + days), d - timedelta(days=60)
    if re.search(r"\bFY|during the year|for the year|annual", x, re.I): return d - timedelta(days=60 + 365), d - timedelta(days=60)
    return d, d + timedelta(days=1)   # aggregate of recent orders ("won 4 deals"): treat as dated at publication


def orders_12m(orders, asof, rev=None, items=False, incl_big=False):
    """New firm order value over the 12 months to asof, Rs crore (figures above MAX_X_REVENUE x rev are left out
    unless incl_big). Orders with no INR value (no FX rate) are never counted.

    A company-stated period total already contains the single orders announced before it, so the figure is the
    larger of (sum of single orders) and (a stated total + the single orders announced after it); a stated total is
    pro-rated by how much of its period falls inside the 12 months."""
    win = [o for o in orders if o["cr"] is not None and asof - timedelta(days=365) < o["d"] <= asof
           and (incl_big or not (rev and o["cr"] > MAX_X_REVENUE * rev))]
    singles = [o for o in win if o["kind"] == "single"]
    best, basis, chosen = sum(o["cr"] for o in singles), "single orders", [(o, o["cr"]) for o in singles]
    for t in (o for o in win if o["kind"] == "period total"):
        start, end = period_span(t)
        inside = (end - max(start, asof - timedelta(days=365))).days / max((end - start).days, 1)
        part = t["cr"] * min(1, max(0, inside))
        v = part + sum(o["cr"] for o in singles if o["d"] > t["d"])
        if v > best:
            best, basis = v, f"stated total of {t['cr']:,.0f} cr on {t['d']} (pro-rated to the 12 months) + later single orders"
            chosen = [(t, part)] + [(o, o["cr"]) for o in singles if o["d"] > t["d"]]
    return ((best or None), basis, chosen) if items else ((best or None), basis)


def mgmt_target_multiple(iss, wk, rev):
    """Largest revenue target for a named year (concall/presentation, previous 9 months) as a multiple of TTM revenue."""
    if not rev: return None
    def load():
        import csv
        by = {}
        if os.path.exists(OUTLOOK):
            for r in csv.DictReader(open(OUTLOOK)):
                if r["kind"] == "REVENUE_TARGET" and r["amount_cr"] and r["target_fy"]:
                    by.setdefault(r["issuer_id"], []).append((r["published_at"][:10], float(r["amount_cr"]), int(float(r["target_fy"]))))
        return by
    best = None
    for d, amt, fy in cached("targets", 3600, load).get(str(iss), []):
        dd = date.fromisoformat(d)
        if wk - timedelta(days=270) <= dd <= wk + timedelta(days=7) and dd.year <= fy <= dd.year + 5:
            m = amt / rev
            if 1 < m < 10: best = max(best or 0, m)
    return best


def listing_keys(iss):
    """(exchange, symbol) to match insider/deal rows: the NSE symbol when listed on NSE, else the BSE scrip code
    (dual-listed companies disclose the same trades on both exchanges, so only one side is counted)."""
    ids = q("""SELECT h.exchange, h.kind, h.value FROM securities s JOIN identifier_history h USING (security_id)
               WHERE s.issuer_id=%s AND h.valid_to IS NULL""", (iss,))
    nse = [r["value"] for r in ids if r["exchange"] == "NSE" and r["kind"] == "SYMBOL"]
    if nse: return "NSE", nse
    return "BSE", [r["value"] for r in ids if r["exchange"] == "BSE"]


BUY, SELL = r"^(buy|acqui)", r"^(sell|dispos)"


def flows(iss, lo, hi):
    """Net promoter buying (insider disclosures) and institutional net buying (bulk/block deals), Rs crore."""
    ex, syms = listing_keys(iss)
    if not syms: return None, None
    p = q("""SELECT coalesce(sum(CASE WHEN transaction_type ~* %(b)s THEN value_inr WHEN transaction_type ~* %(s)s THEN -value_inr ELSE 0 END), 0)/1e7 v
               FROM insider_trades WHERE exchange=%(ex)s AND symbol = ANY(%(sy)s) AND coalesce(trade_to, trade_from) BETWEEN %(lo)s AND %(hi)s
                AND person_category ~* 'promoter'""", dict(b=BUY, s=SELL, ex=ex, sy=syms, lo=lo, hi=hi))[0]["v"]
    i = q("""SELECT coalesce(sum(CASE WHEN side LIKE 'B%%' THEN 1 ELSE -1 END * quantity * price), 0)/1e7 v FROM bulk_block_deals
              WHERE exchange=%(ex)s AND symbol = ANY(%(sy)s) AND trade_date BETWEEN %(lo)s AND %(hi)s AND client_name ~* %(r)s""",
          dict(ex=ex, sy=syms, lo=lo, hi=hi, r=INST))[0]["v"]
    return float(p), float(i)


INST = (r"mutual fund|\yfund\y|insurance|assurance|pension|\yamc\y|asset management|societe generale|goldman|morgan stanley|bnp paribas|"
        r"citigroup|nomura|abu dhabi|government of singapore|monetary authority|vanguard|norges|hsbc|jp ?morgan|blackrock|fidelity|"
        r"\yfpi\y|\yaif\y|alternative investment|investment fund")


def op_margin(iss, wk):
    """Shared comparable financials; liquidity counts each security-day once."""
    values = financial_metrics(iss, wk)
    rows = q("""SELECT avg(close*volume)/1e7 v FROM (
        SELECT DISTINCT ON (p.security_id,p.trade_date) p.security_id,p.trade_date,p.close,p.volume
        FROM prices p JOIN securities s USING(security_id) WHERE s.issuer_id=%s
        AND p.provider='nse_bhavcopy' AND p.adjustment='UNADJUSTED'
        AND p.trade_date BETWEEN %s::date-90 AND %s AND p.volume>0
        ORDER BY p.security_id,p.trade_date,p.recorded_at DESC,p.provider_version DESC) daily""", (iss,wk,wk))
    liq=rows[0]['v'] if rows else None
    return values['opm'],values['opm_change'],values['revenue_growth'],float(liq) if liq is not None else None


def excess_36m(sec, entry):
    """Match the existing outcome convention: entry +14d, 1095d, first close within 10d."""
    if not sec: return (None, None)
    end = entry + timedelta(days=1095)
    prices = q("""SELECT
        (SELECT close FROM prices_split_bonus_adjusted WHERE security_id=%s AND provider='nse_bhavcopy'
         AND trade_date BETWEEN %s AND %s AND close>0 ORDER BY trade_date LIMIT 1) a,
        (SELECT close FROM prices_split_bonus_adjusted WHERE security_id=%s AND provider='nse_bhavcopy'
         AND trade_date BETWEEN %s AND %s AND close>0 ORDER BY trade_date LIMIT 1) b""",
        (sec, entry, entry + timedelta(days=10), sec, end, end + timedelta(days=10)))[0]
    if not prices['a'] or not prices['b']: return (None, None)
    def market():
        r = q("""WITH a AS (
          SELECT DISTINCT ON (security_id) security_id, close FROM prices_split_bonus_adjusted
          WHERE provider='nse_bhavcopy' AND trade_date BETWEEN %s AND %s AND close>0 ORDER BY security_id, trade_date),
        b AS (SELECT DISTINCT ON (security_id) security_id, close FROM prices_split_bonus_adjusted
          WHERE provider='nse_bhavcopy' AND trade_date BETWEEN %s AND %s AND close>0 ORDER BY security_id, trade_date)
        SELECT b.close/a.close-1 AS ret FROM a JOIN b USING(security_id)""",
        (entry, entry + timedelta(days=10), end, end + timedelta(days=10)))
        return statistics.median(float(x['ret']) for x in r) if r else None
    benchmark = cached(f'median36:{entry}', 1800, market)
    stock_return = float(prices['b']) / float(prices['a']) - 1
    return stock_return, benchmark


def holding_changes(issuer, entry):
    """Latest consecutive-quarter ownership change published before entry (IST midnight)."""
    history = q("""SELECT DISTINCT ON (period_end) period_end, broadcast_at, promoter_pct, fii_pct
        FROM shareholding_patterns WHERE issuer_id=%s
        AND (extract(month FROM period_end), extract(day FROM period_end)) IN ((3,31),(6,30),(9,30),(12,31))
        AND broadcast_at < %s::date::timestamp AT TIME ZONE 'Asia/Kolkata'
        AND period_end < %s ORDER BY period_end DESC, broadcast_at DESC, source_ref DESC""", (issuer, entry, entry))
    result = dict(holding_period=None, holding_previous_period=None, promoter_holding_pct=None,
                  fii_holding_pct=None, promoter_change_pp=None, fii_change_pp=None,
                  holding_year_ago_period=None, promoter_yoy_pp=None, fii_yoy_pp=None)
    if not history: return result
    latest = history[0]
    result.update(holding_period=latest['period_end'], holding_published_at=latest['broadcast_at'],
                  promoter_holding_pct=latest['promoter_pct'], fii_holding_pct=latest['fii_pct'])
    quarter = lambda d: d.year * 4 + (d.month - 1) // 3
    if (entry-latest['period_end']).days <= 180:
        # Same quarter a year earlier; if it was not filed the change is unknown.
        ago = next((h for h in history[1:] if quarter(latest['period_end']) - quarter(h['period_end']) == 4), None)
        if ago:
            result['holding_year_ago_period'] = ago['period_end']
            for field in ('promoter', 'fii'):
                a, z = latest[field+'_pct'], ago[field+'_pct']
                if a is not None and z is not None:
                    result[field+'_yoy_pp'] = round(float(a)-float(z), 4)
    # Missing previous quarter is unknown; never substitute a different interval or a missing value with zero.
    if len(history)<2: return result
    previous = history[1]
    if quarter(latest['period_end'])-quarter(previous['period_end']) != 1: return result
    if (entry-latest['period_end']).days > 180: return result
    result['holding_previous_period'] = previous['period_end']
    for field in ('promoter','fii'):
        a, z = latest[field+'_pct'], previous[field+'_pct']
        if a is not None and z is not None:
            result[field+'_change_pp'] = round(float(a)-float(z), 4)
    return result


AMT = re.compile(r"([\d,.]+)\s+([A-Z]{3})\s+([A-Z]+)")


def fx_inr(cur, d):
    """INR per unit of `cur` at the last ECB rate on or before d (dashboard_fx_rates)."""
    if cur == "INR": return 1.0
    r = q("SELECT inr_per_unit FROM dashboard_fx_rates WHERE currency=%s AND rate_date <= %s ORDER BY rate_date DESC LIMIT 1", (cur, d))
    return float(r[0]["inr_per_unit"]) if r else None


def review_order(review_id, size, rev):
    """Order size in Rs crore for a pick, by what the review itself used: (a) the amount of the order event the review
    cites (its packet lists it, e.g. "49.86 INR CRORE"; the one nearest size% x revenue when several), (b) size% x the
    TTM revenue in the review's packet, (c) size% x our TTM revenue. Returns (crore, basis)."""
    x = q("""SELECT r.result->'event_ids' ev, p.content->'events' pe, p.content#>>'{financials,ttm,revenue,value}' prev
               FROM triage_reviews r LEFT JOIN triage_packets p USING (packet_id) WHERE r.review_id=%s""", (review_id,))
    x = x[0] if x else {}
    cited = set(x.get("ev") or [])
    prev = float(x["prev"].replace(",", "")) if x.get("prev") else None
    amts = []
    for ev in x.get("pe") or []:
        m = AMT.match(ev.get("amount") or "")
        if ev.get("event_id") in cited and m and m.group(3) in SCALE_CR:
            fx = fx_inr(m.group(2), (ev.get("published_at") or "")[:10] or None)
            if fx: amts.append(float(m.group(1).replace(",", "")) * SCALE_CR[m.group(3)] * fx)
    base = prev or rev
    if amts:
        want = size / 100 * base if size and base else None
        return (min(amts, key=lambda v: abs(v - want)) if want else max(amts)), "review amount"
    if size and prev: return size / 100 * prev, "review denominator"
    if size and rev: return size / 100 * rev, "derived from size % x TTM revenue"
    return None, None


VIEWS = {   # which eligible rows picks() returns
    "year": ("DISTINCT ON (r.issuer_id, extract(year FROM r.week_start))", "r.issuer_id, extract(year FROM r.week_start), r.is_pick DESC, r.week_start"),
    "first": ("DISTINCT ON (r.issuer_id, extract(year FROM r.week_start))", "r.issuer_id, extract(year FROM r.week_start), r.week_start"),
    "latest": ("DISTINCT ON (r.issuer_id, extract(year FROM r.week_start))", "r.issuer_id, extract(year FROM r.week_start), r.week_start DESC"),
    "events": ("", "r.week_start, r.issuer_id"),
}


def picks(year, include, view="year"):
    """view: year = one row per company-year, a pick preferred (default); first / latest = earliest / latest eligible
    row per company-year; events = every eligible row."""
    actions = ["DEEP_RESEARCH"] + (["WATCH_MILESTONE"] if include == "watch" else [])
    distinct, order = VIEWS[view]
    rows = q(f"""SELECT {distinct} r.review_id, r.issuer_id, r.week_start, r.label, r.legal_name, r.triage_action,
                       r.is_pick, r.decided_by, r.rules_version, r.size_pct_of_revenue, r.size_basis, r.firm, r.routine,
                       r.disqualifier, r.confidence, r.rationale, r.excess_6m, r.excess_12m, r.excess_24m, r.return_12m, r.return_24m,
                       (SELECT h.security_id FROM securities s JOIN identifier_history h USING (security_id)
                         WHERE s.issuer_id=r.issuer_id AND h.exchange='NSE' AND h.kind='SYMBOL' ORDER BY h.valid_to NULLS FIRST LIMIT 1) sec
                  FROM triage_review_results r
                 WHERE (%s = 0 OR extract(year FROM r.week_start) = %s) AND r.triage_action = ANY(%s)
                   AND (r.is_pick OR r.triage_action <> 'DEEP_RESEARCH')
                 ORDER BY {order}""", (year, year, actions))
    for r in rows:
        e = r["week_start"] + timedelta(days=14)
        r.update(holding_changes(r["issuer_id"], e))
        r["return_36m"], r["benchmark_36m"] = excess_36m(r["sec"], e)
        r["excess_36m"] = r["return_36m"] - r["benchmark_36m"] if r["return_36m"] is not None and r["benchmark_36m"] is not None else None
        for horizon in (12, 24):
            sr, ex = r.get(f"return_{horizon}m"), r.get(f"excess_{horizon}m")
            r[f"benchmark_{horizon}m"] = float(sr) - float(ex) if sr is not None and ex is not None else None
        r["runup_6m"] = runup(r["sec"], e) if r["sec"] else None
        r["margin_ttm"] = ttm_margin(r["issuer_id"], r["week_start"])
        r["category"] = category(r["size_pct_of_revenue"] and float(r["size_pct_of_revenue"]), r["runup_6m"], r["margin_ttm"]) \
            if r["is_pick"] else "Watchlist"
        rev = ttm_revenue_cr(r["issuer_id"], r["week_start"])
        mc = mcap_cr(r["sec"], r["issuer_id"], r["week_start"], e) if r["sec"] else None
        size = r["size_pct_of_revenue"] and float(r["size_pct_of_revenue"])
        # order % mcap (score, R3) stays on size % x TTM revenue so the combos do not move; order_cr is the review's own figure
        r["order_cr_derived"] = size / 100 * rev if size and rev else None
        r["order_cr"], r["order_cr_basis"] = review_order(r["review_id"], size, rev)
        r["mcap_cr"] = mc
        orders = order_inflow(r["issuer_id"])
        asof = r["week_start"] + timedelta(days=6)
        o12, _, chosen = orders_12m(orders, asof, rev, items=True)
        r["orders_12m_pct"] = round(100 * o12 / rev, 1) if o12 and rev else None
        r["orders_y1_pct"] = execution_years(chosen, rev)["y1_est_pct"] if o12 and rev else None
        o12b, _ = orders_12m(orders, asof, rev, incl_big=True)
        r["orders_12m_incl_big_pct"] = round(100 * o12b / rev, 1) if o12b and rev else None
        r["order_to_mcap"] = r["order_cr_derived"] / mc if r["order_cr_derived"] and mc else None
        r["mgmt_target_x"] = mgmt_target_multiple(r["issuer_id"], r["week_start"], rev)
        r["promoter_net_cr"], r["inst_net_cr"] = flows(r["issuer_id"], r["week_start"] - timedelta(days=90), e)
        with psycopg.connect(DSN) as cc:   # one technical check, shared with the combos
            psec, prov = combo_flags.price_source(cc, r["issuer_id"], r["sec"], e)
            t = combo_flags.price_checks(cc, psec, e, prov) if psec else None
        r["tech"] = t
        r["tech_score"] = t["n"] if t else None
        r["price_date"], r["exchange"] = (t["price_date"], t["exchange"]) if t else (None, None)
        flags = []
        if r["order_to_mcap"] and r["order_to_mcap"] >= 0.25: flags.append("Order ≥25% of mcap")
        if r["mgmt_target_x"] and r["mgmt_target_x"] >= 2: flags.append("Mgmt target ≥2x revenue")
        if r["promoter_net_cr"] and r["promoter_net_cr"] >= 1: flags.append("Promoter bought ≥₹1 cr")
        if r["promoter_net_cr"] and r["promoter_net_cr"] <= -1: flags.append("Promoter sold ≥₹1 cr")
        if r["inst_net_cr"] and r["inst_net_cr"] >= 1: flags.append("Institutions bought ≥₹1 cr")
        if r["inst_net_cr"] and r["inst_net_cr"] <= -1: flags.append("Institutions sold ≥₹1 cr")
        if rev and any(o["cr"] is not None and o["cr"] > MAX_X_REVENUE * rev and asof - timedelta(days=365) < o["d"] <= asof for o in orders):
            flags.append("Order >4x revenue: verify")
        if t:
            flags.append(f"Technicals {t['n']}/3")
            if t["below_falling_200"]: flags.append("Below falling 200-day")
        # scorecard (2026-10-20 backtest): 1 point each, minus illiquid / expensive; None = input unknown (scores 0)
        ps = (mc / rev) if mc and rev else None
        opm, opm_chg, revg, liq = op_margin(r["issuer_id"], r["week_start"])
        known = lambda v, test: None if v is None else bool(test(v))
        with psycopg.connect(DSN) as oc:
            ob = orderbook.series(oc, r["issuer_id"], datetime.combine(e, datetime.min.time()), quarters=4)
        last = ob[-1] if ob else {}
        bk = last.get("order_book_cr")
        growing = bool(bk and rev and bk >= rev and ((last.get("book_yoy_pct") or 0) >= 30 or (last.get("inflow_yoy_pct") or 0) >= 30))
        shrinking = (last.get("book_yoy_pct") or 0) < 0
        inputs = {"order_mcap_25": known(r["order_to_mcap"], lambda v: v >= 0.25), "mcap_lt_2000": known(mc, lambda v: v < 2000),
                  "ps_lt_1_5": known(ps, lambda v: v < 1.5), "opm_up_1pp": known(opm_chg, lambda v: v > 0.01),
                  "opm_lt_10": known(opm, lambda v: v < 0.10),
                  "mgmt_target_1_5x": None if not rev else (r["mgmt_target_x"] or 0) >= 1.5,
                  "tech_2_of_3": known(r["tech_score"], lambda v: v >= 2), "revenue_growing": known(revg, lambda v: v > 0),
                  "order_book_growing": growing if bk and rev else None}
        pts = [bool(v) for v in inputs.values()]
        r["order_book"] = last
        if growing: flags.append("Order book growing")
        if shrinking: flags.append("Order book shrinking")
        r["score"] = sum(pts) - (2 if liq is not None and liq < 0.5 else 0) - (1 if ps is not None and ps > 3 else 0)
        r["score_inputs"] = dict(inputs, illiquid_penalty=known(liq, lambda v: v < 0.5), expensive_penalty=known(ps, lambda v: v > 3))
        r["score_known"] = sum(v is not None for v in inputs.values())
        r["score_n"] = len(inputs)
        flags.append(f"Data {r['score_known']}/{r['score_n']} known")
        r["ps"], r["opm"] = ps, opm
        r["signals"] = flags
        with psycopg.connect(DSN) as cc:
            r["combos"], r["combo_checks"] = combo_flags.flags(cc, r, psec, e, t=t) if t else ([], None)
        r.pop("sec")
    rows.sort(key=lambda r: r["week_start"])
    return rows


def engine_queue(days=90):
    """Local-engine DEEP_RESEARCH decisions that no model reviewed (no non-engine review for the same company-week)."""
    return q("""SELECT r.week_start, r.issuer_id, r.label, r.legal_name, r.size_pct_of_revenue, r.size_basis, r.confidence, r.rationale, r.decided_by
                  FROM triage_review_results r
                 WHERE r.triage_action='DEEP_RESEARCH' AND r.decided_by LIKE 'local engine%%'
                   AND (%s = 0 OR r.week_start >= current_date - %s)
                   AND NOT EXISTS (SELECT 1 FROM triage_review_results o WHERE o.issuer_id=r.issuer_id AND o.week_start=r.week_start
                                     AND o.decided_by NOT LIKE 'local engine%%')
                 ORDER BY r.week_start DESC, r.label""", (days, days))


def company(iss):
    info = q("""SELECT i.issuer_id, i.legal_name, i.issuer_model,
                       (SELECT string_agg(DISTINCT h.exchange || ':' || h.value, ', ') FROM securities s JOIN identifier_history h
                          USING (security_id) WHERE s.issuer_id = i.issuer_id) ids FROM issuers i WHERE i.issuer_id = %s""", (iss,))
    if not info: return None
    sec = q("""SELECT h.security_id FROM securities s JOIN identifier_history h USING (security_id) WHERE s.issuer_id=%s
               AND h.exchange='NSE' AND h.kind='SYMBOL' ORDER BY h.valid_to NULLS FIRST LIMIT 1""", (iss,))
    fin = q("""SELECT DISTINCT ON (metric, period_end) metric, period_end, value, scope FROM financial_facts_asof
                WHERE issuer_id=%s AND period_type='QUARTER' AND value IS NOT NULL
                  AND metric IN ('revenue','total_income','pat','eps_basic','finance_cost','depreciation','pbt','tax','employee_cost','other_income')
                ORDER BY metric, period_end, (scope='CONSOLIDATED') DESC, recorded_at DESC""", (iss,))
    quarters = {}
    for f in fin:
        quarters.setdefault(f["period_end"].isoformat(), {"scope": f["scope"]})[f["metric"]] = float(f["value"])
    prices, index = [], []
    if sec:
        prices = q("""SELECT DISTINCT ON (date_trunc('week', trade_date)) trade_date d, close FROM prices_split_bonus_adjusted
                       WHERE security_id=%s AND provider='nse_bhavcopy' AND close>0 AND trade_date >= '2020-01-01'
                       ORDER BY date_trunc('week', trade_date), trade_date DESC""", (sec[0]["security_id"],))
        index = q("""SELECT DISTINCT ON (date_trunc('week', trade_date)) trade_date d, close FROM index_closes
                      WHERE index_name='Nifty Smallcap 250' AND trade_date >= '2020-01-01'
                      ORDER BY date_trunc('week', trade_date), trade_date DESC""")
    reviews = q("""SELECT r.week_start, r.decided_by, r.rules_version, r.triage_action, r.size_pct_of_revenue, r.size_basis, r.firm,
                          r.routine, r.disqualifier, r.confidence, r.rationale, r.is_final, r.result
                     FROM triage_reviews r WHERE r.issuer_id=%s ORDER BY r.week_start DESC, r.is_final DESC LIMIT 200""", (iss,))
    orders, revs = order_inflow(iss), {}
    for r in reviews:
        wk = r["week_start"]
        if wk not in revs: revs[wk] = ttm_revenue_cr(iss, wk)
        tot, basis, chosen = orders_12m(orders, wk + timedelta(days=6), revs[wk], items=True)
        r["orders_y1_pct"] = execution_years(chosen, revs[wk])["y1_est_pct"] if tot and revs[wk] else None
        r["orders_12m_cr"], r["orders_12m_basis"] = tot, basis
        r["orders_12m_pct"] = round(100 * tot / revs[wk], 1) if tot and revs[wk] else None
        res = r.pop("result") or {}
        r["evidence"] = res.get("evidence") or res.get("evidence_refs") or res.get("key_evidence")
        r["missing_information"] = res.get("missing_information")
        r["open_questions"] = res.get("open_questions") or res.get("research_questions")
    events = q("""SELECT m.published_at, m.event_type, m.family, m.commercial_stage, m.amount, m.scale, m.amount_text, m.quote,
                         m.source_url, m.page_no, r.outcome
                    FROM commercial_mentions m LEFT JOIN commercial_resolutions r USING (mention_id)
                   WHERE m.issuer_id=%s AND coalesce(r.outcome, '') <> 'NOT_AN_EVENT'
                   ORDER BY m.published_at DESC LIMIT 300""", (iss,))
    docs = q("""SELECT p.published_at, coalesce(p.original_category, p.original_subcategory) category, p.title, p.attachment_url,
                       p.pipeline_state FROM document_publications p WHERE p.issuer_id=%s
                 ORDER BY p.published_at DESC NULLS LAST LIMIT 300""", (iss,))
    ex, syms = listing_keys(iss)
    deals = q("""SELECT coalesce(trade_to, trade_from) trade_date, 'Insider: ' || coalesce(person_category,'') who, person_name name,
                        transaction_type side, value_inr/1e7 cr
                   FROM insider_trades WHERE exchange=%(ex)s AND symbol = ANY(%(sy)s) AND person_category ~* 'promoter' AND value_inr >= 1e7
                 UNION ALL
                 SELECT trade_date, initcap(kind) || ' deal', client_name, side, quantity*price/1e7 FROM bulk_block_deals
                  WHERE exchange=%(ex)s AND symbol = ANY(%(sy)s) AND quantity*price >= 1e7 AND client_name ~* %(r)s
                 ORDER BY 1 DESC NULLS LAST LIMIT 200""", dict(ex=ex, sy=syms, r=INST)) if syms else []
    with psycopg.connect(DSN) as oc:
        ob = orderbook.series(oc, iss, None, quarters=20)
        shp = shareholding.series(oc, iss, None, quarters=24)
    pli = q("""SELECT approval_date, scheme, tranche, committed_investment_cr, product_segment, source_url
                 FROM pli_beneficiaries WHERE issuer_id=%s ORDER BY approval_date""", (iss,))
    today = date.today()
    rev = ttm_revenue_cr(iss, today)
    tot, basis, chosen = orders_12m(orders, today, rev, items=True)
    for o in orders:
        if rev and o["cr"] is not None and o["cr"] > MAX_X_REVENUE * rev: o["kind"] = "not in total: >4x revenue, verify"
    order_summary = {"total_cr": tot, "basis": basis, "no_fx": [dict(o, d=o["d"].isoformat()) for o in orders if o["kind"] == "no FX rate"], "execution": execution_years(chosen, rev), "ttm_revenue_cr": rev, "pct": round(100 * tot / rev, 1) if tot and rev else None,
                     "orders": [dict(o, d=o["d"].isoformat()) for o in reversed(orders) if o["d"] > today - timedelta(days=730)]}
    return {"info": info[0], "order_summary": order_summary, "order_book": ob, "shareholding": shp, "pli": pli, "deals": deals, "quarters": quarters, "prices": prices, "index": index, "reviews": reviews,
            "events": events, "documents": docs, "outlook": outlook(iss)}


class H(BaseHTTPRequestHandler):
    def send(self, code, body, ctype):
        b = body.encode() if isinstance(body, str) else body
        self.send_response(code); self.send_header("Content-Type", ctype); self.send_header("Content-Length", str(len(b)))
        self.end_headers(); self.wfile.write(b)

    def do_GET(self):
        u = urlparse(self.path); a = parse_qs(u.query)
        try:
            if u.path in ("/", "/index.html"):
                return self.send(200, open(os.path.join(HERE, "index.html"), "rb").read(), "text/html; charset=utf-8")
            if u.path == "/api/status":
                data = cached("status", 300, status)
            elif u.path == "/api/picks":
                yv, inc, view = a.get("year", ["all"])[0], a.get("include", [""])[0], a.get("view", ["year"])[0]
                if view not in VIEWS: return self.send(400, '{"error":"view must be year, events, first or latest"}', "application/json")
                y = 0 if yv == "all" else int(yv)
                data = cached(f"picks{y}{inc}{view}", 1800, lambda: picks(y, inc, view))
            elif u.path == "/api/process_health":
                data = process_health.load_report()
            elif u.path == "/api/detection_audit":
                data = audit.load_report()
            elif u.path == "/api/engine_queue":
                days = int(a.get("days", ["90"])[0])
                data = cached(f"engine{days}", 600, lambda: engine_queue(days))
            elif u.path == "/api/buy":
                sys.path.insert(0, os.path.join(J, "autobuy")); import buy_candidates
                days = int(a.get("days", ["28"])[0])
                data = cached(f"buy{days}", 1800, lambda: buy_candidates.candidates(days))
            elif u.path == "/api/combos":
                data = combo_flags.COMBOS
            elif u.path == "/api/company":
                data = company(a["id"][0])
                if data is None: return self.send(404, '{"error":"not found"}', "application/json")
            else:
                return self.send(404, "not found", "text/plain")
            self.send(200, json.dumps(json_safe(data), default=enc, allow_nan=False), "application/json")
        except Exception as e:
            self.send(500, json.dumps({"error": f"{type(e).__name__}: {e}"}), "application/json")

    def do_POST(self):
        u = urlparse(self.path)
        origin = self.headers.get("Origin") or ""
        if origin and not origin.startswith(("http://127.0.0.1:8765", "http://localhost:8765")):
            return self.send(403, '{"error":"forbidden"}', "application/json")
        if u.path == "/api/resume":
            return self.send(200, json.dumps(resume()), "application/json")
        self.send(404, "not found", "text/plain")

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    print("http://127.0.0.1:8765", flush=True)
    ThreadingHTTPServer(("127.0.0.1", 8765), H).serve_forever()
