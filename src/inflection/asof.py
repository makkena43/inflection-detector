"""The one as-of predicate (spec section 17).

Packet assembly, evidence search, scenario calculation and submission
validation must all use this function rather than their own cutoff rules.

A source is eligible at ``cutoff`` when:
* its availability is known (unknown availability blocks historical use);
* it was available by the cutoff (a date-only publication counts as
  available at the end of that day IST); and
* in ACTUAL_SYSTEM_REPLAY, the system had also ingested it by the cutoff.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time
from typing import Optional
from zoneinfo import ZoneInfo

from .states import PublicationBasis, RunMode

IST = ZoneInfo("Asia/Kolkata")


@dataclass(frozen=True)
class Eligibility:
    eligible: bool
    reason: str
    available_at: Optional[datetime] = None


def available_at(basis: PublicationBasis, published_at: Optional[datetime],
                 published_date: Optional[date]) -> Optional[datetime]:
    if basis == PublicationBasis.EXCHANGE_TIMESTAMP:
        if published_at is None or published_at.tzinfo is None:
            raise ValueError("EXCHANGE_TIMESTAMP needs a timezone-aware published_at")
        return published_at
    if basis == PublicationBasis.DATE_ONLY:
        if published_date is None:
            raise ValueError("DATE_ONLY needs published_date")
        return datetime.combine(published_date, time(23, 59, 59), tzinfo=IST)
    return None


def eligible(cutoff: datetime, mode: RunMode, basis: PublicationBasis, published_at: Optional[datetime] = None,
             published_date: Optional[date] = None, ingested_at: Optional[datetime] = None) -> Eligibility:
    if cutoff.tzinfo is None:
        raise ValueError("cutoff must be timezone-aware")
    avail = available_at(basis, published_at, published_date)
    if avail is None:
        return Eligibility(False, "UNVERIFIED_PUBLICATION: publication time unknown")
    if avail > cutoff:
        return Eligibility(False, f"POST_CUTOFF_EVIDENCE: available {avail.isoformat()}", avail)
    if mode == RunMode.ACTUAL_SYSTEM_REPLAY:
        if ingested_at is None:
            return Eligibility(False, "ingestion time unknown; cannot prove the system held it", avail)
        if ingested_at > cutoff:
            return Eligibility(False, f"ingested {ingested_at.isoformat()}, after the cutoff", avail)
    return Eligibility(True, "ok", avail)
