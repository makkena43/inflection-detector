"""MakroGraph India beneficiary discovery, ported to inflection's tables.

Port of MakroGraphIntelligence `src/makrograph/india/beneficiary_discovery.py` (`BeneficiaryDiscoveryLayer.discover`
and `_query_signal_companies`, b31bdd0).  The constants, the conviction formula, the role mapping, the signal-type
sets, the 40-company cap and the date window are copied unchanged so a run here continues the MakroGraph series
copied into theme_beneficiaries.  What changed:

* Signals and theme entities per filing come from theme_document_tags (filled by `tag`, which runs MakroGraph's
  own SignalExtractor and IndiaEntityInjector, vendored verbatim) instead of mg_signals / mg_document_entities.
* Companies are grouped by issuer, not by MakroGraph's (company name, ticker) text pair.
* Ties at the 40-company cap are broken by issuer id so a re-run returns the same rows (MakroGraph left it to
  PostgreSQL).
* Rows are append-only: re-running an as_of date that already exists writes nothing.

As in MakroGraph, a signal is counted once for every matching theme entity its filing carries (the SQL joined
signals to document entities), and the window is ``filed BETWEEN floor AND as_of`` with dates compared to IST
wall-clock times, so filings on the as_of day itself are outside it.
"""
from __future__ import annotations

import json
import math
import re
from datetime import date, datetime, timedelta, timezone
from typing import Iterable, Optional
from zoneinfo import ZoneInfo

from .mg_india_entities import IndiaEntityInjector
from .mg_signal_extractor import SignalExtractor
from .mg_supply_chain import _NODE_INDEX, IndiaSupplyChainDB

IST = ZoneInfo("Asia/Kolkata")
TAGGER_VERSION = "mg-b31bdd0:signal_extractor@a298c84a7f2b+india_entity_injector@341ed2e27cb0"
DEFAULT_LOOKBACK = 365

# ---- copied unchanged from beneficiary_discovery.py ---------------------------------------------------------------
_STAGE_ROLE = {
    0: "critical_supplier",
    1: "direct_supplier",
    2: "input_supplier",
    3: "ecosystem_participant",
}

_PRODUCT_ENTITY_KEYWORDS: dict[str, list[str]] = {
    "Power Transformer":             ["power grid", "electrical equipment"],
    "CRGO Steel":                    ["electrical equipment", "power grid"],
    "HV Cable":                      ["power grid", "electrical equipment"],
    "Solar Module":                  ["solar energy"],
    "Solar Cell":                    ["solar energy"],
    "Solar Wafer":                   ["solar energy"],
    "EMS / Contract Manufacturing":  ["semiconductor"],
    "PCB / Printed Circuit Board":   ["semiconductor"],
    "Semiconductor IC":              ["semiconductor"],
    "Battery Cell (Li-ion)":         ["battery storage", "electric vehicle"],
    "EV Battery Pack":               ["electric vehicle", "battery storage"],
    "Optical Fiber Cable":           ["5g telecom", "optical fiber"],
    "5G BTS / Radio Unit":           ["5g telecom"],
    "Rolling Stock / Locomotives":   ["railway infrastructure"],
    "Traction Motor":                ["railway infrastructure", "electrical equipment"],
    "Defense electronics":           ["defense electronics"],
}

_THEME_TO_PRODUCT: dict[str, str] = {
    "transformer":           "Power Transformer",
    "power transformer":     "Power Transformer",
    "crgo":                  "CRGO Steel",
    "hv cable":              "HV Cable",
    "cable supply":          "HV Cable",
    "solar wafer":           "Solar Wafer",
    "solar cell":            "Solar Cell",
    "solar module":          "Solar Module",
    "solar manufacturing":   "Solar Module",
    "ems":                   "EMS / Contract Manufacturing",
    "pcb":                   "PCB / Printed Circuit Board",
    "semiconductor":         "Semiconductor IC",
    "battery cell":          "Battery Cell (Li-ion)",
    "battery":               "Battery Cell (Li-ion)",
    "acc battery":           "Battery Cell (Li-ion)",
    "electric vehicle":      "EV Battery Pack",
    "optical fiber":         "Optical Fiber Cable",
    "fiber preform":         "Optical Fiber Cable",
    "5g":                    "5G BTS / Radio Unit",
    "railway":               "Rolling Stock / Locomotives",
    "traction":              "Traction Motor",
    "defense":               "Defense electronics",
    "defence":               "Defense electronics",
}

