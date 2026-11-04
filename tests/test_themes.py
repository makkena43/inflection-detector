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
    assert ex["themes"][0]["company_role"] is None                       # no makrograph_ref tables: unknown

    # evidence of what the company makes, from MakroGraph's capability / role ledgers (point in time)
    db.execute("""CREATE SCHEMA makrograph_ref;
                  CREATE TABLE makrograph_ref.mg_company_capabilities (as_of_date date, ticker text, product text,
                                                                       manufacturer bool);
                  CREATE TABLE makrograph_ref.mg_company_product_roles (country text, as_of_date date, ticker text,
                      normalized_product text, role_type text, adjudication_state text, last_evidence_date date)""")
    assert D.exposure(db, abc, cut)["themes"][0]["company_role"] == "MENTION_ONLY"
    db.execute("""INSERT INTO makrograph_ref.mg_company_product_roles VALUES
                  ('IN', '2025-06-30', 'ABCT', 'crgo electrical steel', 'DIRECT_PRODUCT_SUPPLIER',
                   'EARNINGS_CAPTURE_EVIDENCED', '2025-06-01'),
                  ('IN', '2025-06-30', 'ABCT', 'crgo lamination', 'MANUFACTURER', 'QUARANTINED_AMBIGUOUS_ROLE',
                   '2025-06-01')""")
    assert D.exposure(db, abc, cut)["themes"][0]["company_role"] == "SUPPLIER"
    db.execute("INSERT INTO makrograph_ref.mg_company_capabilities VALUES ('2026-06-30', 'ABCT', 'CRGO Steel', true)")
    assert D.exposure(db, abc, cut)["themes"][0]["company_role"] == "SUPPLIER"     # dated after the cutoff
    db.execute("INSERT INTO makrograph_ref.mg_company_capabilities VALUES ('2025-12-31', 'ABCT', 'CRGO Steel', true)")
    assert D.exposure(db, abc, cut)["themes"][0]["company_role"] == "MAKER"
    # ...unless its own order passages mostly describe EPC work
    mid = db.execute("""INSERT INTO commercial_mentions (rules_version, text_artifact_id, document_version_id,
                            publication_id, issuer_id, published_at, source_url, page_no, span_start, span_end, quote,
                            family, event_type, commercial_stage, modality, observation_status, relationship,
                            amount, currency, scale, amount_basis)
                        SELECT 'r', a.text_artifact_id, p.document_version_id, p.publication_id, p.issuer_id,
                               p.published_at, 'u', 1, 0, 1, 'q', 'ORDER', 'ORDER', 'BINDING_DEMAND', 'REALIZED',
                               'OBSERVED', 'UNKNOWN', 100, 'INR', 'CRORE', 'FIRM'
                          FROM document_publications p JOIN text_artifacts a USING (document_version_id)
                         WHERE p.issuer_id = %s LIMIT 1 RETURNING mention_id""", (abc,)).fetchone()[0]
    for n in range(2):
        db.execute("""INSERT INTO theme_phrase_mentions (mention_id, issuer_id, source_key, quote_md5, published_at,
                          family, phrases, version, role) VALUES (%s,%s,%s,%s,'2025-10-01','ORDER','{}',%s,'EPC')""",
                   (mid, abc, f"k{n}", f"m{n}", E.VERSION))
    assert D.exposure(db, abc, cut)["themes"][0]["company_role"] == "EPC"

    with pytest.raises(Exception):
        db.execute("UPDATE theme_beneficiaries SET conviction_score = 0")


# ---------------- emergent themes ----------------
from inflection.themes import emergent as E


def test_phrases_are_content_word_runs():
    q = ("Dear Sir/Madam, BSE Limited. The Company has received an order worth Rs 120 crore for supply of 765 kV "
         "power transformers to PGCIL. The equity shares are listed.")
    p = E.phrases(q)
    assert p == ["power", "transformers", "power transformers"]          # only the object of the order
    assert "bse limited" in E.phrases(q, objects_only=False)              # what the old method picked up


def _rows(as_of):
    rows = []
    d_recent, d_prior = as_of - timedelta(days=30), as_of - timedelta(days=400)
    for c in ("A", "B", "C", "D", "E"):                       # five companies now win transformer orders
        rows.append((c, d_recent, ["power transformers", "transformers", "letter of award"], 50))
    rows.append(("A", d_prior, ["power transformers", "letter of award"], 10))   # one did a year ago
    rows.append(("F", d_recent, ["power transformers", "letter of award"], None))
    for i in range(300):                                      # generic language used by most companies
        rows.append((f"Z{i}", d_prior, ["letter of award", f"product {i}"], None))
    rows.append(("G", as_of, ["power transformers"], 999))    # filed on the as_of day: outside
    return rows


