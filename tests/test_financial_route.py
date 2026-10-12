"""The financial route: spec 18.1 checks on year-earlier comparables, priority classes shared with the
commercial route, and the database steps, including a real XBRL sample filing (Rain Q4 CY21) against a
year-earlier filing built from it."""

from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest

from inflection import financials, queue
from inflection.commercial import vocabulary as CV
from inflection.financial import pipeline
from inflection.financial import rules as R
from inflection.sources.common import IST
from inflection.sources.download import Archive
from test_financials import FACTS, _company, entry, filing
from test_sources import client

CR = Decimal(10) ** 7


def period(end=date(2025, 9, 30), segments=None, unverified=(), **crore):
    p = R.Period(end, {k: Decimal(str(v)) * CR for k, v in crore.items()},
                 {k: (Decimal(str(v)) * CR if v is not None else None) for k, v in (segments or {}).items()})
    for m in unverified:
        p.values[m] = None
    return p


# revenue 1,000; expenses 900 incl. finance 20 and depreciation 30 -> operating profit 150 (15%)
BASE = dict(revenue=1000, total_expenses=900, finance_cost=20, depreciation=30)


def check(name, cur, prior):
    return next(c for c in R.run_checks(cur, prior) if c.name == name)


# ---------------- checks ----------------

def test_operating_margin_up_200_bps_fires_and_150_does_not():
    prior = period(**BASE)
    up = period(**{**BASE, "revenue": 1100, "total_expenses": 975})          # 175 / 1100 = 15.9%: +91 bps
    assert check("MARGIN_EXPANSION", up, prior).status == "NOT_FIRED"
    up = period(**{**BASE, "revenue": 1000, "total_expenses": 880})          # 170 / 1000 = 17%: +200 bps
    c = check("MARGIN_EXPANSION", up, prior)
    assert c.status == "FIRED" and c.values["bps"] == 200 and "operating margin up 200 bps" in c.detail


def test_gross_margin_only_for_companies_that_report_materials():
    prior = period(**BASE, cost_of_materials=600)
    cur = period(**{**BASE, "total_expenses": 890}, cost_of_materials=550)   # gross 40% -> 45%
    c = check("MARGIN_EXPANSION", cur, prior)
    assert c.status == "FIRED" and c.detail.startswith("gross margin up 500 bps")
    assert "gross_margin" not in check("MARGIN_EXPANSION", period(**BASE), period(**BASE)).values


def test_operating_profit_growth_needs_a_positive_comparable_base():
    c = check("OPERATING_PROFIT_GROWTH", period(**{**BASE, "total_expenses": 862.5}), period(**BASE))
    assert c.status == "FIRED" and c.values["growth"] == "25.0%"
    c = check("OPERATING_PROFIT_GROWTH", period(**BASE), period(**{**BASE, "total_expenses": 1060}))
    assert c.status == "NOT_MEASURABLE" and c.values["turned_positive"]
    tiny = period(**{**BASE, "total_expenses": 1040})                        # base 10 = 1% of revenue
    assert check("OPERATING_PROFIT_GROWTH", period(**BASE), tiny).status == "NOT_MEASURABLE"


def test_segment_loss_must_shrink_30_percent_and_be_large_enough():
    prior = period(**BASE, segments={"Solar EPC": -40, "Cables": 100})
    c = check("SEGMENT_LOSS_REDUCTION", period(**BASE, segments={"solar  epc": -26, "Cables": 90}), prior)
    assert c.status == "FIRED" and "Solar EPC segment loss shrank 35.0%" in c.detail
    assert check("SEGMENT_LOSS_REDUCTION", period(**BASE, segments={"Solar EPC": 5}), prior).detail.startswith(
        "Solar EPC segment loss turned to profit")
    assert check("SEGMENT_LOSS_REDUCTION", period(**BASE, segments={"Solar EPC": -30}), prior).status == "NOT_FIRED"
    small = period(**BASE, segments={"Other": -5})                          # 0.5% of revenue: near-zero base
    assert check("SEGMENT_LOSS_REDUCTION", period(**BASE, segments={"Other": 0}), small).status == "NOT_MEASURABLE"


def test_finance_cost_drop_and_its_floor():
    c = check("FINANCE_COST_DROP", period(**{**BASE, "finance_cost": 16}), period(**BASE))
    assert c.status == "FIRED" and "source of debt reduction to investigate" in c.detail
    assert check("FINANCE_COST_DROP", period(**{**BASE, "finance_cost": 1}),
                 period(**{**BASE, "finance_cost": 4})).status == "NOT_MEASURABLE"    # 0.4% of revenue


