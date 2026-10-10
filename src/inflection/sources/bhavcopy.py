"""Daily NSE / BSE equity bhavcopy (end-of-day prices per instrument).

Ported from MakroGraph ``fetcher/nse_price_fetcher.py`` and ``fetcher/bse_price_fetcher.py`` at
b31bdd0 (see docs/reuse_inventory.md): the file URLs and the column mappings.  Differences:

* stdlib ``csv`` and the shared rate-limited ``HttpClient`` instead of pandas, requests and the
  ``nse`` package;
* NSE is read from two files and merged: the UDiFF ``BhavCopy_NSE_CM`` file (ISIN, company name,
  every series) and MakroGraph's ``sec_bhavdata_full`` (delivery quantity and average price).
  MakroGraph read only the second, which has no ISIN, and kept one series per symbol;
* when a UDiFF file does not exist (before July 2024) the older ISIN-bearing files are tried:
  NSE ``cmDDMONYYYYbhav.csv.zip`` and BSE ``EQ_ISINCODE_DDMMYY.zip``;
* BSE rows are keyed on the scrip code.  MakroGraph keyed them on the ticker for UDiFF files and on
  the scrip code for older files, so one company had two keys;
* a missing value stays missing.  MakroGraph filled absent BSE columns with 0;
* turnover is in rupees for every format (``sec_bhavdata_full`` reports lakhs);
* a day with no file is EMPTY_UNVERIFIED (holiday or not yet published) and a 401/403/429 is
  BLOCKED, never "no rows".
"""

from __future__ import annotations

import csv
import io
import zipfile
from dataclasses import dataclass, field, fields, replace
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Callable, Iterable, Optional

from .common import WindowStatus
from .http import HttpClient, Response

NSE_UDIFF_URL = "https://nsearchives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_0_0_{ymd}_F_0000.csv.zip"
NSE_LEGACY_URL = ("https://nsearchives.nseindia.com/content/historical/EQUITIES/{yyyy}/{mon}/"
                  "cm{dd}{mon}{yyyy}bhav.csv.zip")
NSE_FULL_URL = "https://archives.nseindia.com/products/content/sec_bhavdata_full_{dmy}.csv"
NSE_REFERER = "https://www.nseindia.com/"
BSE_UDIFF_URL = "https://www.bseindia.com/download/BhavCopy/Equity/BhavCopy_BSE_CM_0_0_0_{ymd}_F_0000.CSV"
BSE_LEGACY_URL = "https://www.bseindia.com/download/BhavCopy/Equity/EQ_ISINCODE_{dmy2}.zip"
BSE_REFERER = "https://www.bseindia.com/"
ACCEPT = "text/csv, application/zip, application/octet-stream, */*"
LAKH = Decimal(100000)


@dataclass(frozen=True)
class PriceRow:
    exchange: str                   # "NSE" | "BSE"
    trade_date: date
    code: str                       # NSE symbol / BSE scrip code
    series: str = ""                # NSE series / BSE group
    ticker: Optional[str] = None    # BSE ticker symbol
    isin: Optional[str] = None
    instrument_name: Optional[str] = None
    instrument_type: Optional[str] = None
    prev_close: Optional[Decimal] = None
    open: Optional[Decimal] = None
    high: Optional[Decimal] = None
    low: Optional[Decimal] = None
    last: Optional[Decimal] = None
    close: Optional[Decimal] = None
    avg_price: Optional[Decimal] = None
    volume: Optional[Decimal] = None
    turnover: Optional[Decimal] = None      # rupees
    trades: Optional[int] = None
    delivery_qty: Optional[Decimal] = None
    delivery_pct: Optional[Decimal] = None
    source_formats: tuple[str, ...] = ()

    @property
    def key(self) -> tuple:
        return self.exchange, self.trade_date, self.code, self.series


VALUE_FIELDS = [f.name for f in fields(PriceRow) if f.name not in ("exchange", "trade_date", "code", "series",
                                                                    "source_formats")]


@dataclass
class DayResult:
    exchange: str
    trade_date: date
    status: WindowStatus
    rows: list[PriceRow] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    files: list[tuple[str, bytes]] = field(default_factory=list)   # (url, raw bytes) as received
    requests: int = 0


# ---------------------------------------------------------------- parsing

def _num(v) -> Optional[Decimal]:
    s = (v or "").strip().replace(",", "")
    if s in ("", "-", "NA", "nan"):
        return None
    try:
        return Decimal(s)
    except InvalidOperation:
        return None


def _int(v) -> Optional[int]:
    n = _num(v)
    return int(n) if n is not None else None


def _text(v) -> Optional[str]:
    s = (v or "").strip()
    return s or None


def _isin(v) -> Optional[str]:
    s = (v or "").strip().upper()
    return s if len(s) == 12 and s[:2].isalpha() and s[-1].isdigit() else None


