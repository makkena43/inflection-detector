"""Shared types: one announcement row, and the coverage outcome of one listing window."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from typing import Any, Optional
from zoneinfo import ZoneInfo

from ..states import PublicationBasis
from .http import Response

IST = ZoneInfo("Asia/Kolkata")


class WindowStatus(str, Enum):
    """Coverage of one listing request window.  Only COMPLETE means "these are all the filings"."""
    COMPLETE = "COMPLETE"
    EMPTY_UNVERIFIED = "EMPTY_UNVERIFIED"   # 200 with no rows: a holiday, or a silent block
    PARTIAL = "PARTIAL"                     # some sub-requests failed or only a category subset was listed
    TRUNCATED = "TRUNCATED"                 # the source has more rows than were fetched
    BLOCKED = "BLOCKED"                     # 401/403/429 or a non-JSON (challenge) page
    FAILED = "FAILED"                       # network error or 5xx after retries


@dataclass(frozen=True)
class Announcement:
    exchange: str                       # "NSE" | "BSE"
    exchange_id: str                    # NSE seq_id / BSE NEWSID
    segment: str                        # NSE index ("equities", "sme") or BSE "equity"
    symbol: str                         # NSE symbol or BSE scrip code
    issuer_name: str
    category: str                       # exchange's own category text, unfiltered
    subcategory: str
    subject: str
    attachment_url: str                 # "" when the filing has no attachment
    published_at: Optional[datetime]    # IST-aware, only when basis is EXCHANGE_TIMESTAMP
    published_date: Optional[date]
    publication_basis: PublicationBasis
    raw_time: str                       # the exchange's original text, kept for audit
    raw: dict = field(default_factory=dict, compare=False, repr=False)


@dataclass
class WindowResult:
    exchange: str
    segment: str
    from_date: date
    to_date: date
    status: WindowStatus
    announcements: list[Announcement] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    requests: int = 0


def parse_exchange_time(text: str, formats: tuple[str, ...], date_formats: tuple[str, ...]
                        ) -> tuple[Optional[datetime], Optional[date], PublicationBasis]:
    """Exchange times are IST wall-clock.  MakroGraph stamped them as UTC (5h30m late); fixed here."""
    s = (text or "").strip()
    if not s:
        return None, None, PublicationBasis.UNKNOWN
    for fmt in formats:
        try:
            dt = datetime.strptime(s, fmt).replace(tzinfo=IST)
            return dt, dt.date(), PublicationBasis.EXCHANGE_TIMESTAMP
        except ValueError:
            continue
    for fmt in date_formats:
        try:
            d = datetime.strptime(s, fmt).date()
            return None, d, PublicationBasis.DATE_ONLY
        except ValueError:
            continue
    return None, None, PublicationBasis.UNKNOWN


def decode_json(resp: Response) -> tuple[WindowStatus, Any, str]:
    """Classify a listing response.  An HTML page where JSON was expected is a bot challenge: BLOCKED."""
    if resp.status is None or (resp.status >= 500):
        return WindowStatus.FAILED, None, resp.error or f"HTTP {resp.status}"
    if resp.blocked:
        return WindowStatus.BLOCKED, None, f"HTTP {resp.status}"
    if resp.status != 200:
        return WindowStatus.FAILED, None, f"HTTP {resp.status}"
    body = resp.body.strip()
    if not body:
        return WindowStatus.EMPTY_UNVERIFIED, None, "empty body"
    try:
        return WindowStatus.COMPLETE, json.loads(body), ""
    except ValueError:
        return WindowStatus.BLOCKED, None, "non-JSON response (likely a bot-protection page)"