def test_unverified_inputs_are_not_compared_and_working_capital_is_not_covered():
    checks = R.run_checks(period(**BASE, unverified=("total_expenses",)), period(**BASE))
    st = {c.name: c.status for c in checks}
    assert st["OPERATING_PROFIT_GROWTH"] == "UNVERIFIED" and st["MARGIN_EXPANSION"] == "UNVERIFIED"
    assert st["WORKING_CAPITAL_DAYS"] == "NOT_MEASURABLE"
    ev = R.classify(checks, [], False, False, "i", datetime(2025, 11, 1, tzinfo=IST), [])
    assert ev["priority_class"] == "D" and ev["outcome"] == "DEFER" and ev["reasons"][0].startswith("data repair")


def test_cautions_for_a_revenue_jump_and_exceptional_items():
    notes = R.cautions(period(**{**BASE, "revenue": 1600}, exceptional_items=-100), period(**BASE))
    assert notes[0].startswith("revenue up 60.0%: check for an acquisition") and "exceptional items" in notes[1]


def test_comparable_window_handles_leap_day():
    assert R.comparable_window(date(2024, 2, 29)) == (date(2023, 2, 21), date(2023, 3, 7))


# ---------------- priority ----------------

AT = datetime(2025, 11, 10, 18, 0, tzinfo=IST)


def mech(event_type, stage="BINDING_DEMAND", obs="OBSERVED", **details):
    from inflection.commercial.vocabulary import STAGE_RANK
    return R.Mechanism("e", f"v-{event_type}-{stage}", event_type, stage, STAGE_RANK.get(stage, 0), obs,
                       AT - timedelta(days=90), details)


def fired(*names):
    kinds = {"FINANCE_COST_DROP": "DEBT"}
    return [R.Check(n, "FIRED", n.lower(), Decimal(2), mechanism_kind=kinds.get(n, "OPERATING")) for n in names]


@pytest.mark.parametrize("checks,mechs,active,equity,cls,alloc", [
    (fired("OPERATING_PROFIT_GROWTH"), [mech("ORDER")], False, False, "P2", "RANKED"),
    (fired("OPERATING_PROFIT_GROWTH"), [], False, False, "P3", "NONE"),
    (fired("OPERATING_PROFIT_GROWTH", "MARGIN_EXPANSION"), [], False, False, "P3", "EXPLORATION"),
    (fired("OPERATING_PROFIT_GROWTH"), [mech("ORDER", "AMBITION")], False, False, "P3", "NONE"),
    (fired("OPERATING_PROFIT_GROWTH"), [mech("ORDER", obs="FORECAST")], False, False, "P3", "NONE"),
    (fired("OPERATING_PROFIT_GROWTH"), [mech("CAPACITY", "FUNDED_PLAN")], False, False, "P3", "NONE"),
    (fired("OPERATING_PROFIT_GROWTH"), [mech("CAPACITY", "FUNDED_PLAN", commissioned=True)], False, False, "P2",
     "RANKED"),
    (fired("FINANCE_COST_DROP"), [mech("ORDER")], False, False, "P3", "NONE"),       # orders don't explain interest
    (fired("FINANCE_COST_DROP"), [mech("DEBT_REDUCTION", "UNKNOWN")], False, False, "P2", "RANKED"),
    (fired("FINANCE_COST_DROP"), [mech("DEBT_REDUCTION", "UNKNOWN")], False, True, "P3", "NONE"),
    (fired("FINANCE_COST_DROP"), [mech("DEBT_REDUCTION", "UNKNOWN", funded_by_equity=True)], False, False, "P3",
     "NONE"),
    (fired("MARGIN_EXPANSION"), [], True, False, "U0", "UPDATE"),
])
def test_priority_classes(checks, mechs, active, equity, cls, alloc):
    ev = R.classify(checks, mechs, active, equity, "i", AT, [])
    assert (ev["priority_class"], ev["queue_allocation"]) == (cls, alloc)
    assert ev["outcome"] == ("ADMIT" if cls in ("U0", "P2") else "DEFER")
    assert bool(ev["without_mechanism"]) == (cls in ("P3",) or (cls == "U0" and not mechs))


