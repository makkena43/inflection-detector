"""Emergent themes: discovered from inflection's own order / capacity / launch passages, no fixed list, no LLM.

A theme is a group of product or sector phrases that more and more companies start winning orders for, adding
capacity for, or launching, at the same time.  Every weekly snapshot is computed only from filings public by its
as_of date, so a packet for any past week reads what was knowable then.

1. Phrases (`phrases`): RAKE-style key phrases from each commercial passage (commercial_mentions, families ORDER,
   COMMERCIAL_START, QUALIFICATION, CAPACITY, PRODUCT_LAUNCH): runs of content words between stop words, numbers
   and punctuation, 1-4 words.  Generic filing words are not listed by hand: a phrase used by more than
   GENERIC_SHARE of all companies with passages in the two-year window ("letter of award", "purchase order") is
   treated as generic.
2. Breadth and acceleration: distinct companies naming a phrase in the last RECENT_DAYS vs the same window a year
   earlier (year-on-year, so the results season does not distort it), plus the order value behind it.
3. Grouping: phrases whose company sets overlap (Jaccard >= JOIN) or where one phrase contains the other and most
   companies are shared are merged into one theme (union-find).  The name is the phrase most companies use.
4. Continuity: a theme keeps its key from the previous snapshot when its phrases overlap the old theme's phrases,
   so a theme can be followed week to week and its first detection date is kept.
5. Stage 0-5 by breadth and momentum (MakroGraph's lifecycle thresholds): 0 forming (<4 companies), 1 emerging
   (4-9), 2 accelerating (10-24), 3 consensus (25+), 4 saturating (25+ and growth <= 0), 5 declining (shrinking
   year on year by a third or more).

Everything is counts and set overlaps over the database; nothing is hand-listed except English stop words.
"""
from __future__ import annotations

import re
from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Iterable, Optional
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")
VERSION = "emergent-1"
FAMILIES = ("ORDER", "COMMERCIAL_START", "QUALIFICATION", "CAPACITY", "PRODUCT_LAUNCH")
RECENT_DAYS = 180
WINDOW_DAYS = 730            # phrases and company sets for grouping come from the two years before as_of
GENERIC_SHARE = 0.08         # a phrase used by more than 8% of companies in the window is generic language
GENERIC_FLOOR = 25           # ...but never below 25 companies (small samples)
MIN_COMPANIES = 3            # a theme needs at least this many companies in the recent window
JOIN = 0.5                   # company-set Jaccard for merging two phrases
CONTAIN_SHARE = 0.6          # "transformer" absorbs "power transformer" when 60% of the smaller set is shared
KEEP_KEY = 0.3               # phrase-set Jaccard to keep a theme's key from the previous snapshot
MAX_PHRASE_WORDS = 4
SCALE_TO_CRORE = {"UNITS": Decimal("1e-7"), "THOUSAND": Decimal("1e-4"), "LAKH": Decimal("0.01"),
                  "MILLION": Decimal("0.1"), "CRORE": Decimal(1), "BILLION": Decimal(100)}

# English function words (not domain words): phrase boundaries, as in RAKE.
STOP = frozenset("""
a about above after again against all also am an and any are as at be been before being below between both but by
can could did do does doing down during each few for from further had has have having he her here hers herself him
himself his how i if in into is it its itself just me more most my myself no nor not now of off on once only or
other our ours ourselves out over own same she should so some such than that the their theirs them themselves then
there these they this those through to too under until up very was we were what when where which while who whom why
will with would you your yours yourself yourselves per via upon within without across along among towards toward
shall may might must said such whereas hereby herein thereof therein further including include includes included
""".split())
_TOKEN = re.compile(r"[a-z][a-z\-&/]*[a-z]|[a-z]")
_SPLIT = re.compile(r"[.,;:()\[\]{}\"'“”‘’!?|\n\r\t]+")


def phrases(text: str) -> list[str]:
    """Candidate key phrases: maximal runs of content words (no digits, no stop words), 1-4 words, deduplicated."""
    out, seen = [], set()
    for chunk in _SPLIT.split((text or "").lower()):
        run: list[str] = []
        for raw in chunk.split():
            tok = raw.strip("-&/")
            if not tok or any(ch.isdigit() for ch in tok) or tok in STOP or not _TOKEN.fullmatch(tok) or len(tok) < 2:
                if run:
                    _emit(run, out, seen)
                run = []
                continue
            run.append(tok)
        if run:
            _emit(run, out, seen)
    return out


