"""The commercial route: passages, company events, materiality and priority (pure), then the
database pipeline end to end on real PostgreSQL.

Order cases are ported from MakroGraph ``tests/earnings_inflection/test_wp4_external_demand.py``
at b31bdd0; the rest are new.
"""

import re
from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest

from inflection.asof import IST
from inflection.commercial import pipeline
from inflection.commercial import vocabulary as V
from inflection.commercial.extract import extract_document, split_page, window_end
from inflection.commercial.resolve import Resolver, assess, evaluation, materiality

PO = ("The Company has received a purchase order worth Rs 450 crore from Eastern Rail Systems Limited for supply "
      "of bogie frames.")


def mentions(text, page=1):
    return extract_document([(page, text)])[0]


def one(text):
    (m,) = mentions(text)
    return m


def resolve(*docs):
    """docs: (doc_id, text, 'YYYY-MM-DD') -> (resolver, placements)"""
    r = Resolver("issuer")
    out = []
    for doc_id, text, when in docs:
        at = datetime.fromisoformat(when + "T12:00:00+05:30")
        for m in mentions(text):
            out.append(r.place(m, at, doc_id))
    return r, out


# ---------------- passages ----------------

def test_sentence_spans_point_into_the_page():
    body = "Outcome of Board Meeting\n\n1. The Company has received a purchase order\nfrom Eastern Rail Systems " \
           "Limited worth Rs. 450 crore. 2. Purchase order No. ERS/11 dated 1.2.2024 applies."
    for s in split_page(3, body):
        assert re.sub(r"\s+", " ", body[s.start:s.end]).strip() == s.text and s.page_no == 3
    texts = [s.text for s in split_page(3, body)]
    assert "1. The Company has received a purchase order from Eastern Rail Systems Limited worth Rs. 450 crore." \
        in texts                                                    # "Rs." is not a sentence end


def test_order_terms_and_observed_award_despite_future_execution():
    m = one("XYZ Limited has received an order worth Rs. 358 crore (exclusive of GST) from NTPC Limited for supply "
            "of transformers, which will be executed over 18 months.")
    assert (m.family, m.stage, m.modality, m.observation_status) == ("ORDER", "BINDING_DEMAND", "REALIZED", "OBSERVED")
    assert (m.amount.value, m.amount.scale.value, m.amount_basis) == (Decimal(358), "CRORE", "FIRM")
    assert (m.counterparty, m.counterparty_named) == ("NTPC Limited", True)
    assert m.details["duration_months"] == 18 and m.details["tax_basis"] == "EXCLUSIVE"
    assert m.details["product"] == "transformers"


@pytest.mark.parametrize("text,basis,stage", [
    ("The Company has signed a framework agreement with Northern Utility Limited for supplies up to Rs 1,000 crore.",
     "CEILING", "QUALIFIED"),
    ("The Company has received a purchase order worth Rs 100 crore from Northern Utility Limited with a minimum "
     "guaranteed offtake.", "GUARANTEED_MINIMUM", "BINDING_DEMAND"),
    ("The Company has received a release order worth Rs 60 crore from Northern Utility Limited under the rate "
     "contract.", "EXECUTABLE_RELEASE", "BINDING_DEMAND"),
    ("The Company has signed an MoU with Northern Utility Limited for supply of meters worth Rs 500 crore.",
     "NON_BINDING", "AMBITION"),
    ("The Company has been declared L1 bidder for a Rs 450 crore tender of Eastern Rail Systems Limited.",
     "NON_BINDING", "QUALIFIED"),
])
def test_value_basis_and_stage(text, basis, stage):        # ported (basis), stage mapping new
    m = one(text)
    assert (m.amount_basis, m.stage) == (basis, stage)


def test_plain_rupee_amounts_and_order_references():
    m = one("The Company has received a purchase order No. PO/2026/123 for Rs. 4,50,00,000/- from Larsen & Toubro "
            "Limited.")
    assert (m.amount.value, m.amount.scale.value) == (Decimal(45000000), "UNITS")
    assert m.details["reference_id"] == "PO/2026/123" and m.counterparty == "Larsen & Toubro Limited"