def test_build_finds_accelerating_theme_and_drops_generic_language():
    as_of = date(2025, 12, 31)
    themes = E.build(_rows(as_of), as_of)
    assert [t["name"] for t in themes] == ["power transformers"]
    t = themes[0]
    assert set(t["phrases"]) == {"power transformers", "transformers"}    # merged: same companies
    assert (t["companies"], t["companies_prior"], t["growth_pct"], t["stage"]) == (6, 1, 500.0, 1)
    assert t["order_value_cr"] == 250 and t["members"][0]["first_seen"] in (as_of - timedelta(days=30), as_of - timedelta(days=400))
    assert {m["issuer_id"] for m in t["members"]} == {"A", "B", "C", "D", "E", "F"}


def test_cue_word_only_phrases_are_dropped():
    p = E.phrases("Received a work order for supply of civil works and production capacity expansion.")
    assert "civil works" in p and "work order" not in p and "production capacity" not in p


def test_specificity_drops_words_common_in_ordinary_filings():
    as_of = date(2025, 12, 31)
    rows = []
    for c in ("A", "B", "C", "D"):
        rows.append((c, as_of - timedelta(days=20), ["bess", "months"], 10))
    for i in range(40):                                       # other order passages
        rows.append((f"Y{i}", as_of - timedelta(days=50), [f"widget {i}"], None))
    bg = ({"months": 5000, "bess": 2}, 100000)               # "months" is everywhere in ordinary filings
    themes = E.build(rows, as_of, bg)
    assert [(t["name"], t["phrases"]) for t in themes] == [("bess", ["bess"])] and themes[0]["specificity"] > 8
    assert set(E.build(rows, as_of)[0]["phrases"]) == {"bess", "months"}   # without a background "months" joins


def test_role_from_wording():
    assert E.role("ORDER", "The Company has received an order for supply of power transformers.") == "SUPPLIER"
    assert E.role("ORDER", "Bagged an EPC order for erection of a 220 kV substation.") == "EPC"
    assert E.role("ORDER", "The Company has placed an order for solar modules with Waaree Energies.") == "BUYER"
    assert E.role("CAPACITY", "Commissioned a 5 MW solar plant for captive consumption.") == "BUYER"
    assert E.role("CAPACITY", "Commenced commercial production of lithium-ion cells.") == "MAKER"
    assert E.role("ORDER", "Order book stands at Rs 500 crore.") is None
    assert E.company_role(["BUYER", "SUPPLIER", "SUPPLIER", None]) == "SUPPLIER"
    assert E.company_role(["BUYER", "MAKER"]) == "MAKER" and E.company_role([None]) is None


def test_build_carries_company_role():
    as_of = date(2025, 12, 31)
    rows = [(c, as_of - timedelta(days=10), ["bess"], 10, r) for c, r in (("A", "SUPPLIER"), ("B", "BUYER"), ("C", None))]
    t = E.build(rows, as_of)[0]
    assert {m["issuer_id"]: m["role"] for m in t["members"]} == {"A": "SUPPLIER", "B": "BUYER", "C": None}


def test_only_labelled_yes_phrases_form_themes():
    as_of = date(2025, 12, 31)
    rows = [(c, as_of - timedelta(days=10), ["bess", "commissioned"], 10) for c in "ABC"]
    rows += [(c, as_of - timedelta(days=10), ["mtpa"], None) for c in "DEF"]
    themes = E.build(rows, as_of, allowed=frozenset({"bess"}))
    assert [(t["name"], t["phrases"]) for t in themes] == [("bess", ["bess"])]


