"""Controlled vocabularies from the design spec (sections 6-9, 12).

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
    PARTIAL = "PARTIAL"
    EMPTY_UNVERIFIED = "EMPTY_UNVERIFIED"
    FAILED = "FAILED"
    NOT_ATTEMPTED = "NOT_ATTEMPTED"
