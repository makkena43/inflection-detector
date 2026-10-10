"""Controlled vocabularies from the design spec (v1.0).

Each enum here has a matching CHECK constraint in ``db/migrations``; the test
suite fails if the two drift apart.

Where the pasted spec was internally inconsistent, the choice made is noted
on the member (see docs/spec_open_issues.md).
"""

from __future__ import annotations

from enum import Enum


class WorkflowState(str, Enum):
    QUEUED = "QUEUED"
    TRIAGING = "TRIAGING"
    WATCH = "WATCH"
    RESEARCHING = "RESEARCHING"
    # Fully researched, but the investor policy (return hurdle, downside,
    # position/liquidity limits) is not set yet.  Used in spec section 7 but
    # missing from the section 8 list.
    AWAITING_INVESTMENT_POLICY = "AWAITING_INVESTMENT_POLICY"
    READY_FOR_INVESTOR_REVIEW = "READY_FOR_INVESTOR_REVIEW"
    REJECTED = "REJECTED"
    DATA_REPAIR = "DATA_REPAIR"
    DEFERRED = "DEFERRED"
    # Budget exhausted; work is preserved.  Used in spec section 10 but
    # missing from the section 8 list.
    DEFERRED_BUDGET = "DEFERRED_BUDGET"
    # Section 18.3: an unresearched case is never expired into rejection.
    STALE_UNRESEARCHED = "STALE_UNRESEARCHED"
    CLOSED = "CLOSED"


class BusinessEvidenceState(str, Enum):
    EMERGING = "EMERGING"
    COMMERCIALLY_VALIDATED = "COMMERCIALLY_VALIDATED"
    SCALING = "SCALING"
    DETERIORATING = "DETERIORATING"
    UNKNOWN = "UNKNOWN"


class RecommendationState(str, Enum):
    CONSIDER_WITHIN_PRICE_BAND = "CONSIDER_WITHIN_PRICE_BAND"
    WATCH_MILESTONE = "WATCH_MILESTONE"
    PASS_VALUATION = "PASS_VALUATION"
    PASS_RISK = "PASS_RISK"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    REVIEW_EXISTING_POSITION = "REVIEW_EXISTING_POSITION"


class InvestorDecision(str, Enum):
    NOT_REVIEWED = "NOT_REVIEWED"
    APPROVED = "APPROVED"
    # Workflow step 8 lets the investor "request changes"; the section 8 list
    # had no value for it.
    CHANGES_REQUESTED = "CHANGES_REQUESTED"
    DECLINED = "DECLINED"
    DEFERRED = "DEFERRED"
    REVOKED = "REVOKED"


class RelationshipStatus(str, Enum):
    """Counterparty relationship (workflow step 3).  UNKNOWN is not shell/fraud."""
    CONFIRMED_RELATED = "CONFIRMED_RELATED"
    ISSUER_ASSERTED_UNRELATED = "ISSUER_ASSERTED_UNRELATED"
    INDEPENDENTLY_SUPPORTED_UNRELATED = "INDEPENDENTLY_SUPPORTED_UNRELATED"
    UNKNOWN = "UNKNOWN"


class InputStatus(str, Enum):
    """Provenance of a scenario input (section 7).  Forecasts never become OBSERVED."""
    OBSERVED = "OBSERVED"
    MANAGEMENT_GUIDANCE = "MANAGEMENT_GUIDANCE"
    ANALYST_ASSUMPTION = "ANALYST_ASSUMPTION"
    DERIVED = "DERIVED"


class AssertionType(str, Enum):
    """What kind of claim an evidence reference supports (section 8)."""
    REPORTED_FACT = "REPORTED_FACT"
    MANAGEMENT_STATEMENT = "MANAGEMENT_STATEMENT"
    COMMERCIAL_COMMITMENT = "COMMERCIAL_COMMITMENT"
    THIRD_PARTY_STATEMENT = "THIRD_PARTY_STATEMENT"


class Scenario(str, Enum):
    DOWNSIDE = "DOWNSIDE"
    BASE = "BASE"
    UPSIDE = "UPSIDE"


class RunMode(str, Enum):
    """Section 12: every run carries ``as_of`` and one of these modes."""
    LIVE = "LIVE"
    PUBLIC_INFORMATION_RECONSTRUCTION = "PUBLIC_INFORMATION_RECONSTRUCTION"
    ACTUAL_SYSTEM_REPLAY = "ACTUAL_SYSTEM_REPLAY"


class CoverageStatus(str, Enum):
    """Ingestion coverage.  An empty response is not proof of complete coverage."""
    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"                     # some sub-requests failed, or only a category subset
    TRUNCATED = "TRUNCATED"                 # the source has more rows than were fetched
    EMPTY_UNVERIFIED = "EMPTY_UNVERIFIED"
    BLOCKED = "BLOCKED"                     # 401/403/429 or a bot-protection page
    FAILED = "FAILED"
    NOT_ATTEMPTED = "NOT_ATTEMPTED"


class PipelineState(str, Enum):
    """Section 4: processing state of one publication.  FAILED is not an empty filing."""
    DISCOVERED = "DISCOVERED"
    DOWNLOADED = "DOWNLOADED"
    TEXT_READY = "TEXT_READY"
    OCR_REQUIRED = "OCR_REQUIRED"
    PARTIAL_TEXT = "PARTIAL_TEXT"
    FAILED = "FAILED"
    SUPERSEDED = "SUPERSEDED"