def test_nothing_fired_is_no_evaluation_and_reasons_name_the_mechanism():
    assert R.classify([R.Check("X", "NOT_FIRED", "")], [], False, False, "i", AT, []) is None
    ev = R.classify(fired("OPERATING_PROFIT_GROWTH"), [mech("ORDER")], False, False, "i", AT, ["caution"])
    assert "possible mechanism: order (binding demand, public 2025-08-12)" in ev["reasons"][0]
    assert ev["reasons"][-1] == "caution" and ev["ranking"][:4] == [2, 1, -1, -3]


def test_policy_hash_is_stable():
    assert R.policy_hash() == R.policy_hash() and len(R.policy_hash()) == 64


# ---------------- database ----------------

def _seed(db):
    iss = db.execute("INSERT INTO issuers (legal_name) VALUES ('ABC Limited') RETURNING issuer_id").fetchone()[0]
    sec = db.execute("INSERT INTO securities (issuer_id, isin) VALUES (%s, 'INE111A01011') RETURNING security_id",
                     (iss,)).fetchone()[0]
    db.execute("""INSERT INTO identifier_history (security_id, exchange, kind, value, valid_from, source)
                  VALUES (%s, 'NSE', 'SYMBOL', 'ABC', '2010-01-01', 'test')""", (sec,))
    return iss, financials.ensure_source(db)


def _results(db, iss, src, n, end, at, scope="CONSOLIDATED", segments=None, unverified=(), **crore):
    doc = db.execute("INSERT INTO documents (issuer_id) VALUES (%s) RETURNING document_id", (iss,)).fetchone()[0]
    ver = db.execute("""INSERT INTO document_versions (document_id, sha256, storage_key, byte_size, media_type)
                        VALUES (%s, %s, 'k', 1, 'application/xml') RETURNING document_version_id""",
                     (doc, f"{n:064x}")).fetchone()[0]
    pid = db.execute("""INSERT INTO document_publications (document_version_id, source_id, external_id, source_url,
                                                           published_at, publication_basis, issuer_id, pipeline_state,
                                                           period_end)
                        VALUES (%s, %s, %s, 'https://x', %s, 'EXCHANGE_TIMESTAMP', %s, 'TEXT_READY', %s)
                        RETURNING publication_id""", (ver, src, f"INDAS_{n}", at, iss, end)).fetchone()[0]
    rows = [(m, None, Decimal(str(v)) * CR) for m, v in crore.items()]
    rows += [("segment_result", s, Decimal(str(v)) * CR) for s, v in (segments or {}).items()]
    for metric, segment, value in rows:
        bad = metric in unverified
        db.execute("""INSERT INTO financial_facts (issuer_id, metric, period_start, period_end, scope, segment, value,
                                                   value_kind, currency, scale, original_text, missing_reason,
                                                   period_type, available_at, provider, provider_version,
                                                   publication_id, content_hash)
                      VALUES (%s, %s, %s, %s, %s, %s, %s, 'MONEY', 'INR', 'UNITS', %s, %s, 'QUARTER', %s, 'nse_xbrl',
                              'test', %s, md5(%s))""",
                   (iss, metric, end - timedelta(days=91), end, scope, segment, None if bad else value, str(value),
                    "UNVERIFIED" if bad else None, at, pid, f"{pid}{metric}{segment}"))
    return pid


def _event(db, iss, event_type, stage, at):
    eid = db.execute("""INSERT INTO events (issuer_id, event_type, first_public_at, rules_version, created_by)
                        VALUES (%s, %s, %s, %s, 'test') RETURNING event_id""",
                     (iss, event_type, at, CV.RULES_VERSION)).fetchone()[0]
    return db.execute("""INSERT INTO event_versions (event_id, version_no, commercial_stage, event_type,
                                                     observation_status, content_hash, published_at, details,
                                                     magnitude_missing_reason)
                         VALUES (%s, 1, %s, %s, 'OBSERVED', md5(%s::text), %s, '{}', 'NOT_DISCLOSED') RETURNING event_version_id""",
                      (eid, stage, event_type, eid, at)).fetchone()[0]


