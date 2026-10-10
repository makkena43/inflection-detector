from datetime import datetime, timezone

from inflection.evidence import ArtifactRecord, Claim, EvidenceRef, validate_claim
from inflection.states import AssertionType, PublicationBasis, RunMode

PUB = datetime(2026, 5, 10, 12, 0, tzinfo=timezone.utc)
CUTOFF = datetime(2026, 6, 1, tzinfo=timezone.utc)
PAGE2 = "Order book stood at Rs 1,240 crore as on 31 March 2026."


class Store:
    def __init__(self, **over):
        rec = dict(text_artifact_id="ta-1", document_version_id="dv-1", issuer_id="iss-1",
                   publication_basis=PublicationBasis.EXCHANGE_TIMESTAMP, published_at=PUB,
                   pages=("cover page", PAGE2), ingested_at=PUB)
        rec.update(over)
        self.rec = ArtifactRecord(**rec)

    def artifact(self, tid):
        return self.rec if tid == self.rec.text_artifact_id else None


def ref(**over):
    start = PAGE2.index("Rs 1,240")
    kw = dict(document_version_id="dv-1", text_artifact_id="ta-1", page_no=2, span_start=start,
              span_end=start + len("Rs 1,240 crore"), quote="Rs 1,240  crore", source_url="https://example.invalid",
              published_at=PUB, assertion_type=AssertionType.REPORTED_FACT)
    kw.update(over)
    return EvidenceRef(**kw)


def fact(r):
    return Claim("c1", "FACT", "order book is 1,240 cr", evidence=(r,))


def test_valid_reference_passes():
    assert validate_claim(fact(ref()), Store(), "iss-1", CUTOFF) == []


def test_quote_mismatch_fails():
    errs = validate_claim(fact(ref(quote="Rs 2,240 crore")), Store(), "iss-1", CUTOFF)
    assert any("quote does not match" in e for e in errs)


def test_after_cutoff_fails():
    errs = validate_claim(fact(ref()), Store(), "iss-1", datetime(2026, 5, 1, tzinfo=timezone.utc))
    assert any("POST_CUTOFF_EVIDENCE" in e for e in errs)


def test_wrong_issuer_and_unknown_publication_fail():
    errs = validate_claim(fact(ref()), Store(issuer_id="iss-2", publication_basis=PublicationBasis.UNKNOWN,
                                             published_at=None), "iss-1", CUTOFF)
    assert any("another issuer" in e for e in errs)
    assert any("UNVERIFIED_PUBLICATION" in e for e in errs)


def test_missing_artifact_and_bad_page():
    assert validate_claim(fact(ref(text_artifact_id="nope")), Store(), "iss-1", CUTOFF)
    assert any("page out of range" in e for e in validate_claim(fact(ref(page_no=9)), Store(), "iss-1", CUTOFF))


def test_fact_without_evidence_fails():
    assert validate_claim(Claim("c", "FACT", "x"), Store(), "iss-1", CUTOFF)


def test_assumption_cannot_carry_citations():
    c = Claim("c", "ASSUMPTION", "utilisation reaches 70%", evidence=(ref(),))
    assert any("assumption carries citations" in e for e in validate_claim(c, Store(), "iss-1", CUTOFF))
    assert validate_claim(Claim("c", "ASSUMPTION", "x"), Store(), "iss-1", CUTOFF) == []


def test_calculated_claim_needs_known_ids():
    c = Claim("c", "CALCULATED", "EPS 5.5", input_ids=("i1", "i9"), calculation_id="calc-1")
    errs = validate_claim(c, Store(), "iss-1", CUTOFF, frozenset({"i1"}), frozenset({"calc-1"}))
    assert errs == ["claim c: unknown input id i9"]


def test_system_replay_needs_ingestion_by_cutoff():
    late = Store(ingested_at=datetime(2026, 7, 1, tzinfo=timezone.utc))
    assert validate_claim(fact(ref()), late, "iss-1", CUTOFF) == []
    errs = validate_claim(fact(ref()), late, "iss-1", CUTOFF, mode=RunMode.ACTUAL_SYSTEM_REPLAY)
    assert any("after the cutoff" in e for e in errs)


def test_date_only_publication_available_end_of_day_ist():
    from datetime import date
    from inflection.asof import available_at
    d = date(2026, 5, 10)
    store = Store(publication_basis=PublicationBasis.DATE_ONLY, published_at=None, published_date=d)
    r = ref(published_at=available_at(PublicationBasis.DATE_ONLY, None, d))
    assert validate_claim(fact(r), store, "iss-1", CUTOFF) == []
    same_day_noon = datetime(2026, 5, 10, 6, 30, tzinfo=timezone.utc)   # 12:00 IST
    assert any("POST_CUTOFF_EVIDENCE" in e for e in validate_claim(fact(r), store, "iss-1", same_day_noon))
