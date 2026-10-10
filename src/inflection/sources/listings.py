"""Exchange listing files: who is listed, under which code and ISIN, and whether suspended or delisted.

Ported from MakroGraph ``fetcher/sector_master_fetcher.py`` (NSE ``EQUITY_L.csv`` and the BSE
``Equity.csv`` column map) and ``fetcher/bse_fetcher.py`` (the BSE ``ListofScripData`` API) at
b31bdd0 (see docs/reuse_inventory.md).  Differences:

* NSE's SME list and symbol change file are read too;
* BSE is asked for each status (Active, Suspended, Delisted), not only Active, so companies that
  left the market stay in the company list;
* plain rate-limited requests.  BSE's API answers plain requests with a block; that is reported as
  BLOCKED, and ``parse_bse`` also reads the Equity.csv file downloaded from BSE's website;
* rows keep every column as published (``raw``) and nothing is filtered at fetch time.
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field, replace
from datetime import date
from decimal import Decimal
from typing import Optional
from urllib.parse import urlencode

from .bhavcopy import _date, _isin, _num, _text, csv_records
from .common import WindowStatus, decode_json
from .http import HttpClient

NSE_EQUITY_URL = "https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv"
NSE_SME_URL = "https://nsearchives.nseindia.com/emerge/corporates/content/SME_EQUITY_L.csv"
NSE_SYMBOL_CHANGE_URL = "https://nsearchives.nseindia.com/content/equities/symbolchange.csv"
NSE_REFERER = "https://www.nseindia.com/"
BSE_SCRIPS_URL = "https://api.bseindia.com/BseIndiaAPI/api/ListofScripData/w"
BSE_REFERER = "https://www.bseindia.com/"
BSE_STATUSES = {"Active": "ACTIVE", "Suspended": "SUSPENDED", "Delisted": "DELISTED"}
BSE_SME_GROUPS = ("M", "MT")
CSV_ACCEPT = "text/csv, application/octet-stream, */*"
_DATES = ("%d-%b-%Y", "%d-%b-%y", "%d-%m-%Y", "%d/%m/%Y", "%Y-%m-%d")


@dataclass(frozen=True)
class ListingRow:
    exchange: str                   # "NSE" | "BSE"
    list_name: str                  # NSE_EQUITY_L, NSE_SME_EQUITY_L, BSE_ACTIVE, BSE_FILE ...
    code: str                       # NSE symbol / BSE scrip code
    status: str                     # ACTIVE | SUSPENDED | DELISTED | UNKNOWN
    board: str                      # MAINBOARD | SME | UNKNOWN
    raw: dict
    ticker: Optional[str] = None    # BSE security id
    isin: Optional[str] = None
    name: Optional[str] = None
    series: Optional[str] = None
    listing_date: Optional[date] = None
    face_value: Optional[Decimal] = None
    industry: Optional[str] = None


@dataclass(frozen=True)
class SymbolChange:
    old_symbol: str
    new_symbol: str
    effective_date: date
    name: Optional[str] = None


@dataclass
class ListResult:
    exchange: str
    list_name: str
    status: WindowStatus
    rows: list = field(default_factory=list)            # ListingRow or SymbolChange
    notes: list[str] = field(default_factory=list)
    files: list[tuple[str, bytes]] = field(default_factory=list)
    requests: int = 0


# ---------------------------------------------------------------- parsing

def _key(k: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", (k or "").upper())


def _pick(r: dict, *names: str) -> Optional[str]:
    for n in names:
        v = _text(r.get(n))
        if v:
            return v
    return None


def _normalised(rows: list[dict]) -> list[tuple[dict, dict]]:
    """(normalised-key row, original row) pairs; keys become upper-case letters and digits only."""
    return [({_key(k): ("" if v is None else str(v).strip()) for k, v in r.items()}, r) for r in rows]


def parse_nse(body: bytes, list_name: str, board: str) -> list[ListingRow]:
    """NSE EQUITY_L.csv / SME_EQUITY_L.csv (header spellings differ between the two)."""
    out = []
    for r, raw in _normalised(csv_records(body)):
        code = _pick(r, "SYMBOL")
        if not code:
            continue
        out.append(ListingRow(
            "NSE", list_name, code.upper(), "ACTIVE", board, raw, isin=_isin(_pick(r, "ISINNUMBER", "ISIN")),
            name=_pick(r, "NAMEOFCOMPANY", "COMPANYNAME", "NAME"), series=_pick(r, "SERIES"),
            listing_date=_date(_pick(r, "DATEOFLISTING", "LISTINGDATE") or "", _DATES),
            face_value=_num(_pick(r, "FACEVALUE"))))
    return out


def parse_symbol_changes(body: bytes) -> list[SymbolChange]:
    """NSE symbolchange.csv: company name, old symbol, new symbol, effective date.  The file is
    sometimes published without its header row, so columns are read by position."""
    text = body.decode("utf-8-sig", errors="replace")
    if text.lstrip()[:1] == "<":
        raise ValueError("HTML page instead of CSV")
    out = []
    for row in csv.reader(io.StringIO(text)):
        cells = [c.strip() for c in row]
        if len(cells) < 4 or _key(cells[0]).startswith("SMNAME") or not cells[1] or not cells[2]:
            continue
        d = _date(cells[3], _DATES)
        if d:
            out.append(SymbolChange(cells[1].upper(), cells[2].upper(), d, cells[0] or None))
    return out


def _bse_row(r: dict, raw: dict, list_name: str, status: Optional[str]) -> Optional[ListingRow]:
    code = _pick(r, "SCRIPCD", "SECURITYCODE", "SCRIPCODE")
    if not code:
        return None
    code = code.split(".")[0]
    published = (_pick(r, "STATUS") or "").capitalize()
    group = _pick(r, "GROUP", "SCGROUP")
    return ListingRow(
        "BSE", list_name, code, status or BSE_STATUSES.get(published, "UNKNOWN"),
        "SME" if group in BSE_SME_GROUPS else ("MAINBOARD" if group else "UNKNOWN"), raw,
        ticker=_pick(r, "SCRIPID", "SECURITYID"), isin=_isin(_pick(r, "ISINNUMBER", "ISINNO", "ISIN")),
        name=_pick(r, "ISSUERNAME", "SCRIPNAME", "SECURITYNAME"), series=group,
        face_value=_num(_pick(r, "FACEVALUE")),
        industry=_pick(r, "INDUSTRYNEWNAME", "INDUSTRY", "SECTORNAME"))


def parse_bse(rows: list[dict], list_name: str, status: Optional[str] = None) -> list[ListingRow]:
    """BSE ListofScripData JSON rows, or Equity.csv rows (``status`` None: read each row's Status)."""
    out = []
    for r, raw in _normalised(rows):
        row = _bse_row(r, raw, list_name, status)
        if row:
            out.append(row)
    return out


def parse_file(body: bytes, exchange: str) -> list[ListingRow]:
    """A listing file downloaded by hand: NSE EQUITY_L / SME_EQUITY_L or BSE Equity.csv."""
    if exchange == "NSE":
        rows = parse_nse(body, "NSE_FILE", "UNKNOWN")
        return [replace(r, board="SME" if r.series in ("SM", "ST", "SZ") else "MAINBOARD") for r in rows]
    return parse_bse(csv_records(body), "BSE_FILE")


# ---------------------------------------------------------------- fetching

def _fetch_csv(client: HttpClient, exchange: str, list_name: str, url: str, parse) -> ListResult:
    before = client.requests
    result = ListResult(exchange, list_name, WindowStatus.FAILED)
    resp = client.get(url, referer=NSE_REFERER, accept=CSV_ACCEPT)
    if resp.ok:
        result.files.append((url, resp.body))
        try:
            result.rows = parse(resp.body)
        except (ValueError, csv.Error) as exc:
            result.status = WindowStatus.BLOCKED if "HTML" in str(exc) else WindowStatus.FAILED
            result.notes.append(f"unreadable: {exc}")
        else:
            result.status = WindowStatus.COMPLETE if result.rows else WindowStatus.EMPTY_UNVERIFIED
            if not result.rows:
                result.notes.append("no rows")
    elif resp.blocked:
        result.status = WindowStatus.BLOCKED
        result.notes.append(f"HTTP {resp.status}")
    else:
        result.notes.append(resp.error or f"HTTP {resp.status}")
    result.requests = client.requests - before
    return result


def fetch_nse(client: HttpClient) -> list[ListResult]:
    return [
        _fetch_csv(client, "NSE", "NSE_EQUITY_L", NSE_EQUITY_URL, lambda b: parse_nse(b, "NSE_EQUITY_L", "MAINBOARD")),
        _fetch_csv(client, "NSE", "NSE_SME_EQUITY_L", NSE_SME_URL, lambda b: parse_nse(b, "NSE_SME_EQUITY_L", "SME")),
        _fetch_csv(client, "NSE", "NSE_SYMBOL_CHANGES", NSE_SYMBOL_CHANGE_URL, parse_symbol_changes),
    ]


def fetch_bse(client: HttpClient) -> list[ListResult]:
    out = []
    for published, status in BSE_STATUSES.items():
        list_name = f"BSE_{status}"
        before = client.requests
        q = urlencode({"Group": "", "Scripcode": "", "industry": "", "segment": "Equity", "status": published})
        url = f"{BSE_SCRIPS_URL}?{q}"
        st, data, note = decode_json(client.get(url, referer=BSE_REFERER))
        result = ListResult("BSE", list_name, st, notes=[note] if note else [])
        if st == WindowStatus.COMPLETE:
            items = data if isinstance(data, list) else ((data or {}).get("Table") or [])
            result.rows = parse_bse([i for i in items if isinstance(i, dict)], list_name, status)
            if not result.rows:
                result.status = WindowStatus.EMPTY_UNVERIFIED
                result.notes.append("no rows")
        result.requests = client.requests - before
        out.append(result)
    return out
