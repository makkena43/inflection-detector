"""Document classification, availability and content hashing.

Ported from MakroGraph ``earnings_inflection/document_versions.py`` at
b31bdd0 (see docs/reuse_inventory.md).  Changes from the original:

* works on plain text + title instead of MakroGraph's ``SourceDocument``;
* the credit-rating-rationale branch is not ported yet (it depended on
  ``rating_rationale.py``, which the spec treats as a reference only);
* availability distinguishes a proven exchange timestamp from a date-only
  publication, and a date-only document is never tradable on that same day.

Classification looks at document contents, not only the title.  A
conference-call invitation is never treated as a transcript.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from enum import Enum
from typing import Optional
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")


class DocumentKind(str, Enum):
    FINANCIAL_RESULTS = "FINANCIAL_RESULTS"
    ANNUAL_REPORT = "ANNUAL_REPORT"
    INVESTOR_PRESENTATION = "INVESTOR_PRESENTATION"
    EARNINGS_CALL_TRANSCRIPT = "EARNINGS_CALL_TRANSCRIPT"
    EARNINGS_CALL_INVITATION = "EARNINGS_CALL_INVITATION"   # never a transcript
    ORDER_ANNOUNCEMENT = "ORDER_ANNOUNCEMENT"
    OTHER_ANNOUNCEMENT = "OTHER_ANNOUNCEMENT"
    UNKNOWN = "UNKNOWN"


_SPEAKER_TURN = re.compile(r"^\s*(?:Moderator|Operator|Management|[A-Z][a-zA-Z.]+(?:\s[A-Z][a-zA-Z.]+){0,3})\s*:", re.M)
_TRANSCRIPT_MARKERS = re.compile(
    r"ladies and gentlemen|question[- ]and[- ]answer|first question is from|"
    r"next question is from|over to you|hand(?:ing)? (?:the )?(?:call|conference) over",
    re.I,
)
_INVITATION_MARKERS = re.compile(
    r"(?:invit(?:e|es|ation)|intimation).{0,120}(?:conference call|earnings call|concall|analyst(?:s)? (?:meet|call))|"
    r"dial[- ]in|universal access number|diamond ?pass|pre-?registration|"
    r"call details|schedule of (?:analyst|investor)",
    re.I | re.S,
)
_RESULTS_MARKERS = re.compile(
    r"statement\s+of\s+[^\n.]{0,80}?(?:financial\s+)?results|"
    r"(?:audited|unaudited|un-audited|reviewed)\b[^\n.]{0,60}?financial\s+results|"
    r"financial\s+results\s+for\s+the\s+(?:quarter|half|year|nine\s+months|period)|"
    r"limited\s+review\s+report|independent\s+auditor'?s'?\s+review\s+report",
    re.I,
)
_RESULTS_TABLE = re.compile(r"(?:revenue|income)\s+from\s+operations[^\n]{0,40}?\d[\d,]*\.\d", re.I)
_ANNUAL_REPORT_MARKERS = re.compile(
    r"directors'? report|board'?s report|management discussion and analysis|"
    r"corporate governance report|notice of (?:the )?\d+(?:st|nd|rd|th) annual general meeting|annual report",
    re.I,
)
_PRESENTATION_MARKERS = re.compile(r"investor presentation|earnings presentation|investor deck|safe harbou?r", re.I)
_ORDER_MARKERS = re.compile(
    r"(?:receipt|bagging|award|secured|received|won)\b.{0,60}\b(?:order|contract|letter of (?:award|intent))|"
    r"letter of (?:award|intent)|purchase order|work order",
    re.I | re.S,
)


def classify_document(text: str, title: str = "") -> tuple[DocumentKind, str]:
    """Return (kind, basis); ``basis`` says which evidence decided it."""
    head = (text or "")[:20000]
    if head.strip():
        speaker_turns = len(_SPEAKER_TURN.findall(head))
        if _TRANSCRIPT_MARKERS.search(head) and speaker_turns >= 4:
            return DocumentKind.EARNINGS_CALL_TRANSCRIPT, f"content:dialogue(turns={speaker_turns})"
        # Results before invitations: board-meeting outcome letters often carry both.
        body = text[:200000]
        if _RESULTS_TABLE.search(body) and _RESULTS_MARKERS.search(body):
            return DocumentKind.FINANCIAL_RESULTS, "content:results-statement+table"
        if _INVITATION_MARKERS.search(head):
            return DocumentKind.EARNINGS_CALL_INVITATION, "content:call-logistics-no-dialogue"
        if _RESULTS_MARKERS.search(head):
            return DocumentKind.FINANCIAL_RESULTS, "content:results-statement"
        if _PRESENTATION_MARKERS.search(head):
            return DocumentKind.INVESTOR_PRESENTATION, "content:presentation"
        if len(_ANNUAL_REPORT_MARKERS.findall(head)) >= 2:
            return DocumentKind.ANNUAL_REPORT, "content:annual-report-sections"
        if _ORDER_MARKERS.search(head):
            return DocumentKind.ORDER_ANNOUNCEMENT, "content:order-language"
        return DocumentKind.OTHER_ANNOUNCEMENT, "content:no-specific-markers"

    t = (title or "").lower()
    if "transcript" in t:
        return DocumentKind.EARNINGS_CALL_TRANSCRIPT, "title_only"
    if re.search(r"conference call|earnings call|analyst.{0,20}meet", t):
        return DocumentKind.EARNINGS_CALL_INVITATION, "title_only"
    if "result" in t:
        return DocumentKind.FINANCIAL_RESULTS, "title_only"
    if "annual report" in t:
        return DocumentKind.ANNUAL_REPORT, "title_only"
    if "presentation" in t:
        return DocumentKind.INVESTOR_PRESENTATION, "title_only"
    if re.search(r"\border\b|contract|letter of award", t):
        return DocumentKind.ORDER_ANNOUNCEMENT, "title_only"
    return DocumentKind.UNKNOWN, "title_only:unclassified"


@dataclass(frozen=True)
class Availability:
    available_at: Optional[datetime]    # earliest moment the information was demonstrably public
    basis: str                          # EXCHANGE_TIMESTAMP | DATE_ONLY | UNKNOWN
    earliest_trade_date: Optional[date] # first session a decision could act on it (before holidays)


def availability(published_at: Optional[datetime], published_date_only: Optional[date]) -> Availability:
    """Proven exchange timestamp wins.  A date-only publication is treated as
    available at the end of that day IST and is not tradable at that day's close."""
    if published_at is not None:
        if published_at.tzinfo is None:
            raise ValueError("published_at must be timezone-aware; refusing to assume a zone")
        local = published_at.astimezone(IST)
        # Information disseminated during or after the session cannot be traded at that close.
        trade = local.date() + timedelta(days=1) if local.time() >= time(9, 15) else local.date()
        return Availability(published_at, "EXCHANGE_TIMESTAMP", trade)
    if published_date_only is not None:
        end = datetime.combine(published_date_only, time(23, 59, 59), tzinfo=IST)
        return Availability(end, "DATE_ONLY", published_date_only + timedelta(days=1))
    return Availability(None, "UNKNOWN", None)


def content_hash(text: str) -> str:
    """Hash of whitespace/case-normalised text, for detecting re-filed identical content."""
    norm = re.sub(r"\s+", " ", text or "").strip().lower()
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()