def _emit(run: list[str], out: list, seen: set) -> None:
    # long runs: every window up to MAX_PHRASE_WORDS, so "power transformer supply" also yields "power transformer"
    n = len(run)
    for size in range(1, min(MAX_PHRASE_WORDS, n) + 1):
        for i in range(n - size + 1):
            p = " ".join(run[i:i + size])
            if p not in seen:
                seen.add(p)
                out.append(p)


def crore(amount, currency, scale) -> Optional[Decimal]:
    if amount is None or currency != "INR" or scale not in SCALE_TO_CRORE:
        return None
    return Decimal(amount) * SCALE_TO_CRORE[scale]


# ---------------------------------------------------------------------------------------------------- per passage
def index(conn, start: Optional[date] = None, end: Optional[date] = None) -> dict:
    """Store the phrases of every commercial passage not yet indexed (one row per publication+quote)."""
    rows = conn.execute(
        """SELECT DISTINCT ON (m.issuer_id, coalesce(m.publication_id::text, m.document_version_id::text), m.quote)
                  m.mention_id, m.issuer_id, coalesce(m.publication_id::text, m.document_version_id::text), m.published_at, m.family, m.quote, m.amount, m.currency,
                  m.scale, m.amount_basis, m.modality
             FROM commercial_mentions m
            WHERE m.family = ANY(%(f)s)
              AND (%(s)s::date IS NULL OR m.published_at >= %(s)s::timestamp AT TIME ZONE 'Asia/Kolkata')
              AND (%(e)s::date IS NULL OR m.published_at <  %(e)s::timestamp AT TIME ZONE 'Asia/Kolkata')
              AND NOT EXISTS (SELECT 1 FROM theme_phrase_mentions t
                               WHERE t.issuer_id = m.issuer_id AND t.quote_md5 = md5(m.quote)
                                 AND t.source_key = coalesce(m.publication_id::text, m.document_version_id::text))
            ORDER BY m.issuer_id, coalesce(m.publication_id::text, m.document_version_id::text), m.quote,
                     m.created_at DESC, m.mention_id""",
        dict(f=list(FAMILIES), s=start, e=end)).fetchall()
    n = 0
    for mid, iss, key, at, fam, quote, amt, cur, sc, basis, modality in rows:
        if modality == "NEGATED":
            continue
        value = crore(amt, cur, sc) if basis in ("FIRM", "EXECUTABLE_RELEASE", "GUARANTEED_MINIMUM") else None
        n += conn.execute(
            """INSERT INTO theme_phrase_mentions (mention_id, issuer_id, source_key, quote_md5, published_at, family,
                                                  phrases, value_cr, version)
               SELECT %s,%s,%s,md5(%s),%s,%s,%s,%s,%s ON CONFLICT DO NOTHING""",
            (mid, iss, key, quote, at, fam, phrases(quote), value, VERSION)).rowcount
    return {"indexed": n}


# ---------------------------------------------------------------------------------------------------- snapshot
class _UF:
    def __init__(self):
        self.p = {}

    def find(self, x):
        self.p.setdefault(x, x)
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]
            x = self.p[x]
        return x

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[max(ra, rb)] = min(ra, rb)


def _stage(cos: int, growth: Optional[float]) -> int:
    if growth is not None and growth <= -33.0:
        return 5
    if cos >= 25:
        return 4 if growth is not None and growth <= 0 else 3
    if cos >= 10:
        return 2
    if cos >= 4:
        return 1
    return 0


