"""Schema checks against a real PostgreSQL (skipped without INFLECTION_TEST_DSN)."""

import re
from pathlib import Path

import psycopg
import pytest

from inflection import states
from inflection.text_extraction import ExtractionStatus

SQL = (Path(__file__).parent.parent / "db" / "migrations" / "0001_init.sql").read_text()


def check_values(column: str) -> list[set[str]]:
    """Value sets of every ``CHECK (<column> IN (...))`` in the migration."""
    found = [set(re.findall(r"'([A-Z_]+)'", m.group(1)))
             for m in re.finditer(rf"CHECK \({column} IN \((.*?)\)\)", SQL, re.S)]
    assert found, f"no CHECK found for {column}"
    return found


@pytest.mark.parametrize("column,enum", [
    ("workflow_state", states.WorkflowState), ("business_state", states.BusinessEvidenceState),
    ("state", states.RecommendationState), ("decision", states.InvestorDecision),
    ("relationship", states.RelationshipStatus), ("status", states.InputStatus),
    ("assertion_type", states.AssertionType), ("mode", states.RunMode),
    ("coverage_status", states.CoverageStatus), ("status", ExtractionStatus),
])
def test_sql_checks_match_python_enums(column, enum):
    assert {e.value for e in enum} in check_values(column)


def seed_case(db):
    iss = db.execute("INSERT INTO issuers (legal_name) VALUES ('Alpha Ltd') RETURNING issuer_id").fetchone()[0]
    ev = db.execute(
        "INSERT INTO candidate_evaluations (run_id, issuer_id, as_of, mode, policy_version, route, components, "
        "outcome, reasons) VALUES (gen_random_uuid(), %s, now(), 'LIVE', 'p1', 'order', '{}', 'ADMIT', "
        "ARRAY['binding order 30%% of TTM revenue']) RETURNING evaluation_id", (iss,)).fetchone()[0]
    case = db.execute("INSERT INTO research_cases (issuer_id, admitted_by, cutoff) VALUES (%s, %s, now()) "
                      "RETURNING case_id", (iss, ev)).fetchone()[0]
    return iss, ev, case


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
    db.execute("INSERT INTO research_tasks (case_id, task_type, base_revision) VALUES (%s, 'DEEP', 1)", (case,))
    with pytest.raises(psycopg.errors.UniqueViolation):
        db.execute("INSERT INTO research_tasks (case_id, task_type, base_revision) VALUES (%s, 'DEEP', 1)", (case,))


def test_claimed_task_needs_lease(db):
    _, _, case = seed_case(db)
    with pytest.raises(psycopg.errors.CheckViolation):
        db.execute("INSERT INTO research_tasks (case_id, task_type, base_revision, status) "
                   "VALUES (%s, 'DEEP', 1, 'CLAIMED')", (case,))


def test_unknown_workflow_state_rejected(db):
    iss, ev, _ = seed_case(db)
    with pytest.raises(psycopg.errors.CheckViolation):
        db.execute("UPDATE research_cases SET workflow_state = 'BUY' WHERE issuer_id = %s", (iss,))


def test_consider_recommendation_needs_band_and_policy(db):
    _, _, case = seed_case(db)
    t = db.execute("INSERT INTO research_tasks (case_id, task_type, base_revision) VALUES (%s, 'DEEP', 1) "
                   "RETURNING task_id", (case,)).fetchone()[0]
    s = db.execute("INSERT INTO research_submissions (task_id, packet_hash, expected_revision, idempotency_key, "
                   "schema_version, payload, author_kind, author_identity, validation_status) "
                   "VALUES (%s, 'h', 1, 'k1', 's1', '{}', 'ANALYST', 'me', 'VALID') RETURNING submission_id",
                   (t,)).fetchone()[0]
    rv = db.execute("INSERT INTO research_versions (case_id, submission_id, version_no, schema_version, payload, "
                    "source_manifest) VALUES (%s, %s, 1, 's1', '{}', '[]') RETURNING research_version_id",
                    (case, s)).fetchone()[0]
    with pytest.raises(psycopg.errors.CheckViolation):
        db.execute("INSERT INTO recommendations (case_id, research_version_id, state, price_date, expires_at) "
                   "VALUES (%s, %s, 'CONSIDER_WITHIN_PRICE_BAND', current_date, now() + interval '30 days')",
                   (case, rv))
    db.execute("INSERT INTO recommendations (case_id, research_version_id, state, price_date, expires_at) "
               "VALUES (%s, %s, 'WATCH_MILESTONE', current_date, now() + interval '30 days')", (case, rv))


def test_observed_scenario_input_needs_evidence(db):
    _, _, case = seed_case(db)
    with pytest.raises(psycopg.errors.CheckViolation):
        db.execute("INSERT INTO scenario_inputs (research_version_id, stream, period, scenario, name, value, "
                   "unit, status) VALUES (gen_random_uuid(), 's', 'FY28', 'BASE', 'volume', 1, 'MW', 'OBSERVED')")


def test_publication_timestamp_basis_consistent(db):
    with pytest.raises(psycopg.errors.CheckViolation):
        db.execute("INSERT INTO document_publications (document_version_id, source_id, external_id, source_url, "
                   "timestamp_basis) VALUES (gen_random_uuid(), gen_random_uuid(), 'x', 'u', 'EXCHANGE_TIMESTAMP')")


def test_page_full_text_search(db):
    doc = db.execute("INSERT INTO documents DEFAULT VALUES RETURNING document_id").fetchone()[0]
    dv = db.execute("INSERT INTO document_versions (document_id, sha256, storage_key, byte_size, media_type) "
                    "VALUES (%s, repeat('a', 64), 'k', 10, 'application/pdf') RETURNING document_version_id",
                    (doc,)).fetchone()[0]
    ta = db.execute("INSERT INTO text_artifacts (document_version_id, extraction_method, extraction_version, "
                    "status) VALUES (%s, 'pdfplumber', 'v1', 'COMPLETE') RETURNING text_artifact_id",
                    (dv,)).fetchone()[0]
    db.execute("INSERT INTO text_pages VALUES (%s, 1, 'cover'), (%s, 2, 'received a purchase order for turbines')",
               (ta, ta))
    hits = db.execute("SELECT page_no FROM text_pages WHERE tsv @@ plainto_tsquery('english', 'turbine orders')"
                      ).fetchall()
    assert hits == [(2,)]