def test_pipeline_end_to_end(db):
    iss, src = _seed(db)
    t = lambda d: datetime.fromisoformat(d + "T18:30:00+05:30")             # noqa: E731
    _results(db, iss, src, 1, date(2024, 6, 30), t("2024-08-10"), **BASE)
    _results(db, iss, src, 2, date(2024, 9, 30), t("2024-11-08"), segments={"Solar": -40}, **BASE)
    _results(db, iss, src, 3, date(2025, 6, 30), t("2025-08-09"), **{**BASE, "total_expenses": 850})
    _results(db, iss, src, 4, date(2025, 6, 30), t("2025-08-09"), scope="STANDALONE", **BASE)
    _results(db, iss, src, 5, date(2025, 9, 30), t("2025-11-07"), segments={"Solar": -20},
             **{**BASE, "total_expenses": 920})
    _results(db, iss, src, 6, date(2025, 12, 31), t("2026-02-10"), unverified=("revenue",), **BASE)
    order = _event(db, iss, "ORDER", "BINDING_DEMAND", t("2025-09-15"))       # between Q1 and Q2
    _event(db, iss, "ORDER", "BINDING_DEMAND", t("2025-12-01"))              # after both results: never visible

    out = pipeline.scan(db, now=t("2026-02-11"))
    assert (out["EVALUATED"], out["NO_COMPARABLE"], out["SKIPPED_STANDALONE"], out["NOT_NOMINATED"]) == (2, 3, 1, 0)
    assert pipeline.scan(db) == {}                                           # nothing is read twice
    ev = db.execute("""SELECT priority_class, outcome, queue_allocation, trigger_event_version_ids,
                              components->'fired', components->'without_mechanism', mode, reasons[1]
                         FROM candidate_evaluations ORDER BY as_of""").fetchall()
    # Q1: operating profit 150 -> 200 and margin 15% -> 20%, but no commercial event public yet
    both = ["MARGIN_EXPANSION", "OPERATING_PROFIT_GROWTH"]
    assert ev[0][:6] == ("P3", "DEFER", "EXPLORATION", [], both, both)
    assert ev[0][7] == "operating margin up 500 bps year on year (15.0% to 20.0%); no mechanism identified"
    # Q2: the Solar segment loss halved, and the September order is public by then
    assert ev[1][:6] == ("P2", "ADMIT", "RANKED", [order], ["SEGMENT_LOSS_REDUCTION"], [])
    assert ev[1][6] == "PUBLIC_INFORMATION_RECONSTRUCTION"
    assert ev[1][7] == ("Solar segment loss shrank 50.0% (₹-40.00 cr to ₹-20.00 cr); possible mechanism: "
                        "order (binding demand, public 2025-09-15)")
    status = dict(db.execute("SELECT period_end::text, status FROM financial_scans WHERE scope = 'CONSOLIDATED'"))
    assert status["2025-12-31"] == "NO_COMPARABLE"                          # Q3 FY25 never filed

    rep = pipeline.report(db)
    assert rep["nominations_without_mechanism"] == {"MARGIN_EXPANSION": 1, "OPERATING_PROFIT_GROWTH": 1}
    assert rep["filings_not_yet_read"] == 0 and rep["top_leads"][0]["priority"] == "P2"
    assert {"check": "WORKING_CAPITAL_DAYS", "status": "NOT_MEASURABLE", "filings": 2} in rep["checks"]
    show = pipeline.history(db, "abc")
    statuses = [f["status"] for f in show["filings"]]
    assert statuses[-2:] == ["EVALUATED", "NO_COMPARABLE"] and statuses.count("SKIPPED_STANDALONE") == 1

    # one line per company across routes; the commercial timeline lists both routes' evaluations
    from inflection.commercial.pipeline import timeline
    assert {e["route"] for e in timeline(db, "ABC")["evaluations"]} == {"FINANCIAL"}
    q = queue.companies(db)
    assert len(q) == 1 and q[0]["priority"] == "P2" and q[0]["routes"] == ["FINANCIAL"]