def csv_records(body: bytes) -> list[dict]:
    """Rows of a CSV file, or of the first CSV inside a ZIP.  Keys and values are stripped."""
    if body[:4] == b"PK\x03\x04":
        with zipfile.ZipFile(io.BytesIO(body)) as z:
            names = [n for n in z.namelist() if n.lower().endswith(".csv")]
            if not names:
                raise ValueError("ZIP holds no CSV")
            body = z.read(names[0])
    text = body.decode("utf-8-sig", errors="replace")
    if text.lstrip()[:1] == "<":
        raise ValueError("HTML page instead of CSV")
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise ValueError("empty file")
    return [{(k or "").strip(): (v or "").strip() for k, v in r.items() if k is not None} for r in reader]


def _date(text: str, formats: Iterable[str]) -> Optional[date]:
    for f in formats:
        try:
            return datetime.strptime(text.strip(), f).date()
        except ValueError:
            continue
    return None


def parse_udiff(body: bytes, exchange: str, trade_date: date) -> list[PriceRow]:
    """NSE or BSE UDiFF cash-market bhavcopy (``BhavCopy_<EX>_CM_0_0_0_YYYYMMDD_F_0000``)."""
    fmt = f"{exchange}_UDIFF"
    out = []
    for r in csv_records(body):
        symbol, scrip = _text(r.get("TckrSymb")), _text(r.get("FinInstrmId"))
        code = symbol if exchange == "NSE" else scrip
        if not code:
            continue
        out.append(PriceRow(
            exchange, _date(r.get("TradDt", ""), ("%Y-%m-%d", "%d-%b-%Y")) or trade_date, code,
            series=r.get("SctySrs", ""), ticker=symbol if exchange == "BSE" else None, isin=_isin(r.get("ISIN")),
            instrument_name=_text(r.get("FinInstrmNm")), instrument_type=_text(r.get("FinInstrmTp")),
            prev_close=_num(r.get("PrvsClsgPric")), open=_num(r.get("OpnPric")), high=_num(r.get("HghPric")),
            low=_num(r.get("LwPric")), last=_num(r.get("LastPric")), close=_num(r.get("ClsPric")),
            volume=_num(r.get("TtlTradgVol")), turnover=_num(r.get("TtlTrfVal")),
            trades=_int(r.get("TtlNbOfTxsExctd")), source_formats=(fmt,)))
    return out


def parse_nse_full(body: bytes, trade_date: date) -> list[PriceRow]:
    """NSE ``sec_bhavdata_full_DDMMYYYY.csv``: prices plus delivery.  Turnover is in lakhs."""
    out = []
    for r in csv_records(body):
        code = _text(r.get("SYMBOL"))
        if not code:
            continue
        lacs = _num(r.get("TURNOVER_LACS"))
        out.append(PriceRow(
            "NSE", _date(r.get("DATE1", ""), ("%d-%b-%Y",)) or trade_date, code, series=r.get("SERIES", ""),
            prev_close=_num(r.get("PREV_CLOSE")), open=_num(r.get("OPEN_PRICE")), high=_num(r.get("HIGH_PRICE")),
            low=_num(r.get("LOW_PRICE")), last=_num(r.get("LAST_PRICE")), close=_num(r.get("CLOSE_PRICE")),
            avg_price=_num(r.get("AVG_PRICE")), volume=_num(r.get("TTL_TRD_QNTY")),
            turnover=lacs * LAKH if lacs is not None else None, trades=_int(r.get("NO_OF_TRADES")),
            delivery_qty=_num(r.get("DELIV_QTY")), delivery_pct=_num(r.get("DELIV_PER")),
            source_formats=("NSE_FULL",)))
    return out


def parse_nse_legacy(body: bytes, trade_date: date) -> list[PriceRow]:
    """NSE ``cmDDMONYYYYbhav.csv`` (before UDiFF).  Turnover is in rupees."""
    out = []
    for r in csv_records(body):
        code = _text(r.get("SYMBOL"))
        if not code:
            continue
        out.append(PriceRow(
            "NSE", _date(r.get("TIMESTAMP", ""), ("%d-%b-%Y",)) or trade_date, code, series=r.get("SERIES", ""),
            isin=_isin(r.get("ISIN")), prev_close=_num(r.get("PREVCLOSE")), open=_num(r.get("OPEN")),
            high=_num(r.get("HIGH")), low=_num(r.get("LOW")), last=_num(r.get("LAST")), close=_num(r.get("CLOSE")),
            volume=_num(r.get("TOTTRDQTY")), turnover=_num(r.get("TOTTRDVAL")), trades=_int(r.get("TOTALTRADES")),
            source_formats=("NSE_LEGACY",)))
    return out


def parse_bse_legacy(body: bytes, trade_date: date) -> list[PriceRow]:
    """BSE ``EQ_ISINCODE_DDMMYY`` (before UDiFF); MakroGraph's old-format column names."""
    out = []
    for r in csv_records(body):
        code = _text(r.get("SC_CODE") or r.get("SECURITY CODE"))
        if not code:
            continue
        out.append(PriceRow(
            "BSE", trade_date, code, series=r.get("SC_GROUP", ""), isin=_isin(r.get("ISIN_CODE")),
            instrument_name=_text(r.get("SC_NAME")), instrument_type=_text(r.get("SC_TYPE")),
            prev_close=_num(r.get("PREVCLOSE")), open=_num(r.get("OPEN")), high=_num(r.get("HIGH")),
            low=_num(r.get("LOW")), last=_num(r.get("LAST")), close=_num(r.get("CLOSE")),
            volume=_num(r.get("NO_OF_SHRS")), turnover=_num(r.get("NET_TURNOV")), trades=_int(r.get("NO_TRADES")),
            source_formats=("BSE_LEGACY",)))
    return out