QUERY_TYPES = ('capex_increase', 'supply_bottleneck', 'demand_surge', 'regulatory_tailwind', 'inventory_drawdown',
               'capacity_shortage', 'localization_opportunity', 'tender_pipeline', 'policy_support')
CAPEX_TYPES = ('capex_increase', 'capacity_shortage', 'localization_opportunity', 'tender_pipeline')
SUPPLY_TYPES = ('supply_bottleneck', 'capacity_shortage', 'demand_surge', 'inventory_drawdown')
ORDER_BOOK_TYPES = ('demand_surge', 'supply_bottleneck', 'capex_increase', 'tender_pipeline', 'capacity_shortage')
HAVING_TYPES = ('capex_increase', 'supply_bottleneck', 'capacity_shortage', 'localization_opportunity', 'tender_pipeline')
COMPANY_CAP = 40
MIN_CONVICTION = 0.15

# Of MakroGraph's EntityExtractor keyword rules (run on the full text), only these two produce entity names the
# product map above uses; IndiaEntityInjector produces the rest.
_KEYWORD_RULE_ENTITIES = ("Semiconductor", "Electric Vehicle")


def resolve_product(theme_name: str) -> Optional[str]:
    tl = theme_name.lower()
    for keyword, product in _THEME_TO_PRODUCT.items():
        if keyword in tl:
            return product
    for node in IndiaSupplyChainDB().all_nodes():
        if node.name.lower() in tl:
            return node.name
    return None


def conviction(capex_sigs: int, supply_sigs: int, import_sub: bool, has_ob: bool) -> float:
    """MakroGraph v0.2 conviction, unchanged."""
    expansion_score = min(1.0, math.log1p(capex_sigs) / math.log1p(8))
    supply_score = min(1.0, math.log1p(supply_sigs) / math.log1p(10))
    import_bonus = 0.15 if import_sub else 0.0
    ob_bonus = 0.10 if has_ob else 0.0
    return round(expansion_score * 0.45 + supply_score * 0.30 + import_bonus + ob_bonus, 3)


def rationale(company: str, theme: str, product: str, sig_count: int, capex_sigs: int, has_ob: bool,
              import_sub: bool) -> str:
    parts = [f"{company} has {sig_count} supply-side signals co-occurring with "
             f"'{product}' in the '{theme}' theme window."]
    if capex_sigs:
        parts.append(f"{capex_sigs} capex_increase signals indicate bottleneck resolution activity.")
    if has_ob:
        parts.append("Order book / demand surge signals present.")
    if import_sub:
        parts.append("Product is import-dependent — domestic supplier qualifies as import substitution play.")
    return " ".join(parts)


# ---- tagging: one filing's text -> MakroGraph signal counts and theme entities ---------------------------------------
_KEYWORD_RES = [(k, re.compile(rf"\b{re.escape(k)}\b", re.IGNORECASE)) for k in _KEYWORD_RULE_ENTITIES]


def tag_text(text: str) -> tuple[dict, list[str]]:
    """What MakroGraph's India NLP pass stored for a document: signal counts by type and entity names (lowercase)."""
    if not text or not text.strip():
        return {}, []
    signals = SignalExtractor({"min_confidence": 0.65, "context_window_chars": 200}).extract(text)
    counts: dict[str, int] = {}
    for s in signals:
        counts[s.signal_type] = counts.get(s.signal_type, 0) + 1
    inj = IndiaEntityInjector()
    synthetic = inj.extract_from_signals(signals)
    if not synthetic:
        synthetic = inj.extract_from_text(text[:2000])
    ents = {e.canonical_name.lower() for e in synthetic}
    ents.update(k.lower() for k, rx in _KEYWORD_RES if rx.search(text))
    return dict(sorted(counts.items())), sorted(ents)


def _filed_ist(published_at, published_date) -> Optional[datetime]:
    if published_at is not None:
        return published_at.astimezone(IST).replace(tzinfo=None)
    if published_date is not None:
        return datetime(published_date.year, published_date.month, published_date.day)
    return None


