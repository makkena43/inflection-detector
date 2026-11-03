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

6. Specificity (emergent-3): a phrase is a candidate only when it is at least SPEC_MIN times more common in the
   object windows of order / capacity / launch passages than in ordinary filing sentences (a fixed sample of
   filings with no commercial passage, `background`).  Words like "months", "strong", "time", "strategic" and
   "projects" are common everywhere and drop out; "bess", "civil works", "mumbai metro" are not.  Phrases made only
   of the cue words that open an object window ("work order", "production capacity", "epc") are not themes either.
   A theme is named after its most specific widely used phrase, not its most common one.
7. Role (emergent-4): which side of the theme each company is on, read from its own passage wording.  MAKER
   (capacity, production, launch), SUPPLIER (order received, qualification), EPC (order received for erection /
   installation / turnkey work), BUYER (order placed with someone else, captive use).  A shortage helps makers and
   suppliers, is mixed for EPC contractors and hurts buyers, so packets show the role next to each theme.
8. Meaning labels (optional): once a local model has labelled phrases (theme_phrase_labels, see
   inflection.themes.labels), only phrases it said could name a product, material, technology, sector or project
   type can form themes, so every theme is named after such a phrase.

Everything is counts and set overlaps over the database; nothing is hand-listed except English stop words and the
cue words that mark where an order's object starts.
"""
from __future__ import annotations

import re
from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Iterable, Optional
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")
VERSION = "emergent-4"
BACKGROUND_VERSION = "emergent-3"   # phrase method unchanged since emergent-3, so its background counts still apply
FAMILIES = ("ORDER", "COMMERCIAL_START", "QUALIFICATION", "CAPACITY", "PRODUCT_LAUNCH")
RECENT_DAYS = 180
WINDOW_DAYS = 730            # phrases and company sets for grouping come from the two years before as_of
GENERIC_SHARE = 0.08         # a phrase used by more than 8% of companies in the window is generic language
GENERIC_FLOOR = 25           # ...but never below 25 companies (small samples)
MIN_COMPANIES = 3            # a theme needs at least this many companies in the recent window
CONTAIN_SHARE = 0.6          # "transformer" absorbs "power transformer" when 60% of the smaller set is shared
KEEP_KEY = 0.3               # phrase-set Jaccard to keep a theme's key from the previous snapshot
MAX_PHRASE_WORDS = 3
JOIN_PASSAGES = 0.3          # phrases merge when they share >= 30% of their passages (same sentences, not same firms)
MAX_THEMES = 300             # themes kept per snapshot, ranked by breadth x growth
VALUE_CAP_PCTL = 0.99        # one passage's value is capped at the 99th percentile of the window's passage values
SPEC_MIN = 16.0              # a phrase must be 16x more common in object windows than in ordinary filing sentences
BACKGROUND_DOCS = 20000      # filings sampled for the background
BACKGROUND_CHARS = 12000     # characters read from each (first pages)
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


# What an order / capacity / launch sentence is ABOUT follows these words: "order for supply of X",
# "capacity of X", "commenced production of X", "launched X".  Only that object window is read, so letter
# headings, exchange names and legal phrases elsewhere in the passage never become themes.
_OBJECT_CUE = re.compile(
    r"\b(?:supply(?:ing)?|manufactur(?:e|ing)|production|producing|design(?:ing)?|installation|commissioning|"
    r"construction|erection|execution|procurement|development|setting\s+up|establishment|expansion|"
    r"upgradation|modernisation|modernization|operation\s+and\s+maintenance|o&m|epc|delivery|export|"
    r"launch(?:ed|ing)?|introduc(?:ed|ing)|qualified|qualification|approval|capacity|plant|facility|line|"
    r"orders?|contracts?|loa|letter\s+of\s+(?:award|intent)|work\s+orders?|purchase\s+orders?)"
    r"\s+(?:of|for|to\s+supply|to\s+manufacture)?\s*", re.I)
_OBJECT_END = re.compile(
    r"\b(?:to|from|worth|valued|value|amounting|aggregating|aggregate|at|by|with|on|under|through|having|"
    r"which|that|received|awarded|placed|issued|dated|vide|inr|rs|usd|crores?|lakhs?|million|billion)\b|[.;:()]",
    re.I)
OBJECT_WORDS = 10
# The cue words above, as words: a phrase made only of these ("work order", "production capacity", "epc") says what
# kind of event it is, not what it is about.
CUE_WORDS = frozenset("""
supply supplying manufacture manufacturing production producing design designing installation commissioning
construction erection execution procurement development setting establishment expansion upgradation modernisation
modernization operation maintenance o&m epc delivery export launch launched launching introduced introducing
qualified qualification approval capacity plant facility facilities line order orders contract contracts loa letter
award intent work purchase
""".split())


def object_text(text: str) -> str:
    """The object windows of a passage: up to OBJECT_WORDS words after each cue, stopped at the next boundary."""
    out = []
    for m in _OBJECT_CUE.finditer(text or ""):
        tail = text[m.end():m.end() + 160]
        e = _OBJECT_END.search(tail)
        win = " ".join((tail[:e.start()] if e else tail).split()[:OBJECT_WORDS])
        if win:
            out.append(win)
    return " | ".join(out)


def phrases(text: str, objects_only: bool = True) -> list[str]:
    """Key phrases: maximal runs of content words (no digits, no stop words, 3+ letters), 1-3 words, deduplicated.
    By default only the object windows of the passage are read."""
    if objects_only:
        text = object_text(text)
    out, seen = [], set()
    for chunk in _SPLIT.split((text or "").lower()):
        run: list[str] = []
        for raw in chunk.split():
            tok = raw.strip("-&/")
            if not tok or any(ch.isdigit() for ch in tok) or tok in STOP or not _TOKEN.fullmatch(tok) or len(tok) < 3:
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
            words = run[i:i + size]
            if all(w in CUE_WORDS for w in words):
                continue
            p = " ".join(words)
            if p not in seen:
                seen.add(p)
                out.append(p)


# ---------------------------------------------------------------------------------------------------- role
_CAPTIVE = re.compile(r"\b(?:captive|own\s+(?:use|consumption|requirement|plants?|facilit(?:y|ies)|operations)|"
                      r"in-house\s+use|self[- ]consumption|for\s+(?:its|our)\s+(?:own|existing|new)\b)", re.I)
_PLACED = re.compile(r"\b(?:placed|has\s+placed|places|procur(?:e|ed|ement|ing)|purchas(?:e|ed|ing)\s+(?:of|from)|"
                     r"(?:awarded|given|issued|granted)\s+(?:the\s+|a\s+|an\s+)?(?:contract|order|work|loa)s?\s+to|"
                     r"order\s+(?:on|with)\s+[A-Z]|sourc(?:e|ed|ing)\s+from|buy(?:ing)?\s+from)", re.I)
_RECEIVED = re.compile(r"\b(?:receiv(?:ed|es|ing)|receipt\s+of|bag(?:ged|s)|secur(?:ed|es)|w[io]ns?|bagging|"
                       r"(?:has|have|been|was|were|is)\s+(?:been\s+)?(?:awarded|declared)|"
                       r"l-?1\b|lowest\s+bidder|letter\s+of\s+(?:award|intent)|loa\b|work\s+orders?\s+from|"
                       r"orders?\s+from|contract\s+from)", re.I)
_CONTRACTING = re.compile(r"\b(?:epc|turnkey|erection|installation|civil\s+works?|construction\s+of|"
                          r"engineering,\s+procurement)", re.I)


def role(family: str, text: str) -> Optional[str]:
    """Which side the filing company is on, from its own wording; None when the wording does not say."""
    text = text or ""
    if _CAPTIVE.search(text):
        return "BUYER"
    if family in ("CAPACITY", "COMMERCIAL_START", "PRODUCT_LAUNCH"):
        return "MAKER"
    if family == "QUALIFICATION":
        return "SUPPLIER"
    received, placed = bool(_RECEIVED.search(text)), bool(_PLACED.search(text))
    if received and not placed:
        return "EPC" if _CONTRACTING.search(text) else "SUPPLIER"
    if placed and not received:
        return "BUYER"
    return None


_ROLE_ORDER = ("MAKER", "SUPPLIER", "EPC", "BUYER")


def company_role(roles: Iterable[Optional[str]]) -> Optional[str]:
    """One role per company in a theme: the most common stated role; ties go to the supply side
    (maker, then supplier, then EPC, then buyer)."""
    counts: dict[str, int] = defaultdict(int)
    for r in roles:
        if r:
            counts[r] += 1
    if not counts:
        return None
    return max(_ROLE_ORDER, key=lambda r: (counts.get(r, 0), -_ROLE_ORDER.index(r)))


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
                               WHERE t.version = %(v)s AND t.issuer_id = m.issuer_id AND t.quote_md5 = md5(m.quote)
                                 AND t.source_key = coalesce(m.publication_id::text, m.document_version_id::text))
            ORDER BY m.issuer_id, coalesce(m.publication_id::text, m.document_version_id::text), m.quote,
                     m.created_at DESC, m.mention_id""",
        dict(f=list(FAMILIES), s=start, e=end, v=VERSION)).fetchall()
    n = 0
    for mid, iss, key, at, fam, quote, amt, cur, sc, basis, modality in rows:
        if modality == "NEGATED":
            continue
        value = crore(amt, cur, sc) if basis in ("FIRM", "EXECUTABLE_RELEASE", "GUARANTEED_MINIMUM") else None
        n += conn.execute(
            """INSERT INTO theme_phrase_mentions (mention_id, issuer_id, source_key, quote_md5, published_at, family,
                                                  phrases, value_cr, version, role)
               SELECT %s,%s,%s,md5(%s),%s,%s,%s,%s,%s,%s ON CONFLICT DO NOTHING""",
            (mid, iss, key, quote, at, fam, phrases(quote), value, VERSION, role(fam, quote))).rowcount
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


