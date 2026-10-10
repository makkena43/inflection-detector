"""Schema checks.  The enum checks read the migration text; the rest run against a real
PostgreSQL (skipped without INFLECTION_TEST_DSN)."""

import re
from pathlib import Path

import psycopg
import pytest

from inflection import states
from inflection.text_extraction import ExtractionStatus
from inflection.units import Scale

SQL = "\n".join(p.read_text() for p in sorted((Path(__file__).parent.parent / "db" / "migrations").glob("*.sql")))


def check_values(column: str) -> list[set[str]]:
    """Value sets of every ``CHECK (<column> IN (...))`` in the migrations."""
    found = [set(re.findall(r"'([A-Z_0-9]+)'", m.group(1)))
             for m in re.finditer(rf"CHECK \({column} IN \((.*?)\)\)", SQL, re.S)]
    assert found, f"no CHECK found for {column}"
    return found


@pytest.mark.parametrize("column,enum", [
    ("workflow_state", states.WorkflowState), ("business_state", states.BusinessEvidenceState),
    ("state", states.RecommendationState), ("decision", states.InvestorDecision),
    ("relationship", states.RelationshipStatus), ("status", states.InputStatus),
    ("assertion_type", states.AssertionType), ("mode", states.RunMode),
    ("coverage_status", states.CoverageStatus), ("status", ExtractionStatus),
    ("pipeline_state", states.PipelineState), ("timestamp_basis", states.PublicationBasis),
    ("missing_reason", states.MissingReason), ("period_type", states.PeriodType),
    ("scope", states.StatementScope), ("commercial_stage", states.CommercialStage),
    ("amount_basis", states.AmountBasis), ("materiality", states.MaterialityStatus),
    ("funding", states.FundingStatus), ("priority_class", states.PriorityClass),
    ("relation", states.EvidenceRelation), ("validity_status", states.ValidityStatus),
    ("identity_status", states.IdentityStatus), ("access_mode", states.AccessMode), ("scale", Scale),
])
def test_sql_checks_match_python_enums(column, enum):
    assert {e.value for e in enum} in check_values(column)


def test_latest_workflow_check_is_complete():
    # 0002 replaces the 0001 constraint; the last definition must be the full enum
    assert check_values("workflow_state")[-1] == {e.value for e in states.WorkflowState}


H = "a" * 64


def seed_case(db):
    iss = db.execute("INSERT INTO issuers (legal_name) VALUES ('Alpha Ltd') RETURNING issuer_id").fetchone()[0]
    ev = db.execute(
        "INSERT INTO candidate_evaluations (run_id, issuer_id, as_of, mode, policy_version, route, components, "
        "outcome, reasons, policy_hash, priority_class, content_hash) VALUES (gen_random_uuid(), %s, now(), 'LIVE', "
        "'p1', 'commercial', '{}', 'ADMIT', ARRAY['binding order 30%% of TTM revenue'], %s, 'P1', %s) "
        "RETURNING evaluation_id", (iss, H, H)).fetchone()[0]
    case = db.execute("INSERT INTO research_cases (issuer_id, admitted_by, cutoff) VALUES (%s, %s, now()) "
                      "RETURNING case_id", (iss, ev)).fetchone()[0]
    return iss, ev, case


def task(db, case, **kw):
    cols = {"case_id": case, "task_type": "DEEP", "base_revision": 1, "cutoff": "2026-10-01T00:00Z", **kw}
    q = f"INSERT INTO research_tasks ({', '.join(cols)}) VALUES ({', '.join(['%s'] * len(cols))}) RETURNING task_id"
    return db.execute(q, list(cols.values())).fetchone()[0]


def version(db, case):
    t = task(db, case)
    s = db.execute("INSERT INTO research_submissions (task_id, packet_hash, base_revision, idempotency_key, "
                   "schema_version, payload, author_kind, author_identity, validation_status, content_hash) "
                   "VALUES (%s, 'h', 1, 'k1', 's1', '{}', 'ANALYST', 'me', 'VALID', %s) RETURNING submission_id",
                   (t, H)).fetchone()[0]
    return db.execute("INSERT INTO research_versions (case_id, submission_id, version_no, schema_version, payload, "
                      "source_manifest, content_hash) VALUES (%s, %s, 1, 's1', '{}', '[]', %s) "
                      "RETURNING research_version_id", (case, s, H)).fetchone()[0]


def test_append_only_tables_refuse_update_and_delete(db):
    _, ev, _ = seed_case(db)
    with pytest.raises(psycopg.errors.IntegrityConstraintViolation):
        db.execute("UPDATE candidate_evaluations SET outcome = 'REJECT' WHERE evaluation_id = %s", (ev,))
    with pytest.raises(psycopg.errors.IntegrityConstraintViolation):
        db.execute("DELETE FROM candidate_evaluations WHERE evaluation_id = %s", (ev,))