def tag(conn, start: date, end: Optional[date] = None, limit: Optional[int] = None) -> dict:
    """Tag filings (with an issuer and extracted text) published from `start` up to `end`, skipping ones already
    tagged. Text = announcement title + every page of the newest readable text artifact."""
    end = end or date.today() + timedelta(days=1)
    rows = conn.execute(
        """SELECT p.publication_id, p.issuer_id, p.published_at, p.published_date, p.title,
                  (SELECT string_agg(tp.body, E'\\n' ORDER BY tp.page_no) FROM text_pages tp
                    WHERE tp.text_artifact_id = ta.text_artifact_id)
             FROM document_publications p
             JOIN LATERAL (SELECT a.text_artifact_id FROM text_artifacts a
                            WHERE a.document_version_id = p.document_version_id AND a.status IN ('COMPLETE','PARTIAL')
                            ORDER BY a.created_at DESC, a.text_artifact_id DESC LIMIT 1) ta ON true
            WHERE p.issuer_id IS NOT NULL
              AND coalesce(p.published_at, p.published_date::timestamp AT TIME ZONE 'Asia/Kolkata')
                  >= %(s)s::timestamp AT TIME ZONE 'Asia/Kolkata'
              AND coalesce(p.published_at, p.published_date::timestamp AT TIME ZONE 'Asia/Kolkata')
                  <  %(e)s::timestamp AT TIME ZONE 'Asia/Kolkata'
              AND NOT EXISTS (SELECT 1 FROM theme_document_tags t WHERE t.publication_id = p.publication_id)
            ORDER BY coalesce(p.published_at, p.published_date::timestamp AT TIME ZONE 'Asia/Kolkata'), p.publication_id
            LIMIT %(lim)s""", dict(s=start, e=end, lim=limit)).fetchall()
    out = {"tagged": 0, "with_signals": 0, "with_entities": 0}
    for pub, iss, at, d, title, body in rows:
        filed = _filed_ist(at, d)
        if filed is None:
            continue
        text = "\n".join(x for x in (title, body) if x)
        counts, ents = tag_text(text)
        conn.execute("""INSERT INTO theme_document_tags (publication_id, issuer_id, filed_ist, signal_counts, entities,
                                                         tagger_version)
                        VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING""",
                     (pub, iss, filed, json.dumps(counts), ents, TAGGER_VERSION))
        out["tagged"] += 1
        out["with_signals"] += bool(counts)
        out["with_entities"] += bool(ents)
    return out


# ---- discovery -------------------------------------------------------------------------------------------------------
def _signal_companies(conn, keywords: list[str], floor: date, as_of: date) -> list[dict]:
    rows = conn.execute(
        """WITH d AS (
               SELECT t.issuer_id, t.signal_counts,
                      (SELECT count(*) FROM unnest(t.entities) e WHERE e = ANY(%(kw)s)) AS n_ent
                 FROM theme_document_tags t
                WHERE t.filed_ist BETWEEN %(floor)s::timestamp AND %(as_of)s::timestamp
                  AND t.entities && %(kw)s::text[]),
             s AS (
               SELECT d.issuer_id, x.key AS signal_type, x.value::int * d.n_ent AS n
                 FROM d, jsonb_each_text(d.signal_counts) x
                WHERE x.key = ANY(%(q)s))
           SELECT issuer_id, sum(n)::int,
                  coalesce(sum(n) FILTER (WHERE signal_type = ANY(%(capex)s)), 0)::int,
                  coalesce(sum(n) FILTER (WHERE signal_type = ANY(%(supply)s)), 0)::int,
                  bool_or(signal_type = ANY(%(ob)s))
             FROM s GROUP BY issuer_id
           HAVING coalesce(sum(n) FILTER (WHERE signal_type = ANY(%(having)s)), 0) >= 1
            ORDER BY 3 DESC, 2 DESC, issuer_id
            LIMIT %(cap)s""",
        dict(kw=[k.lower() for k in keywords], floor=floor, as_of=as_of, q=list(QUERY_TYPES), capex=list(CAPEX_TYPES),
             supply=list(SUPPLY_TYPES), ob=list(ORDER_BOOK_TYPES), having=list(HAVING_TYPES), cap=COMPANY_CAP)).fetchall()
    return [dict(issuer_id=r[0], sig_count=r[1], capex_count=r[2], supply_count=r[3], has_order_book=bool(r[4]))
            for r in rows]