@pytest.mark.parametrize("text", [
    "The Company has received an assessment order from the Income Tax Department raising a demand of Rs 3 crore.",
    "The Company has received an order from the Hon'ble NCLT approving the scheme of amalgamation.",
    "Our order book stands at Rs 1,400 crore as of June 30, 2024.",
    "This presentation contains forward-looking statements; the Company has received orders worth Rs 100 crore.",
    "The purchase order from Eastern Rail Systems Limited has not been cancelled.",
    "The Company has received assessments orders and necessary appeals have been filed.",
    "The Company has received orders for remaining years i.e. AY 16-17 to AY 19-20 and is filing appeals.",
    "During the quarter, the Company received an order from the CCI alleging cartelisation in the supply of products.",
    "Modification / cancellation of orders and multiple bids from a single Eligible Shareholder will be allowed during "
    "the tendering period of the Buyback.",
    "Previous period figures have been regrouped in order to comply with the requirements of amended Schedule III.",
    "Repayment of long term borrowings (2,316.72) (1,878.84)",
    "This Statement is the responsibility of the Company's Management and has been approved by the Board of Directors.",
    "Was there any price increase that we witnessed in this quarter in our key products?",
    "Raw material price increases across ammonia and potash hurt margins.",
])

def test_not_customer_orders(text):
    assert mentions(text) == []


def test_order_value_stated_in_its_own_sentence_is_one_order():
    (m,) = mentions("The Company has received a work order from NTPC Limited for supply of meters. The order is worth "
                    "Rs 120 crore.")
    assert m.amount.value == 120 and m.details["amount_source"]["quote"] == "The order is worth Rs 120 crore."


def test_real_order_wordings():           # from NSE filings in MakroGraph's 2024-03-31 export
    m = one("Shaily received first order from Spin Master during the quarter.")
    assert (m.stage, m.counterparty, m.details["first_order"]) == ("BINDING_DEMAND", "Spin Master", True)
    m = one("We are pleased to announce that the Company has received confirmed additional Export Orders worth of "
            "Rs. 100 crores from its International clients.")
    assert (m.stage, m.amount.value, m.amount_basis) == ("BINDING_DEMAND", Decimal(100), "FIRM")
    m = one("During Q1, Goldiam had won an order worth ₹ 300 million for a retailer in the Middle East.")
    assert (m.stage, m.amount.value, m.amount.scale.value) == ("BINDING_DEMAND", Decimal(300), "MILLION")


def test_forecast_order_is_an_ambition_not_demand():
    m = one("The Company expects to receive orders worth Rs 500 crore from Indian Railways in H2 FY27.")
    assert (m.stage, m.observation_status, m.details["stated_stage"]) == ("AMBITION", "FORECAST", "UNKNOWN")
    assert m.details["deadline"] == "2027-03-31"


def test_subsidiary_recipient_is_scope_not_related_party():
    m = one("Our wholly owned subsidiary ABC Private Limited has bagged an order of Rs 50 crore from Tata Power "
            "Company Limited.")
    assert (m.relationship, m.ownership_scope, m.counterparty) == ("UNKNOWN", "SUBSIDIARY", "Tata Power Company Limited")
    own = one("The Company has received a purchase order worth Rs 200 crore from Rail Components Limited, its wholly "
              "owned subsidiary.")
    assert own.relationship == "CONFIRMED_RELATED"                            # ported
    other = one("The Company has received a purchase order worth Rs 200 crore from Metro Coach Limited, a subsidiary "
                "of Global Mobility Corporation.")
    assert other.relationship == "UNKNOWN"                                    # ported


SEBI_ANNEX = """Disclosure under Regulation 30 of SEBI (LODR) Regulations, 2015

We are pleased to inform that the Company has received a work order for supply of 7,781 solar pumps.

Details of the order:
a) Name of the entity awarding the order(s)/contract(s): Maharashtra State Electricity Distribution Co. Ltd
b) Significant terms and conditions of order(s)/contract(s) awarded in brief: Supply and installation
c) Whether order(s)/contract(s) have been awarded by domestic/international entity: Domestic
d) Nature of order(s)/contract(s): Supply
e) Whether domestic or international: Domestic
f) Time period by which the order(s)/contract(s) is to be executed: 18 months
g) Broad consideration or size of the order(s)/contract(s): approximately Rs. 358 Crores
h) Whether the promoter / promoter group / group companies have any interest in the entity that awarded the order: No
i) Whether the order(s)/contract(s) would fall within related party transactions? If yes, whether the same is done at arm's length: No
"""