def build(rows: Iterable[tuple], as_of: date) -> list[dict]:
    """Pure part of a snapshot. rows = (issuer_id, filed_date, phrases, value_cr) for passages dated before as_of.
    Returns themes with their companies; no database access, so tests and backtests can call it directly."""
    as_of_dt = as_of
    recent_from = as_of_dt - timedelta(days=RECENT_DAYS)
    prior_from, prior_to = recent_from - timedelta(days=365), as_of_dt - timedelta(days=365)
    window_from = as_of_dt - timedelta(days=WINDOW_DAYS)
    total = 0
    win_cos: dict[str, set] = defaultdict(set)
    rec_cos: dict[str, set] = defaultdict(set)
    pri_cos: dict[str, set] = defaultdict(set)
    rec_passages: dict = defaultdict(list)       # company -> [(phrase set, value)] in the recent window
    first: dict[tuple, date] = {}
    for iss, d, phs, val in rows:
        if d >= as_of_dt:
            continue
        if d < window_from:
            continue
        total += 1
        phs = set(phs or ())
        if d >= recent_from:
            rec_passages[iss].append((phs, Decimal(val) if val is not None else None))
        for p in phs:
            win_cos[p].add(iss)
            first[(p, iss)] = min(first.get((p, iss), d), d)
            if d >= recent_from:
                rec_cos[p].add(iss)
            elif prior_from <= d < prior_to:
                pri_cos[p].add(iss)
    if not total:
        return []
    all_cos = set().union(*win_cos.values()) if win_cos else set()
    generic = max(GENERIC_SHARE * len(all_cos), GENERIC_FLOOR)
    cand = sorted(p for p, cos in rec_cos.items() if len(cos) >= MIN_COMPANIES and len(win_cos[p]) <= generic
                  and len(win_cos[p]) >= MIN_COMPANIES)
    # group: shared companies, or containment with most companies shared
    uf = _UF()
    for p in cand:
        uf.find(p)
    by_co: dict = defaultdict(list)
    for p in cand:
        for c in win_cos[p]:
            by_co[c].append(p)
    pairs = set()
    for ps in by_co.values():
        if len(ps) > 400:          # a company naming hundreds of phrases says nothing about which belong together
            continue
        for i, a in enumerate(ps):
            for b in ps[i + 1:]:
                pairs.add((a, b) if a < b else (b, a))
    for a, b in sorted(pairs):
        A, B = win_cos[a], win_cos[b]
        inter = len(A & B)
        jac = inter / len(A | B)
        contained = (f" {a} " in f" {b} " or f" {b} " in f" {a} ") and inter >= CONTAIN_SHARE * min(len(A), len(B))
        if jac >= JOIN or contained:
            uf.union(a, b)
    groups: dict[str, list[str]] = defaultdict(list)
    for p in cand:
        groups[uf.find(p)].append(p)
    out = []
    for members in groups.values():
        rec = set().union(*(rec_cos[p] for p in members))
        pri = set().union(*(pri_cos[p] for p in members))
        if len(rec) < MIN_COMPANIES:
            continue
        growth = None if not pri else round(100.0 * (len(rec) - len(pri)) / len(pri), 1)
        name = max(members, key=lambda p: (len(win_cos[p]), len(p.split()) >= 2, -len(p), p))
        comps = []
        mset = set(members)
        for c in rec:
            hits = [(ph, v) for ph, v in rec_passages[c] if ph & mset]
            n = len(hits)
            v = sum((v for _, v in hits if v is not None), Decimal(0))
            f = min(first[(p, c)] for p in members if (p, c) in first)
            comps.append(dict(issuer_id=c, mentions=n, value_cr=v, first_seen=f))
        comps.sort(key=lambda x: (-x["value_cr"], -x["mentions"], str(x["issuer_id"])))
        out.append(dict(name=name, phrases=sorted(members, key=lambda p: (-len(win_cos[p]), p))[:25],
                        companies=len(rec), companies_prior=len(pri), growth_pct=growth,
                        order_value_cr=sum((x["value_cr"] for x in comps), Decimal(0)),
                        stage=_stage(len(rec), growth), members=comps))
    out.sort(key=lambda t: (-t["companies"], t["name"]))
    return out


def _carry_keys(themes: list[dict], previous: list[tuple]) -> None:
    """Keep each theme's key (and first detection) from the previous snapshot when its phrases overlap enough."""
    used = set()
    for t in themes:
        best, score = None, 0.0
        ps = set(t["phrases"])
        for key, phs, first in previous:
            if key in used:
                continue
            j = len(ps & set(phs)) / len(ps | set(phs)) if phs else 0.0
            if j > score:
                best, score = (key, first), j
        if best and score >= KEEP_KEY:
            t["theme_key"], t["first_detected"] = best
            used.add(best[0])