def _issuer_label(conn, issuer_id, as_of: date) -> tuple[str, Optional[str]]:
    r = conn.execute(
        """SELECT i.legal_name,
                  (SELECT h.value FROM securities s JOIN identifier_history h USING (security_id)
                    WHERE s.issuer_id = i.issuer_id AND h.exchange = 'NSE' AND h.kind = 'SYMBOL'
                    ORDER BY (h.valid_from <= %(d)s AND (h.valid_to IS NULL OR h.valid_to >= %(d)s)) DESC,
                             h.valid_from DESC, h.value LIMIT 1)
             FROM issuers i WHERE i.issuer_id = %(i)s""", dict(i=issuer_id, d=as_of)).fetchone()
    return (r[0], r[1]) if r else (str(issuer_id), None)


def catalog(conn, as_of: date) -> list[str]:
    """Theme names a run on `as_of` uses: the copied MakroGraph list, each from the first date MakroGraph used it."""
    return [r[0] for r in conn.execute(
        "SELECT theme_name FROM theme_catalog WHERE first_as_of IS NULL OR first_as_of <= %s ORDER BY theme_name",
        (as_of,)).fetchall()]


def discover(conn, as_of: date, lookback_days: int = DEFAULT_LOOKBACK, themes: Optional[Iterable[str]] = None,
             write: bool = True) -> dict:
    """One beneficiary snapshot for `as_of`, written as source 'inflection' (append-only)."""
    floor = as_of - timedelta(days=lookback_days)
    names = list(themes) if themes is not None else catalog(conn, as_of)
    out, seen, labels = [], set(), {}
    for theme_name in names:
        product = resolve_product(theme_name)
        if not product:
            continue
        keywords = _PRODUCT_ENTITY_KEYWORDS.get(product, [])
        if not keywords:
            continue
        node = _NODE_INDEX.get(product)
        stage = node.stage if node else 1
        import_sub = node.is_import_dependent if node else False
        for co in _signal_companies(conn, keywords, floor, as_of):
            key = (co["issuer_id"], theme_name)
            if key in seen:
                continue
            seen.add(key)
            conv = conviction(co["capex_count"], co["supply_count"], import_sub, co["has_order_book"])
            if conv < MIN_CONVICTION:
                continue
            if co["issuer_id"] not in labels:
                labels[co["issuer_id"]] = _issuer_label(conn, co["issuer_id"], as_of)
            name, ticker = labels[co["issuer_id"]]
            out.append(dict(theme_name=theme_name, constrained_product=product, supply_chain_node=product,
                            supply_chain_stage=stage - 1, role=_STAGE_ROLE.get(min(stage - 1, 3), "ecosystem_participant"),
                            conviction_score=conv, signal_count=co["sig_count"], capex_signals=co["capex_count"],
                            supply_signals=co["supply_count"], has_order_book=co["has_order_book"],
                            import_substitution=import_sub, company=name, ticker=ticker, issuer_id=co["issuer_id"],
                            rationale=rationale(name, theme_name, product, co["sig_count"], co["capex_count"],
                                                co["has_order_book"], import_sub)[:800]))
    out.sort(key=lambda b: (-b["conviction_score"], b["supply_chain_stage"], b["theme_name"], b["company"]))
    written = 0
    if write:
        for b in out:
            written += conn.execute(
                """INSERT INTO theme_beneficiaries (source, as_of_date, lookback_days, theme_name, constrained_product,
                       supply_chain_node, supply_chain_stage, role, conviction_score, signal_count, capex_signals,
                       supply_signals, has_order_book, import_substitution, rationale, company, ticker, issuer_id)
                   VALUES ('inflection',%(a)s,%(lb)s,%(theme_name)s,%(constrained_product)s,%(supply_chain_node)s,
                       %(supply_chain_stage)s,%(role)s,%(conviction_score)s,%(signal_count)s,%(capex_signals)s,
                       %(supply_signals)s,%(has_order_book)s,%(import_substitution)s,%(rationale)s,%(company)s,
                       %(ticker)s,%(issuer_id)s)
                   ON CONFLICT (source, as_of_date, theme_name, company) DO NOTHING""",
                dict(b, a=as_of, lb=lookback_days)).rowcount
    return {"as_of": as_of.isoformat(), "themes": len(names), "beneficiaries": len(out), "written": written,
            "rows": out if not write else None}