def test_sebi_annexure_fills_value_customer_period_and_relationship():
    (m,) = [x for x in mentions(SEBI_ANNEX) if x.family == "ORDER"]
    assert (m.amount.value, m.amount_basis) == (Decimal(358), "FIRM")
    assert m.details["amount_source"]["quote"].startswith("g) Broad consideration")
    assert m.counterparty == "Maharashtra State Electricity Distribution Co. Ltd" and m.counterparty_named
    assert m.details["duration_months"] == 18 and m.details["customer_geography"] == "DOMESTIC"
    assert m.relationship == "ISSUER_ASSERTED_UNRELATED"


@pytest.mark.parametrize("text,family,stage,observation", [
    ("The Company has commenced commercial production at its Dahej plant.", "COMMERCIAL_START",
     "COMMERCIAL_SHIPMENT", "OBSERVED"),
    ("We expect to commence commercial production at the Dahej plant by Q3FY27.", "COMMERCIAL_START", "AMBITION",
     "FORECAST"),
    ("The Company has been approved as a vendor by Maruti Suzuki India Limited.", "QUALIFICATION", "QUALIFIED",
     "OBSERVED"),
    ("The Board approved capex of Rs 500 crore for capacity expansion at the Hosur plant to 10,000 TPA.", "CAPACITY",
     "FUNDED_PLAN", "FORECAST"),
    ("The Company has signed an MoU with the Government of Gujarat for setting up a plant with an investment of "
     "Rs 2,000 crore.", "CAPACITY", "AMBITION", "FORECAST"),
    ("The Company has prepaid term loans of Rs 200 crore from the proceeds of the QIP.", "DEBT_REDUCTION", "UNKNOWN",
     "OBSERVED"),
    ("The Company has completed the sale of its loss-making textiles subsidiary.", "LOSS_DRAG_REMOVAL", "UNKNOWN",
     "OBSERVED"),
])
def test_families(text, family, stage, observation):
    m = one(text)
    assert (m.family, m.stage, m.observation_status) == (family, stage, observation)


def test_period_ends():
    assert [window_end(x) for x in ("Q3FY27", "FY27", "H1 FY2027", "March 2027", "Sept 2026")] == [
        date(2026, 12, 31), date(2027, 3, 31), date(2026, 9, 30), date(2027, 3, 31), date(2026, 9, 30)]


# ---------------- company events (ported dated states) ----------------

def test_partial_cancellation_reduces_current_value_and_keeps_history():
    r, ps = resolve(("A", PO, "2024-02-10"),
                    ("B", "Eastern Rail Systems Limited has cancelled Rs 150 crore of the purchase order for bogie "
                          "frames.", "2024-07-01"))
    assert [p.outcome for p in ps] == ["NEW", "REVISION"]
    (e,) = r.events
    assert e.amount.value == 300 and e.original_amount.value == 450 and e.stage == "BINDING_DEMAND"
    assert e.version_no == 2 and ps[1].supersedes == ps[0].event.version_id


def test_full_cancellation_reverses_the_commitment():
    r, ps = resolve(("A", PO, "2024-02-10"),
                    ("B", "The purchase order from Eastern Rail Systems Limited has been cancelled by the customer.",
                     "2024-07-01"))
    (e,) = r.events
    assert e.stage == "CANCELLED" and e.amount.value == 0 and ps[1].previous_stage == "BINDING_DEMAND"


def test_amendment_can_reduce_value():
    r, _ = resolve(("A", PO, "2024-02-10"),
                   ("B", "The order value from Eastern Rail Systems Limited has been revised to Rs 300 crore.",
                    "2024-05-01"))
    (e,) = r.events
    assert e.amount.value == 300 and e.details["amended_from"] == "450 CRORE"