def test_queue_raises_an_unexplained_financial_nomination_when_a_commercial_event_follows(db):
    iss, src = _seed(db)
    t = lambda d: datetime.fromisoformat(d + "T18:30:00+05:30")             # noqa: E731
    _results(db, iss, src, 1, date(2024, 9, 30), t("2024-11-08"), **BASE)
    _results(db, iss, src, 2, date(2025, 9, 30), t("2025-11-07"), **{**BASE, "total_expenses": 860})
    pipeline.scan(db)
    assert db.execute("SELECT priority_class FROM candidate_evaluations").fetchone() == ("P3",)
    db.execute("""INSERT INTO candidate_evaluations (run_id, issuer_id, as_of, mode, policy_version, route,
                                                     components, outcome, reasons, policy_hash, priority_class,
                                                     content_hash)
                  VALUES (gen_random_uuid(), %s, %s, 'LIVE', 'commercial-1', 'COMMERCIAL', %s, 'DEFER',
                          '{"order: binding demand; materiality unknown"}', 'h', 'P3', 'c')""",
               (iss, t("2025-12-01"), '{"events": [{"event_type": "ORDER", "stage": "BINDING_DEMAND", '
                                      '"observation": "OBSERVED"}]}'))
    q = queue.companies(db)[0]
    assert q["priority"] == "P2" and q["corroborated"] and q["routes"] == ["COMMERCIAL", "FINANCIAL"]
    assert q["reason"].startswith("operating margin up 400 bps") and "commercial event in the same window" in q["reason"]


def test_real_xbrl_filing_against_the_year_before(db, tmp_path):
    """Rain's Q4 CY21 consolidated filing, and a CY20 filing built from it at three quarters of every
    figure: operating profit up a third, margins unchanged.  The owners' share fails the arithmetic in
    both, but no check uses it."""
    _company(db)
    prior = filing([(tag, q * 3 // 4, fy * 3 // 4) for tag, q, fy in FACTS]).replace(b"2021-", b"2020-")
    listing = {"period=Quarterly": [(200, [entry(1), entry(2, to="31-Dec-2020", dis="20-Feb-2021 19:00:00")])],
               "period=Half-Yearly": [(200, [])], "period=Annual": [(200, [])], "nseindia.com": [(200, b"")]}
    c, _ = client(listing)
    financials.list_results(db, c, date(2020, 1, 1), date(2024, 11, 30))
    dl, _ = client({"INDAS_1.xml": [(200, filing())], "INDAS_2.xml": [(200, prior)]})
    assert financials.load_pending(db, Archive(tmp_path / "a"), dl)["LOADED"] == 2

    out = pipeline.scan(db)
    assert (out["NO_COMPARABLE"], out["EVALUATED"]) == (1, 1)
    assert out["OPERATING_PROFIT_GROWTH:FIRED"] == 1 and out["MARGIN_EXPANSION:NOT_FIRED"] == 1
    cls, reasons, comp = db.execute("SELECT priority_class, reasons, components FROM candidate_evaluations").fetchone()
    assert cls == "P3" and reasons[0].startswith("operating profit up 33.3% year on year (₹366.34 cr to ₹488.46 cr)")
    assert comp["filing"]["comparable_period_end"] == "2020-12-31"
    assert datetime.fromisoformat(comp["filing"]["available_at"]) == datetime(2022, 2, 25, 20, 56, 4, tzinfo=IST)


def test_a_filing_read_before_its_year_earlier_figures_is_read_again_when_they_arrive(db):
    iss, src = _seed(db)
    t = lambda d: datetime.fromisoformat(d + "T18:30:00+05:30")             # noqa: E731
    _results(db, iss, src, 3, date(2025, 6, 30), t("2025-08-09"), **{**BASE, "total_expenses": 850})
    assert pipeline.scan(db, now=t("2026-02-11"))["NO_COMPARABLE"] == 1
    assert pipeline.scan(db) == {}                                           # nothing new: not read again
    _results(db, iss, src, 1, date(2024, 6, 30), t("2024-08-10"), **BASE)   # backfilled later
    out = pipeline.scan(db, now=t("2026-02-11"))
    assert out["EVALUATED"] == 1 and out["NO_COMPARABLE"] == 1               # Q1 FY26 now compared; FY25 has none
    assert pipeline.scan(db) == {}


def test_mechanisms_come_from_the_current_commercial_rules_only(db):
    iss, src = _seed(db)
    t = lambda d: datetime.fromisoformat(d + "T18:30:00+05:30")             # noqa: E731
    _event(db, iss, "ORDER", "BINDING_DEMAND", t("2025-09-15"))
    old = _event(db, iss, "ORDER", "BINDING_DEMAND", t("2025-09-16"))
    db.execute("UPDATE events SET rules_version = 'commercial-old' WHERE event_id = "
               "(SELECT event_id FROM event_versions WHERE event_version_id = %s)", (old,))
    assert len(pipeline._mechanisms(db, iss, t("2025-11-01"))) == 1