def build(rows: Iterable[tuple], as_of: date, background: Optional[tuple[dict, int]] = None,
          spec_min: float = SPEC_MIN, allowed: Optional[frozenset] = None) -> list[dict]:
    """Pure part of a snapshot. rows = (issuer_id, filed_date, phrases, value_cr[, role]) for passages dated before
    as_of.
    background = ({phrase: background sentences containing it}, total background sentences); without it there is
    no specificity filter (tests of the other steps).
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
    win_pass: dict[str, set] = defaultdict(set)  # phrase -> passage numbers in the window
    passages: list[set] = []
    first: dict[tuple, date] = {}
    values = []
    rows = [tuple(r) + (None,) * (5 - len(r)) for r in rows]
    for iss, d, phs, val, _ in rows:
        if window_from <= d < as_of_dt and val is not None:
            values.append(Decimal(val))
    cap = sorted(values)[int(VALUE_CAP_PCTL * (len(values) - 1))] if values else None
    for iss, d, phs, val, rl in rows:
        if d >= as_of_dt:
            continue
        if d < window_from:
            continue
        total += 1
        phs = set(phs or ())
        v = min(Decimal(val), cap) if val is not None and cap is not None else None
        if d >= recent_from:
            rec_passages[iss].append((phs, v, rl))
        passages.append(phs)
        for p in phs:
            win_pass[p].add(len(passages) - 1)
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
    n_pass = len(passages)

    def spec(p: str) -> Optional[float]:
        if background is None:
            return None
        bg, n_bg = background
        return (len(win_pass[p]) / n_pass) / ((bg.get(p, 0) + 1) / (n_bg + 1))

    cand = sorted(p for p, cos in rec_cos.items() if len(cos) >= MIN_COMPANIES and len(win_cos[p]) <= generic
                  and len(win_cos[p]) >= MIN_COMPANIES and (background is None or spec(p) >= spec_min)
                  and (allowed is None or p in allowed))
    specs = {p: spec(p) for p in cand}
    # group phrases that occur in the same passages (same sentences), or where one contains the other and most of
    # the shorter one's passages are shared; sharing companies alone is not enough (a company names many things)
    uf = _UF()
    cset = set(cand)
    for p in cand:
        uf.find(p)
    pairs = set()
    for phs in passages:
        ps = sorted(phs & cset)
        if len(ps) > 60:
            continue
        for i, a in enumerate(ps):
            for b in ps[i + 1:]:
                pairs.add((a, b))
    for a, b in sorted(pairs):
        A, B = win_pass[a], win_pass[b]
        inter = len(A & B)
        jac = inter / len(A | B)
        contained = (f" {a} " in f" {b} " or f" {b} " in f" {a} ") and inter >= CONTAIN_SHARE * min(len(A), len(B))
        if jac >= JOIN_PASSAGES or contained:
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
        if background is None:
            name = max(members, key=lambda p: (len(win_cos[p]), len(p.split()) >= 2, -len(p), p))
        else:   # most specific among the phrases used by at least half as many companies as the widest one
            wide = max(len(win_cos[p]) for p in members)
            name = max((p for p in members if 2 * len(win_cos[p]) >= wide),
                       key=lambda p: (specs[p], len(win_cos[p]), -len(p), p))
        comps = []
        mset = set(members)
        for c in rec:
            hits = [(ph, v, rl) for ph, v, rl in rec_passages[c] if ph & mset]
            n = len(hits)
            v = sum((v for _, v, _ in hits if v is not None), Decimal(0))
            f = min(first[(p, c)] for p in members if (p, c) in first)
            comps.append(dict(issuer_id=c, mentions=n, value_cr=v, first_seen=f,
                              role=company_role(rl for _, _, rl in hits)))
        comps.sort(key=lambda x: (-x["value_cr"], -x["mentions"], str(x["issuer_id"])))
        out.append(dict(name=name, phrases=sorted(members, key=lambda p: (-len(win_cos[p]), p))[:25],
                        companies=len(rec), companies_prior=len(pri), growth_pct=growth,
                        order_value_cr=sum((x["value_cr"] for x in comps), Decimal(0)),
                        stage=_stage(len(rec), growth), members=comps,
                        specificity=None if specs[name] is None else round(specs[name], 1)))
    # rank by breadth and year-on-year growth; keep the top MAX_THEMES
    def score(t):
        g = 100.0 if t["growth_pct"] is None else max(-50.0, min(t["growth_pct"], 300.0))
        return t["companies"] * (1.0 + g / 100.0)
    out.sort(key=lambda t: (-score(t), t["name"]))
    return out[:MAX_THEMES]


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


_BG_CACHE: dict = {}
_LABEL_CACHE: dict = {}


def load_allowed(conn) -> Optional[frozenset]:
    """Phrases labelled as naming a theme under the current prompt version, or None when there are no labels at all
    for it (then no meaning filter is applied)."""
    if "allowed" not in _LABEL_CACHE:
        rows = []
        if conn.execute("SELECT to_regclass('theme_phrase_labels')").fetchone()[0] is not None:
            from .labels import PROMPT_VERSION
            rows = conn.execute("SELECT phrase, is_theme FROM theme_phrase_labels WHERE prompt_version = %s",
                                (PROMPT_VERSION,)).fetchall()
        _LABEL_CACHE["allowed"] = frozenset(p for p, ok in rows if ok) if rows else None
    return _LABEL_CACHE["allowed"]


def load_background(conn) -> Optional[tuple[dict, int]]:
    if VERSION not in _BG_CACHE:
        run = conn.execute("SELECT sentences FROM theme_background_runs WHERE version = %s",
                           (BACKGROUND_VERSION,)).fetchone()
        if not run:
            return None
        bg = dict(conn.execute("SELECT phrase, sentences FROM theme_phrase_background WHERE version = %s",
                               (BACKGROUND_VERSION,)).fetchall())
        _BG_CACHE[VERSION] = (bg, int(run[0]))
    return _BG_CACHE[VERSION]


_SENTENCE = re.compile(r"(?<=[.!?;])\s+|\n\s*\n")


def background(conn, start: date, end: date, docs: int = BACKGROUND_DOCS, chars: int = BACKGROUND_CHARS) -> dict:
    """Count, for every phrase the passages use, how many ordinary filing sentences contain it. Ordinary = a
    deterministic sample of filings published in [start, end) that have no commercial passage. Built once per
    BACKGROUND_VERSION (append-only); run after emergent-index."""
    if conn.execute("SELECT 1 FROM theme_background_runs WHERE version = %s", (BACKGROUND_VERSION,)).fetchone():
        return {"skipped": "exists", "version": BACKGROUND_VERSION}
    vocab = {r[0] for r in conn.execute(
        "SELECT DISTINCT unnest(phrases) FROM theme_phrase_mentions WHERE version IN (%s, %s)",
        (VERSION, BACKGROUND_VERSION)).fetchall()}
    if not vocab:
        return {"error": "no indexed passages for " + VERSION + "; run emergent-index first"}
    ids = [r[0] for r in conn.execute(
        """SELECT p.publication_id FROM document_publications p
            WHERE p.issuer_id IS NOT NULL
              AND coalesce(p.published_at, p.published_date::timestamp AT TIME ZONE 'Asia/Kolkata')
                  >= %(s)s::timestamp AT TIME ZONE 'Asia/Kolkata'
              AND coalesce(p.published_at, p.published_date::timestamp AT TIME ZONE 'Asia/Kolkata')
                  <  %(e)s::timestamp AT TIME ZONE 'Asia/Kolkata'
              AND EXISTS (SELECT 1 FROM text_artifacts a WHERE a.document_version_id = p.document_version_id
                             AND a.status IN ('COMPLETE','PARTIAL'))
              AND NOT EXISTS (SELECT 1 FROM commercial_mentions m WHERE m.publication_id = p.publication_id
                                 AND m.family = ANY(%(f)s))
            ORDER BY md5(p.publication_id::text) LIMIT %(n)s""",
        dict(s=start, e=end, f=list(FAMILIES), n=docs)).fetchall()]
    counts: dict[str, int] = defaultdict(int)
    n_docs = n_sent = 0
    for i in range(0, len(ids), 500):
        for (text,) in conn.execute(
                """SELECT left((SELECT string_agg(tp.body, E'\\n' ORDER BY tp.page_no) FROM text_pages tp
                                 WHERE tp.text_artifact_id = ta.text_artifact_id AND tp.page_no <= 6), %(c)s)
                     FROM document_publications p
                     JOIN LATERAL (SELECT a.text_artifact_id FROM text_artifacts a
                                    WHERE a.document_version_id = p.document_version_id
                                      AND a.status IN ('COMPLETE','PARTIAL')
                                    ORDER BY a.created_at DESC, a.text_artifact_id DESC LIMIT 1) ta ON true
                    WHERE p.publication_id = ANY(%(ids)s)""", dict(c=chars, ids=ids[i:i + 500])).fetchall():
            if not text:
                continue
            n_docs += 1
            for sent in _SENTENCE.split(text):
                if not sent.strip():
                    continue
                n_sent += 1
                for p in set(phrases(sent, objects_only=False)) & vocab:
                    counts[p] += 1
    if not n_sent:
        return {"error": "no background text in the period"}
    with conn.transaction():
        conn.execute("""INSERT INTO theme_background_runs (version, built_from, built_to, documents, sentences)
                        VALUES (%s,%s,%s,%s,%s)""", (BACKGROUND_VERSION, start, end, n_docs, n_sent))
        with conn.cursor().copy("COPY theme_phrase_background (version, phrase, sentences) FROM STDIN") as cp:
            for p, n in counts.items():
                cp.write_row((BACKGROUND_VERSION, p, n))
    _BG_CACHE.pop(VERSION, None)
    return {"version": BACKGROUND_VERSION, "documents": n_docs, "sentences": n_sent, "vocab": len(vocab),
            "phrases_seen": len(counts)}


def snapshot(conn, as_of: date, write: bool = True, spec_min: float = SPEC_MIN, use_labels: bool = True) -> dict:
    """Compute and store the emergent-theme snapshot for as_of, in one transaction (append-only; an existing as_of
    for this VERSION is left as it is). write=False computes and reports without storing."""
    if write and conn.execute("SELECT 1 FROM emergent_theme_snapshots WHERE as_of = %s AND version = %s LIMIT 1",
                              (as_of, VERSION)).fetchone():
        return {"as_of": as_of.isoformat(), "skipped": "exists"}
    rows = conn.execute(
        """SELECT issuer_id, (published_at AT TIME ZONE 'Asia/Kolkata')::date, phrases, value_cr, role
             FROM theme_phrase_mentions
            WHERE version = %(v)s
              AND published_at < %(a)s::timestamp AT TIME ZONE 'Asia/Kolkata'
              AND published_at >= %(w)s::timestamp AT TIME ZONE 'Asia/Kolkata'""",
        dict(a=as_of, w=as_of - timedelta(days=WINDOW_DAYS), v=VERSION)).fetchall()
    bg = load_background(conn)
    if bg is None:
        return {"as_of": as_of.isoformat(), "error": "no background for " + BACKGROUND_VERSION + "; run emergent-background"}
    allowed = load_allowed(conn) if use_labels else None
    themes = build(rows, as_of, bg, spec_min, allowed)
    prev_date = conn.execute("SELECT max(as_of) FROM emergent_theme_snapshots WHERE as_of < %s AND version = %s",
                             (as_of, VERSION)).fetchone()[0]
    previous = conn.execute("""SELECT theme_key, phrases, first_detected FROM emergent_theme_snapshots
                                WHERE as_of = %s AND version = %s ORDER BY companies DESC, theme_key""",
                            (prev_date, VERSION)).fetchall() if prev_date else []
    _carry_keys(themes, previous)
    keys = set()
    for t in themes:
        if "theme_key" not in t:
            base = f"{re.sub(r'[^a-z0-9]+', '-', t['name']).strip('-')}@{as_of.isoformat()}#{VERSION}"
            key, n = base, 1
            while key in keys:
                n += 1
                key = f"{base}.{n}"
            t["theme_key"] = key
        keys.add(t["theme_key"])
        t.setdefault("first_detected", as_of)
    if write:
        with conn.transaction():
            for t in themes:
                conn.execute(
                    """INSERT INTO emergent_theme_snapshots (as_of, theme_key, name, phrases, companies,
                           companies_prior, growth_pct, order_value_cr, stage, first_detected, version)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (as_of, t["theme_key"], t["name"], t["phrases"], t["companies"], t["companies_prior"],
                     t["growth_pct"], t["order_value_cr"], t["stage"], t["first_detected"], VERSION))
                for m in t["members"]:
                    conn.execute(
                        """INSERT INTO emergent_theme_companies (as_of, theme_key, issuer_id, mentions, value_cr,
                               first_seen, role) VALUES (%s,%s,%s,%s,%s,%s,%s)""",
                        (as_of, t["theme_key"], m["issuer_id"], m["mentions"], m["value_cr"], m["first_seen"],
                         m["role"]))
    return {"as_of": as_of.isoformat(), "written": write, "passages": len(rows), "themes": len(themes),
            "labels_allowed": None if allowed is None else len(allowed),
            "by_stage": {s: sum(1 for t in themes if t["stage"] == s) for s in range(6)},
            "top": [(t["name"], t["companies"], t["growth_pct"], t["stage"], t["specificity"], t["phrases"][:5])
                    for t in themes[:40]],
            "early": [(t["name"], t["companies"], t["growth_pct"], t["stage"], t["specificity"], t["phrases"][:5])
                      for t in sorted((t for t in themes if t["stage"] <= 1),
                                      key=lambda t: (-t["companies"], -(t["specificity"] or 0), t["name"]))[:15]]}