class PublicationBasis(str, Enum):
    EXCHANGE_TIMESTAMP = "EXCHANGE_TIMESTAMP"
    DATE_ONLY = "DATE_ONLY"
    UNKNOWN = "UNKNOWN"


class MissingReason(str, Enum):
    """Section 17: a missing value is null plus one of these, never zero."""
    NOT_APPLICABLE = "NOT_APPLICABLE"
    NOT_DISCLOSED = "NOT_DISCLOSED"
    FETCH_FAILED = "FETCH_FAILED"
    UNVERIFIED = "UNVERIFIED"


class PeriodType(str, Enum):
    QUARTER = "QUARTER"
    HALF_YEAR = "HALF_YEAR"
    NINE_MONTHS = "NINE_MONTHS"
    ANNUAL = "ANNUAL"


class StatementScope(str, Enum):
    CONSOLIDATED = "CONSOLIDATED"
    STANDALONE = "STANDALONE"
    SEGMENT = "SEGMENT"
    UNKNOWN = "UNKNOWN"


class CommercialStage(str, Enum):
    """Section 5.2, in order of advancement; CANCELLED and UNKNOWN sit outside the order."""
    AMBITION = "AMBITION"
    FUNDED_PLAN = "FUNDED_PLAN"
    QUALIFIED = "QUALIFIED"
    BINDING_DEMAND = "BINDING_DEMAND"
    COMMERCIAL_SHIPMENT = "COMMERCIAL_SHIPMENT"
    REPEAT_SHIPMENT = "REPEAT_SHIPMENT"
    CANCELLED = "CANCELLED"
    UNKNOWN = "UNKNOWN"


class AmountBasis(str, Enum):
    """How firm a stated amount is.  ``CEILING`` ("up to") is not guaranteed revenue."""
    FIRM = "FIRM"
    CEILING = "CEILING"
    GUARANTEED_MINIMUM = "GUARANTEED_MINIMUM"
    EXECUTABLE_RELEASE = "EXECUTABLE_RELEASE"
    NON_BINDING = "NON_BINDING"
    UNQUANTIFIED = "UNQUANTIFIED"


class MaterialityStatus(str, Enum):
    MATERIAL_POTENTIAL = "MATERIAL_POTENTIAL"
    MATERIALITY_UNKNOWN = "MATERIALITY_UNKNOWN"
    IMMATERIAL = "IMMATERIAL"


class FundingStatus(str, Enum):
    FUNDED = "FUNDED"
    UNRESOLVED = "UNRESOLVED"
    STRESSED = "STRESSED"


class PriorityClass(str, Enum):
    """Section 18.2."""
    U0 = "U0"
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"
    D = "D"


class TriageAction(str, Enum):
    """Section 5.3.  Triage may never recommend Buy."""
    DEEP_RESEARCH = "DEEP_RESEARCH"
    WATCH_MILESTONE = "WATCH_MILESTONE"
    REJECT_WITH_REASON = "REJECT_WITH_REASON"
    DATA_REPAIR = "DATA_REPAIR"
    DEFER_BUDGET = "DEFER_BUDGET"


class EvidenceRelation(str, Enum):
    SUPPORTS = "SUPPORTS"
    CONTRADICTS = "CONTRADICTS"
    CONTEXT = "CONTEXT"


class ValidityStatus(str, Enum):
    """Section 15 test 15: an old recommendation is shown with its validity, never as current by default."""
    VALID = "VALID"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    EXPIRED = "EXPIRED"
    SUPERSEDED = "SUPERSEDED"


class IdentityStatus(str, Enum):
    VERIFIED = "VERIFIED"
    PROVISIONAL = "PROVISIONAL"
    UNRESOLVED = "UNRESOLVED"
    CONFLICT = "CONFLICT"


class AccessMode(str, Enum):
    """Section 3.2 source access modes.  BLOCKED sources are reported, never worked around."""
    LICENSED_FEED = "LICENSED_FEED"
    PUBLIC_PERMITTED = "PUBLIC_PERMITTED"
    USER_EXPORT = "USER_EXPORT"
    MANUAL_IMPORT = "MANUAL_IMPORT"
    BLOCKED = "BLOCKED"


class ErrorCode(str, Enum):
    """Section 19 API error codes."""
    STALE_REVISION = "STALE_REVISION"
    PACKET_CHANGED = "PACKET_CHANGED"
    POST_CUTOFF_EVIDENCE = "POST_CUTOFF_EVIDENCE"
    UNVERIFIED_PUBLICATION = "UNVERIFIED_PUBLICATION"
    EVIDENCE_SPAN_MISMATCH = "EVIDENCE_SPAN_MISMATCH"
    BUDGET_EXCEEDED = "BUDGET_EXCEEDED"
    LEASE_CONFLICT = "LEASE_CONFLICT"
    SOURCE_ACCESS_DENIED = "SOURCE_ACCESS_DENIED"
    FINANCIAL_SCOPE_MISMATCH = "FINANCIAL_SCOPE_MISMATCH"
    INVESTOR_POLICY_REQUIRED = "INVESTOR_POLICY_REQUIRED"