def test_l1_progresses_to_po_and_a_later_retelling_never_downgrades():
    r, ps = resolve(("A", "The Company has been declared L1 bidder for a Rs 450 crore tender of Eastern Rail Systems "
                          "Limited.", "2024-01-10"),
                    ("B", PO, "2024-03-01"),
                    ("C", "Earlier this year we were L1 for the Rs 450 crore bogie frames tender of Eastern Rail "
                          "Systems Limited.", "2024-08-01"))
    assert [p.outcome for p in ps] == ["NEW", "REVISION", "REPETITION"]
    (e,) = r.events
    assert (e.stage, e.basis, e.version_no) == ("BINDING_DEMAND", "FIRM", 2)
    assert e.artifacts == {"A", "B", "C"}


def test_unlinked_cancellation_is_recorded_but_never_counted_as_demand():
    r, (p,) = resolve(("B", "An order worth Rs 80 crore has been cancelled.", "2024-07-01"))
    assert p.novelty == "HISTORY_UNAVAILABLE" and p.event.amount is None and p.event.stage == "CANCELLED"


def test_same_amount_different_named_customers_are_two_orders():
    r, ps = resolve(("A", PO, "2024-02-10"),
                    ("B", PO.replace("Eastern Rail Systems Limited", "Western Coach Limited"), "2024-02-20"))
    assert [p.outcome for p in ps] == ["NEW", "NEW"] and "ambiguous_with" not in r.events[1].details


def test_same_amount_unnamed_mention_is_ambiguous():
    r, ps = resolve(("A", PO, "2024-02-10"),
                    ("B", "We bagged an order worth Rs 450 crore for bogie frames.", "2024-03-05"))
    assert [p.outcome for p in ps] == ["NEW", "NEW"]
    assert r.events[1].details["ambiguous_with"] == [r.events[0].event_id]


def test_different_order_references_are_different_orders():
    r, ps = resolve(("A", PO.replace("purchase order", "purchase order No. ERS/2024/011"), "2024-02-10"),
                    ("B", PO.replace("purchase order", "purchase order No. ERS/2024/019"), "2024-02-11"))
    assert len(r.events) == 2


def test_same_order_in_another_filing_is_a_repetition_and_a_repeat_order_is_new():
    r, ps = resolve(("A", PO, "2024-02-10"),
                    ("B", PO, "2024-02-11"),
                    ("C", "The Company has received a repeat order worth Rs 450 crore from Eastern Rail Systems "
                          "Limited for supply of bogie frames.", "2024-09-01"))
    assert [p.outcome for p in ps] == ["NEW", "REPETITION", "NEW"]
    assert r.events[1].stage == "REPEAT_SHIPMENT" and r.events[1].details["repeat_of"] == r.events[0].event_id


def test_an_older_filing_read_late_is_an_earlier_disclosure():
    r, ps = resolve(("B", PO, "2024-03-01"), ("A", PO, "2024-02-10"))
    assert [p.outcome for p in ps] == ["NEW", "EARLIER_DISCLOSURE"]
    assert r.events[0].first_public_at.date() == date(2024, 2, 10)


def test_capacity_plan_becomes_commercial_production_at_the_same_plant():
    r, ps = resolve(("A", "The Board approved capex of Rs 500 crore for capacity expansion at the Hosur plant.",
                     "2024-01-10"),
                    ("B", "The Company has commenced commercial production at its Hosur plant.", "2025-03-01"))
    assert [p.outcome for p in ps] == ["NEW", "REVISION"]
    (e,) = r.events
    assert (e.event_type, e.stage, e.observation) == ("CAPACITY", "COMMERCIAL_SHIPMENT", "OBSERVED")


def test_repeated_guidance_does_not_advance_stage():
    text = "We plan to set up a new plant at Nagpur to double capacity."
    r, ps = resolve(("A", text, "2024-01-10"), ("B", text, "2024-04-10"))
    assert [p.outcome for p in ps] == ["NEW", "REPETITION"] and r.events[0].stage == "AMBITION"


# ---------------- materiality and priority (spec 18.2 and phase 2 acceptance) ----------------

CR = Decimal(10) ** 7