def test_label_phrases_cached(db):
    from inflection.themes import labels as L
    assert L.parse("Yes.") is True and L.parse("no") is False and L.parse("maybe") is None
    db.execute("INSERT INTO theme_background_runs VALUES (%s, '2021-01-01', '2022-01-01', 1, 1000)", (E.BACKGROUND_VERSION,))
    E._BG_CACHE.clear()
    E._LABEL_CACHE.clear()
    cos = [_company(db, f"Co {i} Limited", f"CO{i}", f"INE{i:03d}A01011") for i in range(3)]
    src = db.execute("""INSERT INTO sources (name, kind, access_policy) VALUES ('nse_announcements', 'announcements',
                        'test') RETURNING source_id""").fetchone()[0]
    for i, iss in enumerate(cos):
        pub = _filing(db, iss, src, 300 + i, datetime(2025, 11, 10, 18, 0, tzinfo=IST), "x")
        ver, art = db.execute("""SELECT p.document_version_id, a.text_artifact_id FROM document_publications p
                                  JOIN text_artifacts a USING (document_version_id) WHERE p.publication_id = %s""",
                              (pub,)).fetchone()
        mid = db.execute("""INSERT INTO commercial_mentions (rules_version, text_artifact_id, document_version_id,
                              publication_id, issuer_id, published_at, source_url, page_no, span_start, span_end,
                              quote, family, event_type, commercial_stage, modality, observation_status, amount,
                              currency, scale, amount_basis, relationship)
                            VALUES ('r',%s,%s,%s,%s,now(),'u',1,0,1,'q','ORDER','ORDER','BINDING_DEMAND','REALIZED',
                                    'OBSERVED',1,'INR','CRORE','FIRM','UNKNOWN') RETURNING mention_id""",
                         (art, ver, pub, iss)).fetchone()[0]
        db.execute("""INSERT INTO theme_phrase_mentions (mention_id, issuer_id, source_key, quote_md5, published_at,
                          family, phrases, version) VALUES (%s,%s,%s,'m',now(),'ORDER',%s,%s)""",
                   (mid, iss, str(pub), ["bess", "commissioned"], E.VERSION))
    asked = []
    res = L.label(db, ask=lambda p: asked.append(p) or ("no" if p == "commissioned" else "Yes"))
    assert res["yes"] == 1 and res["no"] == 1 and sorted(asked) == ["bess", "commissioned"]
    assert L.label(db, ask=lambda p: 1 / 0)["candidates"] == 0          # cached: never asked again
    assert E.load_allowed(db) == frozenset({"bess"})
    E._BG_CACHE.clear()
    E._LABEL_CACHE.clear()


def test_generic_expansion_phrases_are_not_themes():
    as_of = date(2025, 12, 31)
    rows = [(c, as_of - timedelta(days=10), ["new manufacturing facility", "greenfield expansion", "water treatment plant"],
             None) for c in "ABC"]
    assert [t["phrases"] for t in E.build(rows, as_of)] == [["water treatment plant"]]


def test_theme_grade():
    from inflection.themes.context import grade
    assert grade(1, 800.0, 2, "MAKER", True)[0] == "A"
    assert grade(2, 50.0, -3, "SUPPLIER", True)[0] == "B"            # losing companies over 13 weeks
    assert grade(2, 50.0, 0, "EPC", False)[0] == "B"                  # packet's event not in the theme
    assert grade(3, 20.0, 1, "MAKER", True)[0] == "B" and grade(3, 60.0, 1, "MAKER", True)[0] == "A"
    assert grade(4, 0.0, 0, "MAKER", True)[0] == "CROWDED"
    assert grade(2, 50.0, 1, "BUYER", True)[0] == "HEADWIND" and grade(5, -40.0, -5, "MAKER", True)[0] == "HEADWIND"
    assert grade(2, 50.0, 1, None, True)[0] == "NONE" and grade(0, None, None, "MAKER", True)[0] == "NONE"


def test_stage_thresholds():
    assert [E._stage(n, g) for n, g in ((3, None), (5, 50.0), (12, 10.0), (30, 5.0), (30, 0.0), (8, -40.0))] == \
        [0, 1, 2, 3, 4, 5]


def test_theme_key_carries_over_when_phrases_overlap():
    themes = [dict(phrases=["power transformers", "transformers", "switchgear"])]
    E._carry_keys(themes, [("power-transformers@2025-12-27", ["power transformers", "transformers"], date(2025, 6, 7))])
    assert themes[0]["theme_key"] == "power-transformers@2025-12-27" and themes[0]["first_detected"] == date(2025, 6, 7)


def test_emergent_section_render():
    out = "\n".join(C.emergent_section({"snapshot": "2026-10-31", "themes": [dict(
        theme="power transformers", stage=2, companies=14, companies_year_ago=6, growth_pct=133.3,
        theme_first_detected="2025-06-07", company_mentions=3, company_value_cr=420.0, company_first_seen="2026-02-10",
        phrases=["power transformers", "transformers"])]}))
    assert "2 accelerating" in out and "14 (6)" in out and "3, 420, 2026-02-10" in out


