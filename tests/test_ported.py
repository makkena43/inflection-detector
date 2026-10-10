"""Tests for code ported from MakroGraph (b31bdd0).  Cases marked "ported" are
adapted from MakroGraph's tests/earnings_inflection/test_units.py and
test_wp1_text_artifacts.py; the rest cover behaviour changed in the port."""

from datetime import date, datetime, timezone

import pytest

from inflection.counterparty import RelationshipEvidence, assess_relationship, same_counterparty
from inflection.documents import IST, DocumentKind, availability, classify_document, content_hash
from inflection.identity import Alias, IdentityError, IssuerRegistry, is_operating_equity_series
from inflection.states import RelationshipStatus as R, RunMode
from inflection.text_extraction import ExtractionStatus, classify_pages, extract_pdf
from pdf_fixtures import make_pdf

RESULTS_PAGE = "\n".join([
    "Statement of Unaudited Standalone Financial Results for the quarter ended 30 June 2024",
    "(Rs. in crore)",
    "Particulars Quarter ended Year ended",
    "1. Revenue from operations 270.00 260.00 230.00 950.00",
])


# ---------------- documents ----------------

def test_invitation_is_not_transcript_even_with_transcript_title():  # ported
    kind, basis = classify_document(
        "XYZ Ltd invites you to its Q4 FY24 earnings conference call. Universal access number: +91 22 000.",
        title="Earnings call transcript")
    assert kind == DocumentKind.EARNINGS_CALL_INVITATION and basis.startswith("content")


def test_transcript_needs_dialogue():  # ported
    t = "\n".join(["Moderator: Ladies and gentlemen, welcome.", "Asha Iyer: Thanks.",
                   "Moderator: The first question is from Dev.", "Dev Shah: Margins?", "Asha Iyer: Stable.",
                   "Moderator: over to you."])
    assert classify_document(t)[0] == DocumentKind.EARNINGS_CALL_TRANSCRIPT


def test_title_only_classification_is_labelled():  # ported
    assert classify_document("", title="Annual Report 2023-24") == (DocumentKind.ANNUAL_REPORT, "title_only")


def test_results_statement_with_table():
    assert classify_document(RESULTS_PAGE)[0] == DocumentKind.FINANCIAL_RESULTS


def test_date_only_is_end_of_day_and_not_tradable_same_day():
    a = availability(None, date(2024, 8, 12))
    assert a.available_at == datetime(2024, 8, 12, 23, 59, 59, tzinfo=IST)
    assert a.basis == "DATE_ONLY" and a.earliest_trade_date == date(2024, 8, 13)
    assert availability(None, None).available_at is None


def test_timestamp_before_open_is_tradable_same_day_after_open_next_day():
    pre = availability(datetime(2024, 8, 12, 8, 0, tzinfo=IST), None)
    post = availability(datetime(2024, 8, 12, 15, 0, tzinfo=IST), None)
    assert pre.earliest_trade_date == date(2024, 8, 12)
    assert post.earliest_trade_date == date(2024, 8, 13)


def test_naive_timestamp_refused():
    with pytest.raises(ValueError):
        availability(datetime(2024, 8, 12, 8, 0), None)


def test_content_hash_ignores_whitespace_and_case():
    assert content_hash("Revenue  100\n") == content_hash("revenue 100")


# ---------------- identity ----------------

def reg():
    return IssuerRegistry([
        Alias("OLDCO", "NSE", "INE000A01011", "iss-1", date(2010, 1, 1), date(2020, 6, 30), "EQ",
              datetime(2010, 1, 2, tzinfo=timezone.utc)),
        Alias("NEWCO", "NSE", "INE000A01011", "iss-1", date(2020, 7, 1), None, "EQ",
              datetime(2025, 1, 1, tzinfo=timezone.utc)),
        Alias("OLDCO", "NSE", "INE000B01019", "iss-2", date(2021, 1, 1), None, "EQ",
              datetime(2021, 1, 2, tzinfo=timezone.utc)),
    ])


def test_reused_symbol_resolves_by_date():
    assert reg().resolve("oldco", "NSE", date(2015, 1, 1)).issuer_id == "iss-1"
    assert reg().resolve("OLDCO", "NSE", date(2022, 1, 1)).issuer_id == "iss-2"


def test_unknown_symbol_is_unresolved_not_assumed_stable():
    r = reg().resolve("NOPE", "NSE", date(2022, 1, 1))
    assert not r.resolved and r.basis == "unresolved"