def test_one_open_case_per_issuer(db):
    iss, ev, _ = seed_case(db)
    with pytest.raises(psycopg.errors.UniqueViolation):
        db.execute("INSERT INTO research_cases (issuer_id, admitted_by, cutoff) VALUES (%s, %s, now())", (iss, ev))


def test_one_active_task_per_case_and_type(db):
    _, _, case = seed_case(db)
    task(db, case)
    with pytest.raises(psycopg.errors.UniqueViolation):
        task(db, case)


def test_claimed_task_needs_lease_token(db):
    _, _, case = seed_case(db)
    with pytest.raises(psycopg.errors.CheckViolation):
        task(db, case, status="CLAIMED", lease_owner="chat-1", lease_expires_at="2026-10-10T06:00Z")
    task(db, case, status="CLAIMED", lease_owner="chat-1", lease_expires_at="2026-10-10T06:00Z",
         lease_token="7f9e2f0e-7d0c-4c43-9a3a-3c1d0f3c8b11")


def test_unknown_workflow_state_rejected_and_stale_accepted(db):
    iss, _, _ = seed_case(db)
    db.execute("UPDATE research_cases SET workflow_state = 'STALE_UNRESEARCHED' WHERE issuer_id = %s", (iss,))
    with pytest.raises(psycopg.errors.CheckViolation):
        db.execute("UPDATE research_cases SET workflow_state = 'BUY' WHERE issuer_id = %s", (iss,))


def test_consider_recommendation_needs_band_policy_and_scenarios(db):
    _, _, case = seed_case(db)
    rv = version(db, case)
    with pytest.raises(psycopg.errors.CheckViolation):
        db.execute("INSERT INTO recommendations (case_id, research_version_id, state, price_date, valid_until, "
                   "content_hash) VALUES (%s, %s, 'CONSIDER_WITHIN_PRICE_BAND', current_date, "
                   "now() + interval '30 days', %s)", (case, rv, H))
    db.execute("INSERT INTO recommendations (case_id, research_version_id, state, price_date, valid_until, "
               "content_hash) VALUES (%s, %s, 'WATCH_MILESTONE', current_date, now() + interval '30 days', %s)",
               (case, rv, H))


def test_observed_scenario_input_needs_evidence_and_money_needs_currency(db):
    base = ("INSERT INTO scenario_inputs (research_version_id, stream, period, scenario, name, value, value_kind, "
            "currency, scale, status, evidence_ids) VALUES (gen_random_uuid(), 's', 'FY28', 'BASE', 'x', 1, %s, %s, "
            "%s, %s, %s)")
    with pytest.raises(psycopg.errors.CheckViolation):
        db.execute(base, ("MONEY", "INR", "CRORE", "OBSERVED", []))
    with pytest.raises(psycopg.errors.CheckViolation):
        db.execute(base, ("MONEY", None, "CRORE", "ANALYST_ASSUMPTION", []))


def test_regression_6_fact_needs_period_type_and_null_needs_reason(db):
    iss, _, _ = seed_case(db)
    q = ("INSERT INTO financial_facts (issuer_id, metric, period_end, scope, value, value_kind, currency, scale, "
         "period_type, provider, provider_version, missing_reason, content_hash) VALUES "
         "(%s, 'revenue', '2026-06-30', 'CONSOLIDATED', %s, 'MONEY', 'INR', 'CRORE', %s, 'x', '1', %s, %s)")
    db.execute(q, (iss, 100, "QUARTER", None, H))
    with pytest.raises(psycopg.errors.NotNullViolation):
        db.execute(q, (iss, 100, None, None, H))
    with pytest.raises(psycopg.errors.CheckViolation):
        db.execute(q, (iss, None, "QUARTER", None, H))           # null without a reason
    with pytest.raises(psycopg.errors.CheckViolation):
        db.execute(q, (iss, 0, "QUARTER", "NOT_DISCLOSED", H))   # a reason but a value too
    db.execute(q, (iss, None, "QUARTER", "NOT_DISCLOSED", H))