# ---- packet read ----------------------------------------------------------------------------------------------------
# ---- company role (maker / supplier / mention only) -------------------------------------------------------------------
# MakroGraph's capability table (makrograph_ref.mg_company_capabilities, manufacturer rows only) uses the same product
# names for most products; its product-role ledger (mg_company_product_roles) uses free text, so each product gets a
# pattern. Only role rows that MakroGraph's adjudication marked as evidenced are used (the rest are mostly junk).
_CAP_ALIASES = {"PCB / Printed Circuit Board": ("Printed Circuit Boards", "Circuits; printed")}
_ROLE_PRODUCT_RE = {
    "Power Transformer": r"\mtransformer", "Solar Module": r"solar (module|panel)", "Solar Cell": r"solar cell",
    "Solar Wafer": r"wafer", "Battery Cell (Li-ion)": r"(lithium|li-ion).*cell|battery cell",
    "EV Battery Pack": r"battery pack", "PCB / Printed Circuit Board": r"printed circuit|\mpcb",
    "Optical Fiber Cable": r"optical fib", "Rolling Stock / Locomotives": r"rolling stock|locomotive|railway wheel|coach|wagon",
    "CRGO Steel": r"crgo|grain oriented", "Semiconductor IC": r"semiconductor|\mic\M|chip",
    "EMS / Contract Manufacturing": r"electronics? manufacturing service|\mems\M|contract manufactur",
    "Defense electronics": r"defen[cs]e electronic|radar|avionic", "HV Cable": r"(hv|high voltage|ehv).*cable",
    "Traction Motor": r"traction motor", "5G BTS / Radio Unit": r"\mbts\M|radio unit|5g",
}
_ROLE_MAP = {"MANUFACTURER": "MAKER", "DIRECT_PRODUCT_SUPPLIER": "SUPPLIER"}


EPC_LOOKBACK_DAYS = 730
EPC_MIN_PASSAGES = 2


def is_contractor(conn, issuer_id, cutoff: datetime) -> bool:
    """True when the company's own order / capacity passages of the two years before the cutoff mostly describe EPC
    work (erection, installation, turnkey) rather than making things. MakroGraph's capability table calls solar and
    transmission EPC firms 'manufacturers'; this check, from inflection's emergent roles, overrides that."""
    from . import emergent
    counts = dict(conn.execute(
        """SELECT role, count(*) FROM theme_phrase_mentions
            WHERE issuer_id = %s AND version = %s AND role IN ('EPC', 'MAKER')
              AND published_at < %s AND published_at >= %s GROUP BY role""",
        (issuer_id, emergent.VERSION, cutoff, cutoff - timedelta(days=EPC_LOOKBACK_DAYS))).fetchall())
    return counts.get("EPC", 0) >= EPC_MIN_PASSAGES and counts.get("EPC", 0) > counts.get("MAKER", 0)


