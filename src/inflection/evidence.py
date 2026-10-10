"""Evidence reference contract and validator (spec section 8).

A material factual claim cites an exact span on a page of a specific text
artifact.  The validator checks that the source exists, was published by the
cutoff, belongs to the case issuer, and that the quoted span really is on that
page.  A quote match does not prove the quote supports the claim; semantic
support is left to review.  Calculated claims cite input and calculation ids,
and assumptions may not carry citations at all.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Protocol

from .states import AssertionType


@dataclass(frozen=True)
class EvidenceRef:
    document_version_id: str
    text_artifact_id: str
    page_no: int
    span_start: int
    span_end: int
    quote: str
    source_url: str
    published_at: datetime
    assertion_type: AssertionType
    section: str = ""


@dataclass(frozen=True)
class Claim:
    claim_id: str
    kind: str                                   # "FACT" | "CALCULATED" | "ASSUMPTION"
    text: str
    evidence: tuple[EvidenceRef, ...] = ()
    input_ids: tuple[str, ...] = ()
    calculation_id: str = ""


@dataclass(frozen=True)
class ArtifactRecord:
    text_artifact_id: str
    document_version_id: str
    issuer_id: Optional[str]
    published_at: Optional[datetime]            # proven publication time; None = unknown
    pages: tuple[str, ...]                      # page-preserving text, page 1 at index 0


class EvidenceStore(Protocol):
    def artifact(self, text_artifact_id: str) -> Optional[ArtifactRecord]: ...


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def validate_ref(ref: EvidenceRef, store: EvidenceStore, issuer_id: str, cutoff: datetime) -> list[str]:
    p = f"evidence {ref.text_artifact_id} p.{ref.page_no}"
    art = store.artifact(ref.text_artifact_id)
    if art is None:
        return [f"{p}: text artifact does not exist"]
    errors = []
    if art.document_version_id != ref.document_version_id:
        errors.append(f"{p}: artifact belongs to document version {art.document_version_id}, "
                      f"not {ref.document_version_id}")
    if art.issuer_id is None:
        errors.append(f"{p}: document is not mapped to an issuer")
    elif art.issuer_id != issuer_id:
        errors.append(f"{p}: document belongs to another issuer")
    if art.published_at is None:
        errors.append(f"{p}: publication time unknown; not usable as point-in-time evidence")
    else:
        if art.published_at > cutoff:
            errors.append(f"{p}: published {art.published_at.isoformat()} after cutoff {cutoff.isoformat()}")
        if ref.published_at != art.published_at:
            errors.append(f"{p}: cited published_at does not match the stored publication time")
    if not 1 <= ref.page_no <= len(art.pages):
        errors.append(f"{p}: page out of range (document has {len(art.pages)} pages)")
        return errors
    page = art.pages[ref.page_no - 1]
    if not 0 <= ref.span_start < ref.span_end <= len(page):
        errors.append(f"{p}: span {ref.span_start}-{ref.span_end} outside page length {len(page)}")
    elif _norm(page[ref.span_start:ref.span_end]) != _norm(ref.quote):
        errors.append(f"{p}: quote does not match the text at span {ref.span_start}-{ref.span_end}")
    return errors


def validate_claim(claim: Claim, store: EvidenceStore, issuer_id: str, cutoff: datetime,
                   known_input_ids: frozenset[str] = frozenset(),
                   known_calculation_ids: frozenset[str] = frozenset()) -> list[str]:
    p = f"claim {claim.claim_id}"
    if claim.kind == "FACT":
        if not claim.evidence:
            return [f"{p}: factual claim has no evidence reference"]
        return [f"{p}: {err}" for ref in claim.evidence for err in validate_ref(ref, store, issuer_id, cutoff)]
    if claim.kind == "CALCULATED":
        errors = []
        if not claim.calculation_id:
            errors.append(f"{p}: calculated claim has no calculation id")
        elif claim.calculation_id not in known_calculation_ids:
            errors.append(f"{p}: unknown calculation id {claim.calculation_id}")
        if not claim.input_ids:
            errors.append(f"{p}: calculated claim lists no input ids")
        errors += [f"{p}: unknown input id {i}" for i in claim.input_ids if i not in known_input_ids]
        return errors
    if claim.kind == "ASSUMPTION":
        if claim.evidence:
            return [f"{p}: assumption carries citations; cite the facts it rests on as separate FACT claims"]
        return []
    return [f"{p}: unknown claim kind {claim.kind!r}"]
