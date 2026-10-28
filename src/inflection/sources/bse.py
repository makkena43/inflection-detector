"""BSE corporate announcements.

Ported from MakroGraph ``fetcher/bse_fetcher.py`` at b31bdd0: the ``AnnSubCategoryGetData``
endpoint and parameters, the per-category sweep, weekly windows, attachment URL resolution
(AttachLive / AttachHis) and field mapping.  Changes in the port:

* plain HTTP with the same Origin/Referer as BSE's own announcements page (as MakroGraph sent);
  the CLI routes through ``curl_cffi_transport`` (browser TLS fingerprint) when curl_cffi is
  installed, since api.bseindia.com's Akamai edge rejects plain urllib; Playwright/Selenium
  cookie harvesting and the cookie cache are not ported;
* each calendar day is queried separately: the all-category endpoint can silently return no
  rows for a multi-day range. The all-category query (``strCat=-1``) is tried first; when it returns nothing the sweep over
  ``CATEGORIES`` runs and the window is PARTIAL (a category subset), never COMPLETE;
* pages are followed until the reported row count is reached; a page cap makes the window
  TRUNCATED instead of silently stopping (MakroGraph assumed < 50 rows and capped runs at 500);
* times are IST, and ``%I`` is used with AM/PM (MakroGraph's ``%H ... %p`` turned 3 PM into 03:00);
* dissemination time (``DissemDT``) is preferred over ``NEWS_DT``.
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Optional
from urllib.parse import urlencode

from .common import Announcement, WindowResult, WindowStatus, decode_json, parse_exchange_time
from .http import HttpClient

API_URL = "https://api.bseindia.com/BseIndiaAPI/api/AnnSubCategoryGetData/w"
ATTACH_LIVE = "https://www.bseindia.com/xml-data/corpfiling/AttachLive"
ATTACH_HIS = "https://www.bseindia.com/xml-data/corpfiling/AttachHis"
ORIGIN = "https://www.bseindia.com"
REFERER = f"{ORIGIN}/"
# Akamai rejects API calls lacking browser navigation headers (403 before any rate limit).
EXTRA_HEADERS = {"Accept-Language": "en-US,en;q=0.5", "Sec-Fetch-Site": "same-site"}
PAGE_SIZE = 50

# MakroGraph's sweep list (``_COOKIE_FREE_CATEGORIES``); filings outside these are not listed
# when the all-category query is unavailable, which is why such windows are PARTIAL.
# "Company Update" is where BSE files orders, press releases, investor presentations and con-call transcripts
# (as subcategories); "Others" and "Insider Trading / SAST" complete BSE's current category list (checked 2026-10-19:
# "Press Release" and "Analysts/Institutional Investor Meet" return nothing as categories any more).
CATEGORIES = ("Board Meeting", "Result", "Corp. Action", "AGM/EGM", "Company Update", "Others", "Insider Trading / SAST",
              "New Listing", "Scheme of Arrangement", "Acquisition", "Amalgamation",
              "Analysts/Institutional Investor Meet", "Press Release")

_TIME_FORMATS = ("%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S", "%m/%d/%Y %I:%M:%S %p", "%d/%m/%Y %H:%M:%S",
                 "%Y-%m-%d %H:%M:%S", "%d-%m-%Y %H:%M:%S")
_DATE_FORMATS = ("%m/%d/%Y", "%Y-%m-%d")
_UUID = re.compile(r"[0-9a-f\-]{36}", re.I)


def week_chunks(start: date, end: date, days: int = 7) -> list[tuple[date, date]]:
    out, cur = [], start
    while cur <= end:
        out.append((cur, min(cur + timedelta(days=days - 1), end)))
        cur += timedelta(days=days)
    return out


def attachment_url(name: str) -> str:
    """Ported from ``_build_attachment_url``: UUID names live under AttachLive, legacy paths under AttachHis."""
    if not name:
        return ""
    if name.startswith("http"):
        return name
    f = name.strip().lstrip("/")
    if _UUID.fullmatch(f.removesuffix(".pdf").removesuffix(".PDF")):
        stem = f[:36].lower()
        return f"{ATTACH_LIVE}/{stem}.pdf"
    return f"{ATTACH_HIS}/{f}"


def _published(item: dict) -> tuple[str, tuple]:
    for key in ("DissemDT", "DT_TM", "NEWS_DT"):
        raw = str(item.get(key) or "").strip()
        if raw:
            parsed = parse_exchange_time(raw, _TIME_FORMATS, _DATE_FORMATS)
            if parsed[2].value != "UNKNOWN":
                return raw, parsed
    raw = str(item.get("NEWS_DT") or item.get("DissemDT") or "")
    return raw, parse_exchange_time(raw, _TIME_FORMATS, _DATE_FORMATS)


def parse_item(item: dict) -> Optional[Announcement]:
    exchange_id = str(item.get("NEWSID") or "").strip()
    if not exchange_id:
        return None
    raw_time, (published_at, published_date, basis) = _published(item)
    return Announcement(
        exchange="BSE", exchange_id=exchange_id, segment="equity",
        symbol=str(item.get("SCRIP_CD") or item.get("SECURITYCODE") or "").strip(),
        issuer_name=(item.get("SLONGNAME") or item.get("COMPANYLNAME") or "").strip(),
        category=(item.get("CATEGORYNAME") or "").strip(),
        subcategory=(item.get("SUBCATNAME") or "").strip(),
        subject=(item.get("NEWSSUB") or item.get("HEADLINE") or "").strip(),
        attachment_url=attachment_url(item.get("ATTACHMENTNAME") or item.get("FILENAME") or ""),
        published_at=published_at, published_date=published_date, publication_basis=basis,
        raw_time=raw_time, raw=item)


def _row_count(data) -> Optional[int]:
    try:
        return int((data.get("Table1") or [{}])[0].get("ROWCNT"))
    except (AttributeError, TypeError, ValueError, IndexError):
        return None


class BSEAnnouncements:
    def __init__(self, client: Optional[HttpClient] = None, max_pages: int = 300,   # Company Update: ~3,000 rows a week, up to ~12,000 in results weeks
                 categories: tuple[str, ...] = CATEGORIES):
        self.client = client or HttpClient()
        self.max_pages, self.categories = max_pages, categories

    def _query(self, category: str, from_date: date, to_date: date, scrip: str
               ) -> tuple[WindowStatus, list[dict], list[str]]:
        rows: list[dict] = []
        notes: list[str] = []
        total: Optional[int] = None
        for page in range(1, self.max_pages + 1):
            q = urlencode({"pageno": page, "strCat": category, "strPrevDate": from_date.strftime("%Y%m%d"),
                           "strScrip": scrip, "strSearch": "P", "strToDate": to_date.strftime("%Y%m%d"),
                           "strType": "C", "subcategory": "-1"})
            status, data, note = decode_json(self.client.get(f"{API_URL}?{q}", referer=REFERER, origin=ORIGIN,
                                                           extra_headers=EXTRA_HEADERS))
            if status != WindowStatus.COMPLETE:
                if page == 1:
                    return status, [], [f"{category}: {note}"]
                return WindowStatus.PARTIAL, rows, notes + [f"{category} page {page}: {note}"]
            table = (data.get("Table") or []) if isinstance(data, dict) else (data or [])
            total = _row_count(data) if total is None and isinstance(data, dict) else total
            rows.extend(table)
            if not table or len(table) < PAGE_SIZE or (total is not None and len(rows) >= total):
                break
        else:
            return WindowStatus.TRUNCATED, rows, [f"{category}: stopped at {self.max_pages} pages "
                                                  f"({len(rows)} of {total if total is not None else '?'} rows)"]
        if not rows:
            return WindowStatus.EMPTY_UNVERIFIED, [], [f"{category}: no rows"]
        if total is not None and len(rows) < total:
            return WindowStatus.TRUNCATED, rows, [f"{category}: {len(rows)} of {total} rows"]
        ids = [str(r.get('NEWSID')) for r in rows if isinstance(r, dict) and r.get('NEWSID')]
        if len(ids) != len(set(ids)):
            return WindowStatus.PARTIAL, rows, [f"{category}: duplicate IDs across pages; listing may have shifted during pagination"]
        return WindowStatus.COMPLETE, rows, notes

    def list_window(self, from_date: date, to_date: date, scrip: str = "") -> WindowResult:
        if from_date > to_date:
            raise ValueError("start must not be after end")
        if from_date < to_date:
            # The public all-category endpoint returns an empty payload for multi-day
            # queries even when individual days have thousands of rows. Query each day.
            days = list(self.iter_range(from_date, to_date, scrip))
            statuses = {w.status for w in days}
            status = (WindowStatus.COMPLETE if statuses == {WindowStatus.COMPLETE} else
                      WindowStatus.TRUNCATED if WindowStatus.TRUNCATED in statuses else
                      WindowStatus.PARTIAL if any(w.announcements for w in days) else
                      WindowStatus.BLOCKED if WindowStatus.BLOCKED in statuses else
                      WindowStatus.FAILED if WindowStatus.FAILED in statuses else
                      WindowStatus.PARTIAL if WindowStatus.PARTIAL in statuses else WindowStatus.EMPTY_UNVERIFIED)
            seen = {}
            for w in days:
                for a in w.announcements:
                    seen.setdefault(a.exchange_id, a)
            return WindowResult("BSE", "equity", from_date, to_date, status,
                announcements=list(seen.values()),
                notes=[f"{w.from_date}: {n}" for w in days for n in w.notes],
                requests=sum(w.requests for w in days))
        before = self.client.requests
        result = WindowResult("BSE", "equity", from_date, to_date, WindowStatus.COMPLETE)
        status, rows, notes = self._query("-1", from_date, to_date, scrip)
        result.notes += notes
        if status == WindowStatus.EMPTY_UNVERIFIED or status == WindowStatus.BLOCKED:
            result.notes.append("all-category query unavailable; listed a category subset: "
                                + ", ".join(self.categories))
            statuses = []
            for cat in self.categories:
                s, r, n = self._query(cat, from_date, to_date, scrip)
                statuses.append(s)
                rows += r
                result.notes += n
            if all(s in (WindowStatus.BLOCKED, WindowStatus.FAILED) for s in statuses):
                status = WindowStatus.BLOCKED if WindowStatus.BLOCKED in statuses else WindowStatus.FAILED
            elif not rows:
                status = WindowStatus.EMPTY_UNVERIFIED
            elif WindowStatus.TRUNCATED in statuses:
                status = WindowStatus.TRUNCATED
            else:
                status = WindowStatus.PARTIAL
        result.status = status
        seen: set[str] = set()
        for row in rows:
            a = parse_item(row) if isinstance(row, dict) else None
            if a is None:
                result.notes.append("row without NEWSID skipped")
                if result.status == WindowStatus.COMPLETE:
                    result.status = WindowStatus.PARTIAL
            elif a.exchange_id not in seen:
                seen.add(a.exchange_id)
                result.announcements.append(a)
        result.requests = self.client.requests - before
        return result

    def list_range(self, start: date, end: date, scrip: str = "") -> list[WindowResult]:
        return list(self.iter_range(start, end, scrip))

    def iter_range(self, start: date, end: date, scrip: str = ""):
        """Yield each completed day so callers can persist progress before the next request."""
        for a, b in week_chunks(start, end, days=1):
            yield self.list_window(a, b, scrip)