def _assessed(text, revenue_cr=None, active=False, equity=False):
    r, ps = resolve(("A", text, "2026-01-10"))
    p = ps[-1]
    mat = materiality(p.event, revenue_cr * CR if revenue_cr else None)
    return assess(p.event, p.novelty, p.previous_stage, mat, active, equity)


def test_material_binding_order_with_milestone_is_p1():
    a = _assessed(PO.replace(".", ", to be executed over 24 months."), revenue_cr=1500)
    assert a.materiality.status == "MATERIAL_POTENTIAL" and a.materiality.ratio_annualised == Decimal("0.15")
    assert a.priority == "P1" and a.milestone == date(2028, 1, 10)


def test_missing_magnitude_is_not_an_exclusion():
    a = _assessed("The Company has bagged an order from Eastern Rail Systems Limited for supply of bogie frames.",
                  revenue_cr=1500)
    assert (a.materiality.status, a.priority) == ("MATERIALITY_UNKNOWN", "P2")


def test_unknown_execution_period_keeps_materiality_unknown_but_records_the_ratio():
    a = _assessed(PO, revenue_cr=1500)
    assert a.materiality.status == "MATERIALITY_UNKNOWN" and a.materiality.ratio_total == Decimal("0.3")
    assert a.materiality.band == 2 and a.priority == "P2"


def test_small_order_is_immaterial_and_ceiling_is_unknown():
    assert _assessed(PO, revenue_cr=50000).materiality.status == "IMMATERIAL"
    a = _assessed("The Company has signed a framework agreement with Northern Utility Limited for supplies up to "
                  "Rs 1,000 crore.", revenue_cr=1500)
    assert a.materiality.status == "MATERIALITY_UNKNOWN" and "ceiling" in a.materiality.reason


def test_muted_quarter_qualification_enters_discovery():
    a = _assessed("The Company has been approved as a vendor by Maruti Suzuki India Limited.")
    assert a.priority == "P2"


def test_generic_expansion_remains_watch():
    a = _assessed("The Board approved capex of Rs 500 crore for capacity expansion at the Hosur plant.")
    assert a.priority == "P3" and "capacity" in a.reason


def test_shareholder_financing_is_not_operating_debt_repayment():
    assert _assessed("The Company has prepaid term loans of Rs 200 crore from the proceeds of the QIP.").priority == "P3"
    assert _assessed("The Company has prepaid term loans of Rs 200 crore.", equity=True).priority == "P3"
    assert _assessed("The Company has prepaid term loans of Rs 200 crore.").priority == "P2"
    assert _assessed("Finance costs reduced by nearly 29% Y-o-Y in Q3 FY2021.").priority == "P3"


def test_related_party_and_open_case_routing():
    assert _assessed("The Company has received a purchase order worth Rs 900 crore from Rail Components Limited, "
                     "its wholly owned subsidiary.", revenue_cr=1000).priority == "P3"
    assert _assessed(PO, revenue_cr=1500, active=True).priority == "U0"


def test_one_evaluation_per_filing_takes_the_best_class():
    a = _assessed(PO.replace(".", ", to be executed over 24 months."), revenue_cr=1500)
    b = _assessed("The Board approved capex of Rs 500 crore for capacity expansion at the Hosur plant.")
    ev = evaluation([b, a], "issuer", datetime(2026, 1, 10, tzinfo=IST))
    assert (ev["priority_class"], ev["outcome"], ev["queue_allocation"]) == ("P1", "ADMIT", "RANKED")
    assert len(ev["reasons"]) == 2 and ev["materiality"] == "MATERIAL_POTENTIAL"
    assert evaluation([b], "issuer", datetime(2026, 1, 10, tzinfo=IST))["outcome"] == "DEFER"


def test_policy_hash_is_stable():
    assert V.policy_hash() == V.policy_hash() and len(V.policy_hash()) == 64


# ---------------- database pipeline ----------------

