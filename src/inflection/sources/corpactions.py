"""NSE corporate actions (splits, bonuses, dividends ...) from the exchange's own listing.

New code (MakroGraph has no corporate-actions fetcher).  It uses the same NSE JSON API family and
cookie warm-up as the announcements adapter (``nse.py``).  Every row is kept; splits and bonuses
are parsed into a price multiplier, the factor by which prices before the ex-date are scaled:

* ``Bonus 1:2`` (one new share for every two held): multiplier 2 / 3;
* ``Face Value Split (Sub-Division) - From Rs 10/- Per Share To Rs 2/- Per Share``: 2 / 10;
* a consolidation (``From Re 1/- ... To Rs 10/-``) gives a multiplier above one.

A split or bonus whose ratio cannot be read keeps its row with no multiplier and is reported.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Optional
from urllib.parse import urlencode

from .bhavcopy import _date
from .common import WindowStatus, decode_json
from .http import HttpClient
from .nse import NSE_BASE

ACTIONS_URL = f"{NSE_BASE}/api/corporates-corporateActions"
REFERER = f"{NSE_BASE}/companies-listing/corporate-filings-actions"
INDEXES = ("equities", "sme")
_DATES = ("%d-%b-%Y", "%d-%m-%Y", "%Y-%m-%d", "%d/%m/%Y")
_BONUS = re.compile(r"bonus[^0-9]*(\d+(?:\.\d+)?)\s*:\s*(\d+(?:\.\d+)?)", re.I)
_FACE = re.compile(r"from\s*(?:rs|re|inr|₹)?\.?\s*(\d+(?:\.\d+)?).*?to\s*(?:rs|re|inr|₹)?\.?\s*(\d+(?:\.\d+)?)",
                   re.I | re.S)


@dataclass(frozen=True)
class Action:
    symbol: str
    isin: Optional[str]
    kind: str                           # SPLIT | BONUS | DIVIDEND | RIGHTS | BUYBACK | OTHER
    ex_date: date
    subject: str
    price_multiplier: Optional[Decimal]  # SPLIT / BONUS only; None when the ratio could not be read
    ratio: Optional[str]
    raw: dict


@dataclass
class ActionWindow:
    index: str
    from_date: date
    to_date: date
    status: WindowStatus
    actions: list[Action] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    requests: int = 0


def _dec(s: str) -> Optional[Decimal]:
    try:
        d = Decimal(s)
    except InvalidOperation:
        return None
    return d if d > 0 else None


def parse_subject(subject: str) -> list[tuple[str, Optional[Decimal], Optional[str]]]:
    """(kind, price multiplier, ratio text) for each action named in one subject line."""
    s = subject.lower()
    out = []
    if "bonus" in s:
        m = _BONUS.search(subject)
        new, held = (_dec(m.group(1)), _dec(m.group(2))) if m else (None, None)
        out.append(("BONUS", held / (new + held) if new and held else None,
                    f"{m.group(1)}:{m.group(2)}" if m else None))
    if "split" in s or "sub-division" in s or "subdivision" in s or "consolidation" in s:
        m = _FACE.search(subject[s.find("from"):] if "from" in s else subject)
        old, new = (_dec(m.group(1)), _dec(m.group(2))) if m else (None, None)
        out.append(("SPLIT", new / old if old and new else None, f"{m.group(1)}->{m.group(2)}" if m else None))
    if out:
        return out
    for word, kind in (("dividend", "DIVIDEND"), ("rights", "RIGHTS"), ("buy back", "BUYBACK"),
                       ("buyback", "BUYBACK")):
        if word in s:
            return [(kind, None, None)]
    return [("OTHER", None, None)]


def parse_item(item: dict) -> list[Action]:
    symbol = str(item.get("symbol") or "").strip().upper()
    ex = _date(str(item.get("exDate") or ""), _DATES)
    subject = str(item.get("subject") or "").strip()
    if not symbol or not ex or not subject:
        return []
    isin = str(item.get("isin") or "").strip().upper() or None
    return [Action(symbol, isin, kind, ex, subject, mult, ratio, item) for kind, mult, ratio in parse_subject(subject)]


class NSECorporateActions:
    def __init__(self, client: Optional[HttpClient] = None):
        self.client = client or HttpClient()
        self._warmed = False

    def _warm(self) -> None:
        if not self._warmed:
            for url in (NSE_BASE, REFERER):
                self.client.get(url, referer=NSE_BASE, accept="text/html,application/xhtml+xml")
            self._warmed = True

    def list_window(self, from_date: date, to_date: date, index: str = "equities") -> ActionWindow:
        if index not in INDEXES:
            raise ValueError(f"index must be one of {INDEXES}")
        before = self.client.requests
        self._warm()
        q = urlencode({"index": index, "from_date": from_date.strftime("%d-%m-%Y"),
                       "to_date": to_date.strftime("%d-%m-%Y")})
        status, data, note = decode_json(self.client.get(f"{ACTIONS_URL}?{q}", referer=REFERER))
        w = ActionWindow(index, from_date, to_date, status, notes=[note] if note else [])
        if status == WindowStatus.COMPLETE:
            items = data if isinstance(data, list) else ((data or {}).get("data") or [])
            for item in items:
                parsed = parse_item(item) if isinstance(item, dict) else []
                if not parsed:
                    w.notes.append("row without symbol, ex-date or subject skipped")
                w.actions.extend(parsed)
            if not items:
                w.status = WindowStatus.EMPTY_UNVERIFIED
                w.notes.append("no rows")
        w.requests = self.client.requests - before
        return w
