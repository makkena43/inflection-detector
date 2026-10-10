"""NSE corporate announcements.

Ported from MakroGraph ``fetcher/nse_fetcher.py`` at b31bdd0: the bulk date-window endpoint,
month chunking, attachment URL resolution and field mapping.  Changes in the port:

* plain HTTP; the curl_cffi Chrome impersonation is not ported;
* times are IST, not UTC (MakroGraph stamped IST wall-clock as UTC);
* no category/keyword filter at fetch time: every announcement's metadata is kept (spec 6.1);
* an empty window is EMPTY_UNVERIFIED and a blocked one BLOCKED, never "no announcements";
* no ``since`` checkpoint: rows are keyed on ``seq_id``, so reruns are idempotent.
"""

from __future__ import annotations

import calendar
from datetime import date
from typing import Optional
from urllib.parse import urlencode

from .common import Announcement, WindowResult, WindowStatus, decode_json, parse_exchange_time
from .http import HttpClient

NSE_BASE = "https://www.nseindia.com"
NSE_ARCHIVES_BASE = "https://nsearchives.nseindia.com"
ANNOUNCEMENTS_URL = f"{NSE_BASE}/api/corporate-announcements"
REFERER = f"{NSE_BASE}/companies-listing/corporate-filings-announcements"
SEGMENTS = ("equities", "sme")

_TIME_FORMATS = ("%d-%b-%Y %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%d-%m-%Y %H:%M:%S", "%Y-%m-%dT%H:%M:%S",
                 "%d/%m/%Y %H:%M:%S")
_DATE_FORMATS = ("%d-%b-%Y", "%Y-%m-%d", "%d/%m/%Y")


def month_chunks(start: date, end: date) -> list[tuple[date, date]]:
    """Calendar-month windows clipped to [start, end] (ported from ``_generate_month_chunks``)."""
    chunks, cur = [], date(start.year, start.month, 1)
    while cur <= end:
        last = date(cur.year, cur.month, calendar.monthrange(cur.year, cur.month)[1])
        chunks.append((max(cur, start), min(last, end)))
        cur = date(cur.year + (cur.month == 12), cur.month % 12 + 1, 1)
    return chunks


def attachment_url(item: dict) -> str:
    """Ported from ``_resolve_attachment_url``; NSE uses "-" for "no attachment"."""
    a = (item.get("attchmntFile") or item.get("attchmnt") or item.get("attachment") or item.get("fileUrl") or "")
    a = a.strip()
    if not a or a == "-":
        return ""
    if a.startswith("http"):
        return a
    if a.startswith("/"):
        return f"{NSE_BASE}{a}"
    return f"{NSE_ARCHIVES_BASE}/corporate/ANNOUNCEMENTS/{a}"


def parse_item(item: dict, segment: str) -> Optional[Announcement]:
    exchange_id = str(item.get("seq_id") or item.get("id") or "").strip()
    if not exchange_id:
        return None
    raw_time = str(item.get("an_dt") or item.get("exchdisstime") or item.get("dt") or "")
    published_at, published_date, basis = parse_exchange_time(raw_time, _TIME_FORMATS, _DATE_FORMATS)
    return Announcement(
        exchange="NSE", exchange_id=exchange_id, segment=segment,
        symbol=(item.get("symbol") or "").strip().upper(),
        issuer_name=(item.get("sm_name") or item.get("comp") or "").strip(),
        category=(item.get("desc") or "").strip(),
        subcategory=(item.get("smIndustry") or "").strip(),
        subject=(item.get("attchmntText") or "").strip(),
        attachment_url=attachment_url(item),
        published_at=published_at, published_date=published_date, publication_basis=basis,
        raw_time=raw_time, raw=item)


class NSEAnnouncements:
    def __init__(self, client: Optional[HttpClient] = None):
        self.client = client or HttpClient()
        self._warmed = False

    def _warm(self) -> None:
        """Visit the home and filings pages once, as a browser would, so NSE sets its session cookies."""
        if not self._warmed:
            for url in (NSE_BASE, REFERER):
                self.client.get(url, referer=NSE_BASE, accept="text/html,application/xhtml+xml")
            self._warmed = True

    def list_window(self, from_date: date, to_date: date, segment: str = "equities") -> WindowResult:
        if segment not in SEGMENTS:
            raise ValueError(f"segment must be one of {SEGMENTS}")
        before = self.client.requests
        self._warm()
        q = urlencode({"index": segment, "from_date": from_date.strftime("%d-%m-%Y"),
                       "to_date": to_date.strftime("%d-%m-%Y")})
        status, data, note = decode_json(self.client.get(f"{ANNOUNCEMENTS_URL}?{q}", referer=REFERER))
        result = WindowResult("NSE", segment, from_date, to_date, status, notes=[note] if note else [])
        if status == WindowStatus.COMPLETE:
            items = data if isinstance(data, list) else (
                (data or {}).get("data") or (data or {}).get("announcements") or [])
            seen: set[str] = set()
            for item in items:
                a = parse_item(item, segment) if isinstance(item, dict) else None
                if a is None:
                    result.notes.append("row without seq_id skipped")
                    continue
                if a.exchange_id not in seen:
                    seen.add(a.exchange_id)
                    result.announcements.append(a)
            if not result.announcements:
                result.status = WindowStatus.EMPTY_UNVERIFIED
                result.notes.append("no rows: a non-trading day, or an unannounced block")
        result.requests = self.client.requests - before
        return result

    def list_range(self, start: date, end: date, segment: str = "equities") -> list[WindowResult]:
        return [self.list_window(a, b, segment) for a, b in month_chunks(start, end)]