def snapshot(conn, as_of: date, write: bool = True) -> dict:
    """Compute and store the emergent-theme snapshot for as_of (append-only; an existing as_of is left as it is)."""
    if conn.execute("SELECT 1 FROM emergent_theme_snapshots WHERE as_of = %s LIMIT 1", (as_of,)).fetchone():
        return {"as_of": as_of.isoformat(), "skipped": "exists"}
    rows = conn.execute(
        """SELECT issuer_id, (published_at AT TIME ZONE 'Asia/Kolkata')::date, phrases, value_cr
             FROM theme_phrase_mentions
            WHERE published_at < %(a)s::timestamp AT TIME ZONE 'Asia/Kolkata'
              AND published_at >= %(w)s::timestamp AT TIME ZONE 'Asia/Kolkata'""",
        dict(a=as_of, w=as_of - timedelta(days=WINDOW_DAYS))).fetchall()
    themes = build(rows, as_of)
    prev_date = conn.execute("SELECT max(as_of) FROM emergent_theme_snapshots WHERE as_of < %s", (as_of,)).fetchone()[0]
    previous = conn.execute("""SELECT theme_key, phrases, first_detected FROM emergent_theme_snapshots
                                WHERE as_of = %s ORDER BY companies DESC, theme_key""", (prev_date,)).fetchall() \
        if prev_date else []
    _carry_keys(themes, previous)
    for t in themes:
        t.setdefault("theme_key", f"{re.sub(r'[^a-z0-9]+', '-', t['name']).strip('-')}@{as_of.isoformat()}")
        t.setdefault("first_detected", as_of)
    if write:
        for t in themes:
            conn.execute(
                """INSERT INTO emergent_theme_snapshots (as_of, theme_key, name, phrases, companies, companies_prior,
                       growth_pct, order_value_cr, stage, first_detected, version)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (as_of, t["theme_key"], t["name"], t["phrases"], t["companies"], t["companies_prior"], t["growth_pct"],
                 t["order_value_cr"], t["stage"], t["first_detected"], VERSION))
            for m in t["members"]:
                conn.execute(
                    """INSERT INTO emergent_theme_companies (as_of, theme_key, issuer_id, mentions, value_cr, first_seen)
                       VALUES (%s,%s,%s,%s,%s,%s)""",
                    (as_of, t["theme_key"], m["issuer_id"], m["mentions"], m["value_cr"], m["first_seen"]))
    return {"as_of": as_of.isoformat(), "themes": len(themes),
            "by_stage": {s: sum(1 for t in themes if t["stage"] == s) for s in range(6)},
            "top": [(t["name"], t["companies"], t["growth_pct"], t["stage"]) for t in themes[:15]]}


def exposure(conn, issuer_id, cutoff: datetime, mode: str = "PUBLIC_INFORMATION", limit: int = 5) -> dict:
    """The company's emergent themes in the newest snapshot on or before the cutoff date."""
    if cutoff.tzinfo is None:
        raise ValueError("cutoff must be timezone-aware")
    p = dict(i=issuer_id, d=cutoff.astimezone(IST).date(), c=cutoff, replay=mode == "ACTUAL_SYSTEM_REPLAY")
    latest = conn.execute("""SELECT max(as_of) FROM emergent_theme_snapshots
                              WHERE as_of <= %(d)s AND (NOT %(replay)s OR recorded_at <= %(c)s)""", p).fetchone()[0]
    if latest is None:
        return {"snapshot": None, "themes": []}
    p["l"] = latest
    rows = conn.execute(
        """SELECT s.name, s.stage, s.companies, s.companies_prior, s.growth_pct, s.first_detected, c.mentions,
                  c.value_cr, c.first_seen, s.phrases[1:5]
             FROM emergent_theme_companies c JOIN emergent_theme_snapshots s USING (as_of, theme_key)
            WHERE c.as_of = %(l)s AND c.issuer_id = %(i)s
            ORDER BY c.value_cr DESC, c.mentions DESC, s.name LIMIT %(n)s""", dict(p, n=limit)).fetchall()
    return {"snapshot": latest.isoformat(), "themes": [
        dict(theme=r[0], stage=r[1], companies=r[2], companies_year_ago=r[3],
             growth_pct=float(r[4]) if r[4] is not None else None, theme_first_detected=r[5].isoformat(),
             company_mentions=r[6], company_value_cr=float(r[7]), company_first_seen=r[8].isoformat(),
             phrases=list(r[9] or [])) for r in rows]}