def _seed(db):
    iss = db.execute("INSERT INTO issuers (legal_name) VALUES ('ABC Limited') RETURNING issuer_id").fetchone()[0]
    sec = db.execute("INSERT INTO securities (issuer_id, isin) VALUES (%s, 'INE111A01011') RETURNING security_id",
                     (iss,)).fetchone()[0]
    db.execute("""INSERT INTO identifier_history (security_id, exchange, kind, value, valid_from, source)
                  VALUES (%s, 'NSE', 'SYMBOL', 'ABC', '2010-01-01', 'test')""", (sec,))
    src = db.execute("""INSERT INTO sources (name, kind, access_policy) VALUES ('nse_announcements', 'announcements',
                        'test') RETURNING source_id""").fetchone()[0]
    for end, value, ptype in (("2025-03-31", 1200, "ANNUAL"), ("2025-03-31", 300, "QUARTER"),
                              ("2025-06-30", 400, "QUARTER"), ("2025-09-30", 400, "QUARTER"),
                              ("2025-12-31", 400, "QUARTER")):
        db.execute("""INSERT INTO financial_facts (issuer_id, metric, period_end, scope, value, value_kind, currency,
                                                   scale, period_type, available_at, provider, provider_version,
                                                   content_hash)
                      VALUES (%s, 'revenue', %s, 'CONSOLIDATED', %s, 'MONEY', 'INR', 'UNITS', %s, %s, 'test', '1',
                              md5(%s))""",
                   (iss, end, Decimal(value) * CR, ptype, datetime.fromisoformat(end + "T18:00:00+05:30") + timedelta(days=15),
                    end + ptype))
    return iss, src


def _filing(db, iss, src, n, when, pages, category="Bagging/Receiving of orders/contracts"):
    doc = db.execute("INSERT INTO documents (issuer_id) VALUES (%s) RETURNING document_id", (iss,)).fetchone()[0]
    ver = db.execute("""INSERT INTO document_versions (document_id, sha256, storage_key, byte_size, media_type)
                        VALUES (%s, %s, 'k', 1, 'application/pdf') RETURNING document_version_id""",
                     (doc, f"{n:064x}")).fetchone()[0]
    db.execute("""INSERT INTO document_publications (document_version_id, source_id, external_id, source_url,
                                                     published_at, publication_basis, issuer_id, original_category,
                                                     pipeline_state)
                  VALUES (%s, %s, %s, %s, %s, 'EXCHANGE_TIMESTAMP', %s, %s, 'TEXT_READY')""",
               (ver, src, f"ann-{n}", f"https://x/{n}.pdf", when, iss, category))
    art = db.execute("""INSERT INTO text_artifacts (document_version_id, extraction_method, extraction_version, status,
                                                    pages_processed) VALUES (%s, 'pdfplumber', '1', 'COMPLETE', %s)
                        RETURNING text_artifact_id""", (ver, len(pages))).fetchone()[0]
    for i, body in enumerate(pages, 1):
        db.execute("INSERT INTO text_pages (text_artifact_id, page_no, body) VALUES (%s, %s, %s)", (art, i, body))
    return art


