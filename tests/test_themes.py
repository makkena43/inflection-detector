"""MakroGraph supply-gap themes: vendored tagger, ported discovery, MakroGraph import mapping and the packet section."""
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from inflection.packets import contents as C
from inflection.themes import discovery as D
from inflection.themes import importer

IST = ZoneInfo("Asia/Kolkata")
TRANSFORMER = ("The Board approved capacity expansion of the power transformer plant at Vadodara with a capex of "
               "Rs 200 crore. Demand for transformers remains strong and the order book is at a record high, with "
               "strong demand from utilities. The company also commissioned a new switchgear line.")


def test_tag_text_is_makrograph_tagging():
    counts, ents = D.tag_text(TRANSFORMER)
    assert counts == {"capex_increase": 1, "demand_surge": 1}
    assert ents == ["electrical equipment"]
    assert D.tag_text(TRANSFORMER) == (counts, ents)               # deterministic
    assert D.tag_text("Outcome of board meeting. Appointment of director.") == ({}, [])
    # EntityExtractor keyword rule on the full text
    assert "semiconductor" in D.tag_text("We supply semiconductor test equipment.")[1]


def test_conviction_and_product_mapping_unchanged():
    assert D.conviction(8, 10, True, True) == 1.0                   # e.g. CGPOWER / CRGO Steel Shortage in MakroGraph
    assert D.conviction(0, 0, False, False) == 0.0
    assert D.conviction(1, 0, False, True) == round(0.45 * D.math.log1p(1) / D.math.log1p(8) + 0.10, 3)
    assert D.resolve_product("CRGO Steel Shortage") == "CRGO Steel"
    assert D.resolve_product("Battery Cell Manufacturing Gap") == "Battery Cell (Li-ion)"
    assert D.resolve_product("Retail lending") is None


def test_resolve_issuer_prefers_symbol_valid_on_the_date():
    idx = {"ABC": [(date(2010, 1, 1), date(2022, 6, 30), "old"), (date(2023, 1, 1), None, "new")]}
    assert importer.resolve_issuer(idx, "abc", date(2021, 12, 31)) == "old"
    assert importer.resolve_issuer(idx, "ABC", date(2024, 12, 31)) == "new"
    assert importer.resolve_issuer(idx, "ABC", date(2022, 9, 1)) == "new"         # gap: latest holder
    assert importer.resolve_issuer(idx, "", date(2024, 1, 1)) is None


def test_themes_section_render():
    assert "no theme snapshot" in "\n".join(C.themes_section({"snapshot": None, "themes": []}))
    assert "not a flagged supplier" in "\n".join(C.themes_section({"snapshot": "2025-12-31", "themes": []}))
    out = "\n".join(C.themes_section({"snapshot": "2025-12-31", "themes": [dict(
        product="CRGO Steel", theme="CRGO Steel Shortage", role="direct_supplier", conviction=1.0, signals=45,
        order_book=True, import_substitution=True, source="makrograph", first_flagged="2023-12-31",
        snapshots_flagged=3)]}))
    assert "CRGO Steel (CRGO Steel Shortage)" in out and "1.00" in out and "2023-12-31 (3)" in out


# ---------------- database ----------------

def _company(db, name, symbol, isin):
    iss = db.execute("INSERT INTO issuers (legal_name) VALUES (%s) RETURNING issuer_id", (name,)).fetchone()[0]
    sec = db.execute("INSERT INTO securities (issuer_id, isin) VALUES (%s, %s) RETURNING security_id",
                     (iss, isin)).fetchone()[0]
    db.execute("""INSERT INTO identifier_history (security_id, exchange, kind, value, valid_from, source)
                  VALUES (%s, 'NSE', 'SYMBOL', %s, '2010-01-01', 'test')""", (sec, symbol))
    return iss


def _filing(db, iss, src, n, when, body, title="Outcome of Board Meeting"):
    doc = db.execute("INSERT INTO documents (issuer_id) VALUES (%s) RETURNING document_id", (iss,)).fetchone()[0]
    ver = db.execute("""INSERT INTO document_versions (document_id, sha256, storage_key, byte_size, media_type)
                        VALUES (%s, %s, 'k', 1, 'application/pdf') RETURNING document_version_id""",
                     (doc, f"{n:064x}")).fetchone()[0]
    pub = db.execute("""INSERT INTO document_publications (document_version_id, source_id, external_id, source_url,
                            published_at, publication_basis, issuer_id, original_category, pipeline_state, title)
                        VALUES (%s, %s, %s, %s, %s, 'EXCHANGE_TIMESTAMP', %s, 'Outcome of Board Meeting',
                                'TEXT_READY', %s) RETURNING publication_id""",
                     (ver, src, f"ann-{n}", f"https://x/{n}.pdf", when, iss, title)).fetchone()[0]
    art = db.execute("""INSERT INTO text_artifacts (document_version_id, extraction_method, extraction_version, status,
                            pages_processed) VALUES (%s, 'pdfplumber', '1', 'COMPLETE', 1)
                        RETURNING text_artifact_id""", (ver,)).fetchone()[0]
    db.execute("INSERT INTO text_pages (text_artifact_id, page_no, body) VALUES (%s, 1, %s)", (art, body))
    return pub


