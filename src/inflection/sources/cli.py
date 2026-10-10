"""Live check of the exchange adapters.  Prints a coverage line per window; nothing is written to the DB.

    python -m inflection.sources.cli nse 2026-10-08 [--to 2026-10-08] [--segment sme] [--download DIR] [--limit 3]
    python -m inflection.sources.cli bse 2026-10-08 [--download DIR]
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import date
from pathlib import Path

from .bse import REFERER as BSE_REFERER, BSEAnnouncements
from .download import Archive, download
from .http import HttpClient, Transport, curl_cffi_transport
from .nse import REFERER as NSE_REFERER, NSEAnnouncements


def _bse_transport() -> Transport | None:
    """BSE's Akamai edge rejects urllib; use a browser fingerprint when curl_cffi is installed."""
    try:
        return curl_cffi_transport()
    except ImportError:
        print("note: curl_cffi not installed; BSE usually blocks plain urllib (HTTP 403)")
        return None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m inflection.sources.cli")
    ap.add_argument("exchange", choices=("nse", "bse"))
    ap.add_argument("start", type=date.fromisoformat)
    ap.add_argument("--to", type=date.fromisoformat)
    ap.add_argument("--segment", default="equities", choices=("equities", "sme"), help="NSE only")
    ap.add_argument("--download", type=Path, help="archive directory for attachments")
    ap.add_argument("--limit", type=int, default=3, help="attachments to download")
    ap.add_argument("--interval", type=float, default=1.5, help="seconds between requests")
    a = ap.parse_args(argv)

    client = HttpClient(min_interval=a.interval,
                        transport=_bse_transport() if a.exchange == "bse" else None)
    end = a.to or a.start
    if a.exchange == "nse":
        windows, referer = NSEAnnouncements(client).list_range(a.start, end, a.segment), NSE_REFERER
    else:
        windows, referer = BSEAnnouncements(client).list_range(a.start, end), BSE_REFERER

    rows = []
    for w in windows:
        print(f"{w.exchange} {w.segment} {w.from_date}..{w.to_date}: {w.status.value}, "
              f"{len(w.announcements)} rows, {w.requests} requests")
        for n in w.notes:
            print("   note:", n)
        rows += w.announcements
    if rows:
        print("publication basis:", dict(Counter(r.publication_basis.value for r in rows)))
        print("with attachment:", sum(1 for r in rows if r.attachment_url), "of", len(rows))
        r = rows[0]
        print("sample:", r.exchange_id, r.symbol, r.category, "|", r.raw_time, "->", r.published_at,
              "|", r.attachment_url)
    if a.download and rows:
        archive = Archive(a.download)
        for r in [r for r in rows if r.attachment_url][: a.limit]:
            d = download(r.attachment_url, archive, client, referer=referer)
            print("download:", d.status.value, d.http_status, d.final_url,
                  [f"{p.name} {p.size}B" for p in d.pdfs], d.note)
    print("total requests:", client.requests)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