def merge(primary: list[PriceRow], extra: list[PriceRow]) -> list[PriceRow]:
    """Rows keyed on (exchange, date, code, series).  ``primary`` values win; ``extra`` fills gaps."""
    by_key = {r.key: r for r in primary}
    for e in extra:
        p = by_key.get(e.key)
        if p is None:
            by_key[e.key] = e
            continue
        filled = {f: getattr(e, f) for f in VALUE_FIELDS if getattr(p, f) is None and getattr(e, f) is not None}
        by_key[e.key] = replace(p, **filled, source_formats=tuple(dict.fromkeys(p.source_formats + e.source_formats)))
    return list(by_key.values())


# ---------------------------------------------------------------- fetching

@dataclass
class _Part:
    label: str
    response: Response
    rows: list[PriceRow] = field(default_factory=list)
    error: str = ""

    @property
    def missing(self) -> bool:
        return self.response.status == 404


def _get(client: HttpClient, label: str, url: str, referer: str, parse: Callable[[bytes], list[PriceRow]],
         result: DayResult) -> _Part:
    resp = client.get(url, referer=referer, accept=ACCEPT)
    part = _Part(label, resp)
    if resp.ok:
        result.files.append((url, resp.body))
        try:
            part.rows = parse(resp.body)
        except (ValueError, zipfile.BadZipFile, csv.Error) as exc:
            part.error = f"{label}: unreadable ({exc})"
        else:
            if not part.rows:
                part.error = f"{label}: no rows"
    elif resp.status is None:
        part.error = f"{label}: {resp.error}"
    else:
        part.error = f"{label}: HTTP {resp.status}"
    return part


def _status(parts: list[_Part], rows: list[PriceRow]) -> WindowStatus:
    if rows:
        return WindowStatus.COMPLETE if all(p.rows for p in parts) else WindowStatus.PARTIAL
    if any(p.response.blocked for p in parts):
        return WindowStatus.BLOCKED
    if all(p.missing for p in parts):
        return WindowStatus.EMPTY_UNVERIFIED
    return WindowStatus.FAILED


def _first_available(client, candidates, referer, result) -> _Part:
    """Try file formats newest first; a 404 moves on to the older format."""
    part = None
    for label, url, parse in candidates:
        part = _get(client, label, url, referer, parse, result)
        if not part.missing:
            return part
    return part


def fetch_nse(client: HttpClient, d: date) -> DayResult:
    result = DayResult("NSE", d, WindowStatus.FAILED)
    before = client.requests
    mon = d.strftime("%b").upper()
    main = _first_available(client, [
        ("NSE_UDIFF", NSE_UDIFF_URL.format(ymd=d.strftime("%Y%m%d")), lambda b: parse_udiff(b, "NSE", d)),
        ("NSE_LEGACY", NSE_LEGACY_URL.format(yyyy=d.year, mon=mon, dd=d.strftime("%d")),
         lambda b: parse_nse_legacy(b, d)),
    ], NSE_REFERER, result)
    full = _get(client, "NSE_FULL", NSE_FULL_URL.format(dmy=d.strftime("%d%m%Y")), NSE_REFERER,
                lambda b: parse_nse_full(b, d), result)
    result.rows = merge(main.rows, full.rows)
    result.status = _status([main, full], result.rows)
    result.notes = [p.error for p in (main, full) if p.error]
    result.requests = client.requests - before
    return result


def fetch_bse(client: HttpClient, d: date) -> DayResult:
    result = DayResult("BSE", d, WindowStatus.FAILED)
    before = client.requests
    part = _first_available(client, [
        ("BSE_UDIFF", BSE_UDIFF_URL.format(ymd=d.strftime("%Y%m%d")), lambda b: parse_udiff(b, "BSE", d)),
        ("BSE_LEGACY", BSE_LEGACY_URL.format(dmy2=d.strftime("%d%m%y")), lambda b: parse_bse_legacy(b, d)),
    ], BSE_REFERER, result)
    result.rows = merge(part.rows, [])
    result.status = _status([part], result.rows)
    result.notes = [part.error] if part.error else []
    result.requests = client.requests - before
    return result


FETCHERS = {"NSE": fetch_nse, "BSE": fetch_bse}


def weekdays(start: date, end: date) -> list[date]:
    """Trading-day candidates.  Weekends are skipped; holidays come back EMPTY_UNVERIFIED."""
    days, d = [], start
    while d <= end:
        if d.weekday() < 5:
            days.append(d)
        d += timedelta(days=1)
    return days