def test_system_replay_requires_mapping_known_by_cutoff():
    r = reg().resolve("NEWCO", "NSE", date(2022, 1, 1), RunMode.ACTUAL_SYSTEM_REPLAY,
                      datetime(2022, 1, 1, tzinfo=timezone.utc))
    assert r.basis == "mapping_not_known_by_cutoff"
    assert reg().resolve("NEWCO", "NSE", date(2022, 1, 1)).issuer_id == "iss-1"


def test_ambiguous_symbol_raises():
    r = IssuerRegistry(reg().aliases + [Alias("NEWCO", "NSE", "INE000C01017", "iss-3", date(2020, 1, 1))])
    with pytest.raises(IdentityError):
        r.resolve("NEWCO", "NSE", date(2022, 1, 1))


def test_equity_series():  # ported
    assert is_operating_equity_series("W1") is False and is_operating_equity_series(None) is None
    assert is_operating_equity_series("SM") is True and is_operating_equity_series("SM", allow_sme=False) is False


# ---------------- counterparty ----------------

def test_counterparty_matching():  # ported
    assert same_counterparty("NTPC Limited", "National Thermal Power Corporation") is True
    assert same_counterparty("", "Alpha") is None
    assert same_counterparty("Tata Steel Ltd", "Tata Power Company Ltd") is False


def test_issuer_statement_never_independent():
    ev = [RelationshipEvidence("UNRELATED", True, "SEBI order disclosure", date(2026, 1, 5))]
    assert assess_relationship(ev, date(2026, 2, 1))[0] == R.ISSUER_ASSERTED_UNRELATED


def test_independent_source_must_predate_cutoff():
    ev = [RelationshipEvidence("UNRELATED", False, "MCA filing", date(2026, 3, 1))]
    status, used = assess_relationship(ev, date(2026, 2, 1))
    assert status == R.UNKNOWN and used == []
    assert assess_relationship(ev, date(2026, 3, 1))[0] == R.INDEPENDENTLY_SUPPORTED_UNRELATED


def test_related_wins():
    ev = [RelationshipEvidence("UNRELATED", True, "issuer", date(2026, 1, 1)),
          RelationshipEvidence("RELATED", False, "annual report RPT note", date(2026, 1, 2))]
    assert assess_relationship(ev, date(2026, 2, 1))[0] == R.CONFIRMED_RELATED


# ---------------- text extraction ----------------

def test_completeness_statuses():  # ported
    assert classify_pages(["a", "b"], 2)[0] == ExtractionStatus.COMPLETE
    assert classify_pages(["a", ""], 2)[0] == ExtractionStatus.PARTIAL
    assert classify_pages(["a"], 5)[0] == ExtractionStatus.PARTIAL
    assert classify_pages(["", ""], 2)[0] == ExtractionStatus.OCR_REQUIRED
    assert classify_pages([], 0)[0] == ExtractionStatus.EMPTY


def test_text_pdf_extracts_completely_with_pages(tmp_path):  # ported
    pdf = make_pdf(tmp_path / "r.pdf", [RESULTS_PAGE, "Notes: reviewed by the audit committee."])
    res = extract_pdf(pdf)
    assert res.status == ExtractionStatus.COMPLETE and res.pages_expected == 2 and res.pages_with_text == 2
    assert "Revenue from operations" in res.pages[0] and "audit committee" in res.pages[1]


def test_scanned_pdf_needs_ocr(tmp_path):  # ported
    assert extract_pdf(make_pdf(tmp_path / "s.pdf", ["", ""])).status == ExtractionStatus.OCR_REQUIRED


def test_max_page_truncation_is_partial(tmp_path):  # ported
    res = extract_pdf(make_pdf(tmp_path / "l.pdf", [RESULTS_PAGE, "p2", "p3"]), max_pages=2)
    assert res.status == ExtractionStatus.PARTIAL and len(res.pages) == 2
    assert any("processed 2 of 3" in i for i in res.quality_issues)


def test_resource_and_format_limits(tmp_path):
    pdf = make_pdf(tmp_path / "r.pdf", [RESULTS_PAGE])
    assert extract_pdf(pdf, max_bytes=10).status == ExtractionStatus.RESOURCE_LIMIT
    (tmp_path / "x.pdf").write_bytes(b"PK\x03\x04 zip")
    assert extract_pdf(tmp_path / "x.pdf").status == ExtractionStatus.UNSUPPORTED_FORMAT
    (tmp_path / "e.pdf").write_bytes(b"")
    assert extract_pdf(tmp_path / "e.pdf").status == ExtractionStatus.EMPTY