def test_identifier_overlap_conflict_rejected(db):
    iss = db.execute("INSERT INTO issuers (legal_name) VALUES ('A') RETURNING issuer_id").fetchone()[0]
    s1, s2 = (db.execute("INSERT INTO securities (issuer_id, isin) VALUES (%s, %s) RETURNING security_id",
                         (iss, isin)).fetchone()[0] for isin in ("INE000A01011", "INE000B01019"))
    q = ("INSERT INTO identifier_history (security_id, exchange, kind, value, valid_from, valid_to, source) "
         "VALUES (%s, 'NSE', 'SYMBOL', 'ALPHA', %s, %s, 'test')")
    db.execute(q, (s1, "2010-01-01", "2020-06-30"))
    db.execute(q, (s2, "2020-07-01", None))                          # reuse after a gap is fine
    db.execute(q, (s1, "2015-01-01", "2016-01-01"))                  # same security overlapping is fine
    with pytest.raises(psycopg.errors.ExclusionViolation):
        db.execute(q, (s2, "2019-01-01", None))


def test_publication_states(db):
    src = db.execute("INSERT INTO sources (name, kind, access_policy) VALUES ('nse', 'announcements', 'x') "
                     "RETURNING source_id").fetchone()[0]
    q = ("INSERT INTO document_publications (source_id, external_id, source_url, publication_basis, published_at, "
         "pipeline_state, failure_reason) VALUES (%s, %s, 'u', 'EXCHANGE_TIMESTAMP', now(), %s, %s)")
    db.execute(q, (src, "a", "DISCOVERED", None))                    # no bytes yet
    with pytest.raises(psycopg.errors.CheckViolation):
        db.execute(q, (src, "b", "TEXT_READY", None))                # text without bytes
    with pytest.raises(psycopg.errors.CheckViolation):
        db.execute(q, (src, "c", "FAILED", None))                    # failure needs a reason
    db.execute(q, (src, "d", "FAILED", "HTTP 403"))


def test_blocked_source_cannot_be_enabled(db):
    with pytest.raises(psycopg.errors.CheckViolation):
        db.execute("INSERT INTO sources (name, kind, access_policy, enabled) VALUES ('bse', 'a', 'x', true)")


def test_regression_3_unquantified_amount_basis(db):
    iss = db.execute("INSERT INTO issuers (legal_name) VALUES ('A') RETURNING issuer_id").fetchone()[0]
    ev = db.execute("INSERT INTO events (issuer_id) VALUES (%s) RETURNING event_id", (iss,)).fetchone()[0]
    q = ("INSERT INTO event_versions (event_id, version_no, commercial_stage, event_type, observation_status, "
         "amount_basis, magnitude, magnitude_currency, magnitude_scale, magnitude_missing_reason, novelty, "
         "content_hash) VALUES (%s, %s, 'BINDING_DEMAND', 'ORDER', 'OBSERVED', %s, %s, %s, %s, %s, 'NEW', %s)")
    db.execute(q, (ev, 1, "CEILING", 50, "INR", "CRORE", None, H))           # "up to 50 cr" stays a ceiling
    with pytest.raises(psycopg.errors.CheckViolation):
        db.execute(q, (ev, 2, "FIRM", None, None, None, "NOT_DISCLOSED", H))  # no amount cannot be FIRM
    with pytest.raises(psycopg.errors.CheckViolation):
        db.execute(q, (ev, 3, "FIRM", 50, None, None, None, H))               # amount without currency
    db.execute(q, (ev, 4, "UNQUANTIFIED", None, None, None, "NOT_DISCLOSED", H))


def test_idempotency_key_unique_per_tenant_operation(db):
    q = "INSERT INTO idempotency_keys (tenant, operation, idempotency_key, request_sha256) VALUES (%s, %s, 'k', %s)"
    db.execute(q, ("t", "submit", H))
    db.execute(q, ("t", "claim", H))
    with pytest.raises(psycopg.errors.UniqueViolation):
        db.execute(q, ("t", "submit", H))


def test_page_full_text_search(db):
    doc = db.execute("INSERT INTO documents DEFAULT VALUES RETURNING document_id").fetchone()[0]
    dv = db.execute("INSERT INTO document_versions (document_id, sha256, storage_key, byte_size, media_type) "
                    "VALUES (%s, %s, 'k', 10, 'application/pdf') RETURNING document_version_id",
                    (doc, H)).fetchone()[0]
    ta = db.execute("INSERT INTO text_artifacts (document_version_id, extraction_method, extraction_version, "
                    "status) VALUES (%s, 'pdfplumber', 'v1', 'COMPLETE') RETURNING text_artifact_id",
                    (dv,)).fetchone()[0]
    db.execute("INSERT INTO text_pages VALUES (%s, 1, 'cover'), (%s, 2, 'received a purchase order for turbines')",
               (ta, ta))
    hits = db.execute("SELECT page_no FROM text_pages WHERE tsv @@ plainto_tsquery('english', 'turbine orders')"
                      ).fetchall()
    assert hits == [(2,)]