def test_emergent_index_snapshot_and_exposure(db):
    src = db.execute("""INSERT INTO sources (name, kind, access_policy) VALUES ('nse_announcements', 'announcements',
                        'test') RETURNING source_id""").fetchone()[0]
    cos = [_company(db, f"Co {i} Limited", f"CO{i}", f"INE{i:03d}A01011") for i in range(6)]
    when = datetime(2025, 11, 10, 18, 0, tzinfo=IST)
    for i, iss in enumerate(cos):
        pub = _filing(db, iss, src, 100 + i, when, "order")
        ver, art = db.execute("""SELECT p.document_version_id, a.text_artifact_id FROM document_publications p
                                  JOIN text_artifacts a USING (document_version_id) WHERE p.publication_id = %s""",
                              (pub,)).fetchone()
        quote = "Received order for supply of power transformers and switchgear to a state utility."
        for rules in ("r1", "r2"):                       # two rules versions of one passage: indexed once
            db.execute("""INSERT INTO commercial_mentions (rules_version, text_artifact_id, document_version_id,
                              publication_id, issuer_id, published_at, source_url, page_no, span_start, span_end,
                              quote, family, event_type, commercial_stage, modality, observation_status, amount,
                              currency, scale, amount_basis, relationship)
                          VALUES (%s,%s,%s,%s,%s,%s,'u',1,0,10,%s,'ORDER','ORDER','BINDING_DEMAND','REALIZED',
                                  'OBSERVED',100,'INR','CRORE','FIRM','UNKNOWN')""",
                       (rules, art, ver, pub, iss, when, quote))
    assert E.index(db) == {"indexed": 6}
    assert E.index(db) == {"indexed": 0}
    assert "error" in E.snapshot(db, date(2025, 11, 15), spec_min=8)          # no background yet: nothing written
    for i in range(3):                                            # ordinary filings: board meeting language
        _filing(db, cos[i], src, 200 + i, datetime(2025, 3, 1, 18, 0, tzinfo=IST),
                "The board approved the results. The meeting ended at 5 pm. Power transformers were not discussed.")
    bg = E.background(db, date(2025, 1, 1), date(2025, 6, 1))
    assert bg["documents"] == 3 and bg["sentences"] == 9 and bg["phrases_seen"] >= 1
    assert E.background(db, date(2025, 1, 1), date(2025, 6, 1))["skipped"] == "exists"
    res = E.snapshot(db, date(2025, 11, 15), spec_min=8)
    assert res["themes"] >= 1
    assert E.snapshot(db, date(2025, 11, 15), spec_min=8) == {"as_of": "2025-11-15", "skipped": "exists"}
    ex = E.exposure(db, cos[0], datetime(2025, 11, 20, 9, 0, tzinfo=IST))
    assert ex["snapshot"] == "2025-11-15" and ex["themes"]
    top = ex["themes"][0]
    assert top["companies"] == 6 and top["company_value_cr"] == 100.0 and top["stage"] == 1
    assert top["company_role"] == "SUPPLIER"
    assert E.exposure(db, cos[0], datetime(2025, 11, 1, tzinfo=IST)) == {"snapshot": None, "themes": []}
    nxt = E.snapshot(db, date(2025, 11, 22), spec_min=8)                 # next week keeps the theme key
    from inflection.themes.context import assess
    ev = "00000000-0000-0000-0000-0000000000e1"
    res = assess(db, cos[0], datetime(2025, 11, 25, 9, 0, tzinfo=IST),
                 [dict(event_id=ev, quote="LoA for supply of switchgear to a state utility"),
                  dict(event_id="other", quote="Board meeting outcome")])
    t = res["themes"][0]
    assert res["snapshot"] == "2025-11-22" and t["role"] == "SUPPLIER" and t["packet_events_in_theme"] == [ev]
    assert t["companies"] == 6 and t["company_rank"] == 1 and t["entrant"] == "EARLY" and t["momentum_13w"] is None
    assert t["grade"] == "A" and res["best_grade"] == "A"
    assert assess(db, cos[0], datetime(2025, 11, 1, tzinfo=IST), [])["snapshot"] is None
    out = "\n".join(C.theme_assessment_section(res))
    assert "Overall theme grade: **A**" in out and "supplier, #1" in out
    keys = db.execute("SELECT as_of, theme_key FROM emergent_theme_snapshots ORDER BY as_of, theme_key").fetchall()
    assert {k for d, k in keys if d == date(2025, 11, 15)} == {k for d, k in keys if d == date(2025, 11, 22)}