def test_pipeline_end_to_end(db):
    iss, src = _seed(db)
    t1 = datetime(2026, 1, 20, 18, 5, tzinfo=IST)
    _filing(db, iss, src, 1, t1, ["Cover letter", SEBI_ANNEX])
    _filing(db, iss, src, 2, t1 + timedelta(days=1), [SEBI_ANNEX.replace("Disclosure", "Re-filed disclosure")])
    _filing(db, iss, src, 3, t1 + timedelta(days=60),
            ["The Board approved capex of Rs 500 crore for capacity expansion at the Hosur plant."],
            category="Outcome of Board Meeting")
    _filing(db, iss, src, 4, t1, ["Closure of trading window"], category="Trading Window-XBRL")

    out = pipeline.scan(db)
    assert (out["SCANNED"], out["SKIPPED_CATEGORY"], out["family:ORDER"], out["family:CAPACITY"]) == (3, 1, 2, 1)
    assert pipeline.scan(db) == {}                                           # nothing is read twice

    res = pipeline.resolve(db, now=t1 + timedelta(days=61))
    assert (res["NEW"], res["REPETITION"], res["evaluations"]) == (2, 1, 2)
    assert pipeline.resolve(db) == {}

    ev = db.execute("""SELECT priority_class, outcome, materiality, mode, components->'revenue'->>'basis',
                              components->'events'->0->>'ratio_annualised'
                         FROM candidate_evaluations ORDER BY as_of""").fetchall()
    # 358 cr over 18 months = 238.7 cr a year against 1,500 cr (last four quarters, newer than FY25) = 15.9%
    assert ev == [("P1", "ADMIT", "MATERIAL_POTENTIAL", "PUBLIC_INFORMATION_RECONSTRUCTION", "LAST_FOUR_QUARTERS",
                   "0.1591"),
                  ("P3", "DEFER", "MATERIALITY_UNKNOWN", "LIVE", "LAST_FOUR_QUARTERS", None)]

    # evidence: the award sentence and the annexure value line, each a valid span on its page
    links = db.execute("""SELECT l.page_no, l.span_start, l.span_end, l.quote, p.body, l.relation, l.section
                            FROM evidence_links l JOIN text_pages p USING (text_artifact_id, page_no)
                           ORDER BY l.created_at, l.section""").fetchall()
    assert {(r[5], r[6]) for r in links} == {("SUPPORTS", "ORDER"), ("SUPPORTS", "amount"),
                                            ("CONTEXT", "repetition"), ("SUPPORTS", "CAPACITY")}
    for page, a, b, quote, body, *_ in links:
        assert re.sub(r"\s+", " ", body[a:b]).strip() == quote

    show = pipeline.timeline(db, "abc")
    order = show["events"][0]
    assert order["event_type"] == "ORDER" and order["versions"][0]["repeated"] == 1
    assert order["versions"][0]["counterparty"] == "Maharashtra State Electricity Distribution Co. Ltd"
    rep = pipeline.report(db)
    assert rep["resolutions"] == {"NEW": 2, "REPETITION": 1} and rep["filings_not_yet_scanned"] == 0
    assert rep["top_leads"][0]["symbol"] == "ABC" and rep["top_leads"][0]["priority"] == "P1"


def test_filing_without_issuer_is_data_repair_until_linked(db):
    iss, src = _seed(db)
    art = _filing(db, None, src, 9, datetime(2026, 2, 1, 12, tzinfo=IST), [PO])
    assert pipeline.scan(db)["NO_ISSUER"] == 1
    assert pipeline.report(db)["data_repair"] == 1
    db.execute("""UPDATE document_publications SET issuer_id = %s""", (iss,))
    assert pipeline.scan(db)["SCANNED"] == 1
    assert db.execute("SELECT status FROM commercial_scans WHERE text_artifact_id = %s", (art,)).fetchone() == (
        "SCANNED",)


# ---------------- pre-filters: false-positive classes seen in the January 2021 model check ----------------

@pytest.mark.parametrize("text", [
    "Commercial Operation Date (SCOD)",
    "C.O.D. Commercial Operations Date",
    "Repayment of Loans Given - - - - - -",
    "Any advance paid or received for the contract, if any: none",
    "Scrip Code: 511072 Sub: Intimation to the exchange under Regulation 30 of the Listing Regulations",
])
def test_prefilter_drops_non_disclosures(text):
    assert mentions(text) == []


@pytest.mark.parametrize("text, family", [
    ("Agra – Etawah Project achieves COD and starts toll collection at full tariffs.", "COMMERCIAL_START"),
    ("Declaration of COD of 50 MW capacity by THDC India Limited.", "COMMERCIAL_START"),
    ("Scrip Code: 532439 Olectra Greentech has received a Letter of Award for 100 electric buses from MSRTC.",
     "ORDER"),
    ("To BSE Limited. We are pleased to inform you that the Company has received an order worth Rs 45 crore "
     "from Eastern Rail Systems Limited.", "ORDER"),
])
def test_prefilter_keeps_real_events(text, family):
    assert [m.family for m in mentions(text)] == [family]


def test_old_letter_of_intent_is_dropped_only_when_filing_date_is_known():
    text = "On 30 April 2019, MSEDCL issued a letter of intent to STPL for execution of PPA of 507 MW."
    assert extract_document([(1, text)], as_of=date(2021, 1, 28))[0] == []
    assert extract_document([(1, text)], as_of=date(2019, 6, 1))[0] != []
    assert extract_document([(1, text)])[0] != []