def company_roles(conn, issuer_id, day: date, products: list[str], cutoff: Optional[datetime] = None) -> dict[str, str]:
    """{product: MAKER | SUPPLIER | EPC | MENTION_ONLY} from MakroGraph's capability and evidenced role rows dated on
    or before `day`; a 'maker' whose own filings mostly describe EPC work is EPC. {} when the makrograph_ref tables
    are not present."""
    if not products or conn.execute("SELECT to_regclass('makrograph_ref.mg_company_capabilities')").fetchone()[0] is None:
        return {}
    contractor = cutoff is not None and is_contractor(conn, issuer_id, cutoff)
    syms = [r[0] for r in conn.execute(
        """SELECT DISTINCT upper(h.value) FROM securities s JOIN identifier_history h USING (security_id)
            WHERE s.issuer_id = %s AND h.kind = 'SYMBOL'""", (issuer_id,)).fetchall()]
    out = {}
    for prod in products:
        names = [prod, *_CAP_ALIASES.get(prod, ())]
        if conn.execute("""SELECT 1 FROM makrograph_ref.mg_company_capabilities
                            WHERE upper(ticker) = ANY(%s) AND product = ANY(%s) AND manufacturer
                              AND as_of_date <= %s LIMIT 1""", (syms, names, day)).fetchone():
            out[prod] = "EPC" if contractor else "MAKER"
            continue
        rx = _ROLE_PRODUCT_RE.get(prod)
        r = conn.execute(
            """SELECT role_type FROM makrograph_ref.mg_company_product_roles
                WHERE country = 'IN' AND upper(ticker) = ANY(%s) AND normalized_product ~* %s
                  AND role_type IN ('MANUFACTURER', 'DIRECT_PRODUCT_SUPPLIER')
                  AND adjudication_state LIKE '%%EVIDENCED%%' AND as_of_date <= %s AND last_evidence_date <= %s
                ORDER BY role_type = 'MANUFACTURER' DESC LIMIT 1""", (syms, rx, day, day)).fetchone() if rx else None
        out[prod] = _ROLE_MAP[r[0]] if r else "MENTION_ONLY"
        if contractor and out[prod] == "MAKER":
            out[prod] = "EPC"
    return out


def exposure(conn, issuer_id, cutoff: datetime, mode: str = "PUBLIC_INFORMATION", limit: int = 5) -> dict:
    """The company's themes in the newest snapshot dated on or before the cutoff (IST date), one per constrained
    product (highest conviction), with how long it has been flagged. ACTUAL_SYSTEM_REPLAY also needs the row to have
    been recorded by the cutoff."""
    if cutoff.tzinfo is None:
        raise ValueError("cutoff must be timezone-aware")
    day = cutoff.astimezone(IST).date()
    p = dict(i=issuer_id, d=day, c=cutoff, replay=mode == "ACTUAL_SYSTEM_REPLAY")
    latest = conn.execute(
        """SELECT max(as_of_date) FROM theme_beneficiaries
            WHERE as_of_date <= %(d)s AND (NOT %(replay)s OR recorded_at <= %(c)s)""", p).fetchone()[0]
    if latest is None:
        return {"snapshot": None, "themes": []}
    p["latest"] = latest
    rows = conn.execute(
        """WITH syms AS (SELECT DISTINCT upper(h.value) v FROM securities s JOIN identifier_history h USING (security_id)
                          WHERE s.issuer_id = %(i)s AND h.exchange = 'NSE' AND h.kind = 'SYMBOL'),
                mine AS (SELECT b.* FROM theme_beneficiaries b               -- two index lookups, not an OR scan
                          WHERE b.issuer_id = %(i)s
                            AND b.as_of_date <= %(d)s AND (NOT %(replay)s OR b.recorded_at <= %(c)s)
                         UNION
                         SELECT b.* FROM theme_beneficiaries b
                          WHERE upper(b.ticker) IN (SELECT v FROM syms)
                            AND b.as_of_date <= %(d)s AND (NOT %(replay)s OR b.recorded_at <= %(c)s))
           SELECT DISTINCT ON (m.constrained_product) m.constrained_product, m.theme_name, m.role, m.conviction_score,
                  m.signal_count, m.has_order_book, m.import_substitution, m.source,
                  (SELECT min(x.as_of_date) FROM mine x WHERE x.constrained_product = m.constrained_product),
                  (SELECT count(DISTINCT x.as_of_date) FROM mine x WHERE x.constrained_product = m.constrained_product)
             FROM mine m WHERE m.as_of_date = %(latest)s
            ORDER BY m.constrained_product, m.conviction_score DESC, m.theme_name""", p).fetchall()
    themes = [dict(product=r[0], theme=r[1], role=r[2], conviction=float(r[3]), signals=r[4], order_book=bool(r[5]),
                   import_substitution=bool(r[6]), source=r[7], first_flagged=r[8].isoformat(), snapshots_flagged=r[9])
              for r in rows]
    themes.sort(key=lambda t: (-t["conviction"], t["product"]))
    themes = themes[:limit]
    roles = company_roles(conn, issuer_id, day, [t["product"] for t in themes], cutoff)
    for t in themes:
        t["company_role"] = roles.get(t["product"])
    return {"snapshot": latest.isoformat(), "themes": themes}
