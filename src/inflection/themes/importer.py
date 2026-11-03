"""One-off copy of MakroGraph's India theme history into inflection.

Reads the makrograph database in a read-only transaction and writes:
* theme_beneficiaries (source 'makrograph') from mg_india_beneficiaries: every dated snapshot as it is, plus the
  issuer resolved from the NSE symbol valid on that as_of date (NULL when the symbol is unknown here);
* theme_catalog: each theme name that maps to a supply-chain product, with the first as_of MakroGraph used it;
* theme_snapshots: mg_theme_snapshots for country IN (monthly strength/momentum, frozen history).

MakroGraph's mg_theme_beneficiaries is not copied: it keeps only the latest state per (theme, company) with
overwritten first_seen dates, so a past packet would see the future.

Re-running is safe: every insert is ON CONFLICT DO NOTHING on the natural key.
"""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import date
from typing import Optional

import psycopg

from .discovery import resolve_product


def _symbol_index(conn) -> dict:
    idx = defaultdict(list)
    for v, iss, f, t in conn.execute(
            """SELECT upper(h.value), s.issuer_id, h.valid_from, h.valid_to FROM identifier_history h
                 JOIN securities s USING (security_id) WHERE h.exchange = 'NSE' AND h.kind = 'SYMBOL'""").fetchall():
        idx[v].append((f, t, iss))
    return idx


def resolve_issuer(idx: dict, ticker: Optional[str], as_of: date):
    """The issuer whose NSE symbol was `ticker` on `as_of`; else the most recent holder of that symbol."""
    cands = idx.get((ticker or "").strip().upper())
    if not cands:
        return None
    live = [c for c in cands if c[0] <= as_of and (c[1] is None or c[1] >= as_of)]
    pick = max(live or cands, key=lambda c: (c[0], str(c[2])))
    return pick[2]


def copy_from_makrograph(conn, mg_dsn: str) -> dict:
    out = {"beneficiaries_read": 0, "beneficiaries_written": 0, "unresolved_tickers": 0, "catalog_written": 0,
           "snapshots_read": 0, "snapshots_written": 0}
    with psycopg.connect(mg_dsn, options="-c default_transaction_read_only=on") as mg:
        bens = mg.execute(
            """SELECT id, company, nullif(ticker, ''), theme_name, constrained_product, supply_chain_node,
                      supply_chain_stage, beneficiary_type, conviction_score, rationale, signal_count,
                      has_order_book_signals, import_substitution_play, as_of_date
                 FROM mg_india_beneficiaries WHERE as_of_date IS NOT NULL ORDER BY as_of_date, id""").fetchall()
        snaps = mg.execute(
            """SELECT t.theme_slug, t.theme_name, s.snapshot_date, s.strength_score, s.momentum_score, s.doc_count,
                      s.company_count, s.top_entities, t.conviction
                 FROM mg_theme_snapshots s JOIN mg_themes t ON t.id = s.theme_id
                WHERE t.country = 'IN' ORDER BY t.theme_slug, s.snapshot_date""").fetchall()
    idx = _symbol_index(conn)
    first_used: dict[str, tuple[date, str]] = {}
    with conn.transaction():
        for (rid, company, ticker, theme, product, node, stage, role, conv, why, sigs, ob, imp, as_of) in bens:
            out["beneficiaries_read"] += 1
            issuer = resolve_issuer(idx, ticker, as_of)
            out["unresolved_tickers"] += issuer is None
            lookback = 365 if (as_of.month, as_of.day) == (12, 31) else None
            out["beneficiaries_written"] += conn.execute(
                """INSERT INTO theme_beneficiaries (source, as_of_date, lookback_days, theme_name, constrained_product,
                       supply_chain_node, supply_chain_stage, role, conviction_score, signal_count, has_order_book,
                       import_substitution, rationale, company, ticker, issuer_id, source_row_id)
                   VALUES ('makrograph',%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT (source, as_of_date, theme_name, company) DO NOTHING""",
                (as_of, lookback, theme, product, node, stage, role, conv, sigs, ob, imp, why, company, ticker, issuer,
                 rid)).rowcount
            prod = product or resolve_product(theme)
            if prod and (theme not in first_used or as_of < first_used[theme][0]):
                first_used[theme] = (as_of, prod)
        for theme, (first, prod) in sorted(first_used.items()):
            out["catalog_written"] += conn.execute(
                """INSERT INTO theme_catalog (theme_name, constrained_product, source, first_as_of)
                   VALUES (%s,%s,'makrograph',%s) ON CONFLICT (theme_name) DO NOTHING""", (theme, prod, first)).rowcount
        for slug, name, d, strength, momentum, docs, cos, top, convn in snaps:
            out["snapshots_read"] += 1
            out["snapshots_written"] += conn.execute(
                """INSERT INTO theme_snapshots (source, theme_slug, theme_name, snapshot_date, strength_score,
                       momentum_score, doc_count, company_count, top_entities, conviction)
                   VALUES ('makrograph',%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING""",
                (slug, name, d, strength, momentum, docs, cos, json.dumps(top) if top is not None else None,
                 convn)).rowcount
    return out