def test_tag_discover_and_packet_exposure(db):
    abc = _company(db, "ABC Transformers Limited", "ABCT", "INE111A01011")
    xyz = _company(db, "XYZ Finance Limited", "XYZF", "INE222A01011")
    src = db.execute("""INSERT INTO sources (name, kind, access_policy) VALUES ('nse_announcements', 'announcements',
                        'test') RETURNING source_id""").fetchone()[0]
    _filing(db, abc, src, 1, datetime(2025, 5, 10, 18, 0, tzinfo=IST), TRANSFORMER)
    _filing(db, abc, src, 2, datetime(2025, 12, 31, 10, 0, tzinfo=IST), TRANSFORMER)   # on the as_of day: outside
    _filing(db, xyz, src, 3, datetime(2025, 6, 1, 18, 0, tzinfo=IST), "Appointment of statutory auditor.")
    assert D.tag(db, date(2025, 1, 1), date(2026, 1, 1)) == {"tagged": 3, "with_signals": 2, "with_entities": 2}
    assert D.tag(db, date(2025, 1, 1), date(2026, 1, 1))["tagged"] == 0                 # already tagged
    db.execute("""INSERT INTO theme_catalog (theme_name, constrained_product, source, first_as_of)
                  VALUES ('CRGO Steel Shortage', 'CRGO Steel', 'makrograph', '2024-12-31'),
                         ('Power Transformer Capacity Gap', 'Power Transformer', 'makrograph', '2026-06-30')""")
    res = D.discover(db, date(2025, 12, 31))
    assert res["themes"] == 1 and res["beneficiaries"] == 1 and res["written"] == 1   # catalog row from 2026 not used
    row = db.execute("""SELECT company, ticker, issuer_id, constrained_product, signal_count, capex_signals,
                               has_order_book, conviction_score, source FROM theme_beneficiaries""").fetchone()
    # one capex + one demand signal, each counted once per matching entity (only 'electrical equipment')
    assert row[:7] == ("ABC Transformers Limited", "ABCT", abc, "CRGO Steel", 2, 1, True)
    assert float(row[7]) == D.conviction(1, 1, True, True) and row[8] == "inflection"
    assert D.discover(db, date(2025, 12, 31))["written"] == 0                         # append-only, no rewrite

    # a MakroGraph-copied row for an earlier year, matched to the issuer by ticker only
    db.execute("""INSERT INTO theme_beneficiaries (source, as_of_date, lookback_days, theme_name, constrained_product,
                      role, conviction_score, signal_count, has_order_book, import_substitution, company, ticker)
                  VALUES ('makrograph', '2024-12-31', 365, 'CRGO Steel Shortage', 'CRGO Steel', 'direct_supplier',
                          0.7, 9, true, true, 'ABC Transformers', 'abct')""")
    cut = datetime(2026, 2, 2, 9, 0, tzinfo=IST)
    ex = D.exposure(db, abc, cut)
    assert ex["snapshot"] == "2025-12-31"
    assert [(t["product"], t["first_flagged"], t["snapshots_flagged"], t["source"]) for t in ex["themes"]] == \
        [("CRGO Steel", "2024-12-31", 2, "inflection")]
    early = D.exposure(db, abc, datetime(2025, 3, 1, tzinfo=IST))
    assert early["snapshot"] == "2024-12-31" and early["themes"][0]["conviction"] == 0.7
    assert D.exposure(db, xyz, cut) == {"snapshot": "2025-12-31", "themes": []}
    assert D.exposure(db, abc, datetime(2024, 6, 1, tzinfo=IST)) == {"snapshot": None, "themes": []}
    # system replay: rows recorded after the cutoff are invisible
    assert D.exposure(db, abc, cut, "ACTUAL_SYSTEM_REPLAY")["snapshot"] is None

    with pytest.raises(Exception):
        db.execute("UPDATE theme_beneficiaries SET conviction_score = 0")