def exposure(conn, issuer_id, cutoff: datetime, mode: str = "PUBLIC_INFORMATION", limit: int = 5) -> dict:
    """The company's emergent themes in the newest snapshot on or before the cutoff date."""
    if cutoff.tzinfo is None:
        raise ValueError("cutoff must be timezone-aware")
    p = dict(i=issuer_id, d=cutoff.astimezone(IST).date(), c=cutoff, replay=mode == "ACTUAL_SYSTEM_REPLAY")
    p["v"] = VERSION
    latest = conn.execute("""SELECT max(as_of) FROM emergent_theme_snapshots
                              WHERE version = %(v)s AND as_of <= %(d)s AND (NOT %(replay)s OR recorded_at <= %(c)s)""",
                          p).fetchone()[0]
    if latest is None:
        return {"snapshot": None, "themes": []}
    p["l"] = latest
    rows = conn.execute(
        """SELECT s.name, s.stage, s.companies, s.companies_prior, s.growth_pct, s.first_detected, c.mentions,
                  c.value_cr, c.first_seen, s.phrases[1:5], c.role
             FROM emergent_theme_companies c JOIN emergent_theme_snapshots s USING (as_of, theme_key)
            WHERE c.as_of = %(l)s AND c.issuer_id = %(i)s AND s.version = %(v)s
            ORDER BY c.value_cr DESC, c.mentions DESC, s.name LIMIT %(n)s""", dict(p, n=limit)).fetchall()
    return {"snapshot": latest.isoformat(), "themes": [
        dict(theme=r[0], stage=r[1], companies=r[2], companies_year_ago=r[3],
             growth_pct=float(r[4]) if r[4] is not None else None, theme_first_detected=r[5].isoformat(),
             company_mentions=r[6], company_value_cr=float(r[7]), company_first_seen=r[8].isoformat(),
             phrases=list(r[9] or []), company_role=r[10]) for r in rows]}
