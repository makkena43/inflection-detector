"""Exchange adapters and download, ported from MakroGraph (b31bdd0) fetcher/nse_fetcher.py,
fetcher/bse_fetcher.py and run_pdf_fetch_india.  No network: a fake transport replays canned
responses shaped like the exchanges' JSON.  Cases marked "ported" keep MakroGraph's behaviour;
the rest cover the defects fixed in the port (spec section 15 test 11)."""

import io
import json
import zipfile
from datetime import date, datetime

import pytest

from inflection.sources import bse, nse
from inflection.sources.common import IST, WindowStatus
from inflection.sources.download import Archive, DownloadStatus, download
from inflection.sources.http import HttpClient
from inflection.states import PublicationBasis
from pdf_fixtures import make_pdf


class FakeTransport:
    """Routes by URL substring; each route is a list of (status, body) consumed in order (last repeats)."""

    def __init__(self, routes):
        self.routes = {k: list(v) for k, v in routes.items()}
        self.calls = []

    def __call__(self, url, headers, timeout):
        self.calls.append(url)
        for key, replies in self.routes.items():
            if key in url:
                reply = replies.pop(0) if len(replies) > 1 else replies[0]
                if isinstance(reply, Exception):
                    raise reply
                status, body = reply
                return status, body if isinstance(body, bytes) else json.dumps(body).encode()
        return 404, b""


def client(routes):
    t = FakeTransport(routes)
    return HttpClient(min_interval=0, backoff=0, transport=t, sleep=lambda s: None), t


NSE_ROW = {"seq_id": "112233", "symbol": "abc", "sm_name": "ABC Ltd", "desc": "Outcome of Board Meeting",
           "attchmntText": "Financial results for the quarter", "an_dt": "08-Oct-2026 15:10:22",
           "attchmntFile": "https://nsearchives.nseindia.com/corporate/ABC_08102026151022_Outcome.pdf",
           "smIndustry": "Capital Goods"}


# ---------------- NSE ----------------

def test_nse_month_chunks():  # ported (docstring example of _generate_month_chunks)
    assert nse.month_chunks(date(2020, 1, 1), date(2020, 3, 15)) == [
        (date(2020, 1, 1), date(2020, 1, 31)), (date(2020, 2, 1), date(2020, 2, 29)),
        (date(2020, 3, 1), date(2020, 3, 15))]
    assert nse.month_chunks(date(2026, 12, 20), date(2027, 1, 5))[-1] == (date(2027, 1, 1), date(2027, 1, 5))


def test_nse_attachment_url_forms():  # ported, plus "-" meaning no attachment
    assert nse.attachment_url({"attchmntFile": "x.pdf"}) == \
        "https://nsearchives.nseindia.com/corporate/ANNOUNCEMENTS/x.pdf"
    assert nse.attachment_url({"attchmntFile": "/a/b.pdf"}) == "https://www.nseindia.com/a/b.pdf"
    assert nse.attachment_url({"attchmntFile": "-"}) == ""


def test_nse_time_is_ist_not_utc():
    a = nse.parse_item(NSE_ROW, "equities")
    assert a.published_at == datetime(2026, 10, 8, 15, 10, 22, tzinfo=IST)
    assert a.published_at.utcoffset().total_seconds() == 5.5 * 3600
    assert a.publication_basis == PublicationBasis.EXCHANGE_TIMESTAMP
    assert (a.symbol, a.category, a.issuer_name) == ("ABC", "Outcome of Board Meeting", "ABC Ltd")


def test_nse_date_only_and_missing_time():
    d = nse.parse_item({**NSE_ROW, "an_dt": "08-Oct-2026"}, "sme")
    assert d.publication_basis == PublicationBasis.DATE_ONLY and d.published_at is None
    assert d.published_date == date(2026, 10, 8)
    u = nse.parse_item({**NSE_ROW, "an_dt": ""}, "sme")
    assert u.publication_basis == PublicationBasis.UNKNOWN


def test_nse_window_keeps_every_category_and_dedups():
    rows = [NSE_ROW, {**NSE_ROW, "seq_id": "2", "desc": "Trading Window"}, NSE_ROW]
    c, t = client({"corporate-announcements": [(200, rows)], "nseindia.com": [(200, b"<html>")]})
    w = nse.NSEAnnouncements(c).list_window(date(2026, 10, 8), date(2026, 10, 8), "sme")
    assert w.status == WindowStatus.COMPLETE
    assert [a.exchange_id for a in w.announcements] == ["112233", "2"]   # compliance noise not dropped
    assert "index=sme" in t.calls[-1] and "from_date=08-10-2026" in t.calls[-1]
    assert w.requests == 3                                                # two warm-up pages + one listing


@pytest.mark.parametrize("reply,status", [
    ((200, []), WindowStatus.EMPTY_UNVERIFIED),
    ((200, b""), WindowStatus.EMPTY_UNVERIFIED),
    ((403, b""), WindowStatus.BLOCKED),
    ((200, b"<html>Access Denied</html>"), WindowStatus.BLOCKED),
    ((503, b""), WindowStatus.FAILED),
])
def test_nse_empty_or_blocked_is_never_complete(reply, status):
    c, t = client({"corporate-announcements": [reply], "nseindia.com": [(200, b"")]})
    w = nse.NSEAnnouncements(c).list_window(date(2026, 10, 8), date(2026, 10, 8))
    assert w.status == status and w.announcements == []


def test_blocked_is_not_retried_but_5xx_is():
    c, t = client({"corporate-announcements": [(403, b"")], "nseindia.com": [(200, b"")]})
    nse.NSEAnnouncements(c).list_window(date(2026, 10, 8), date(2026, 10, 8))
    assert sum("corporate-announcements" in u for u in t.calls) == 1
    c, t = client({"corporate-announcements": [(502, b""), OSError("reset"), (200, [NSE_ROW])],
                   "nseindia.com": [(200, b"")]})
    w = nse.NSEAnnouncements(c).list_window(date(2026, 10, 8), date(2026, 10, 8))
    assert w.status == WindowStatus.COMPLETE and sum("corporate-announcements" in u for u in t.calls) == 3


# ---------------- BSE ----------------

def bse_row(i, cat="Result"):
    return {"NEWSID": f"n{i}", "SCRIP_CD": 543210, "SLONGNAME": "XYZ Ltd", "CATEGORYNAME": cat,
            "SUBCATNAME": "Financial Results", "NEWSSUB": "XYZ Ltd - Results",
            "NEWS_DT": "2026-10-08T15:10:22.137", "DissemDT": "2026-10-08T15:10:25.5",
            "ATTACHMENTNAME": "692815d2-2636-4325-babd-6c405e98eb88.pdf"}


def test_bse_attachment_url_forms():  # ported
    u = "692815d2-2636-4325-babd-6c405e98eb88"
    assert bse.attachment_url(u + ".pdf") == f"{bse.ATTACH_LIVE}/{u}.pdf"
    assert bse.attachment_url(u.upper()) == f"{bse.ATTACH_LIVE}/{u}.pdf"
    assert bse.attachment_url("Attachments/old.pdf") == f"{bse.ATTACH_HIS}/Attachments/old.pdf"


def test_bse_pm_time_and_dissemination_preferred():
    a = bse.parse_item({**bse_row(1), "DissemDT": "10/08/2026 03:10:25 PM"})
    assert a.published_at == datetime(2026, 10, 8, 15, 10, 25, tzinfo=IST)   # MakroGraph read 03:10 UTC
    b = bse.parse_item({**bse_row(1), "DissemDT": ""})
    assert b.published_at == datetime(2026, 10, 8, 15, 10, 22, 137000, tzinfo=IST)


def test_bse_all_category_query_follows_pages():
    pages = [(200, {"Table": [bse_row(i) for i in range(50)], "Table1": [{"ROWCNT": 120}]}),
             (200, {"Table": [bse_row(i) for i in range(50, 100)], "Table1": [{"ROWCNT": 120}]}),
             (200, {"Table": [bse_row(i) for i in range(100, 120)], "Table1": [{"ROWCNT": 120}]})]
    c, t = client({"AnnSubCategoryGetData": pages})
    w = bse.BSEAnnouncements(c).list_window(date(2026, 10, 8), date(2026, 10, 8))
    assert w.status == WindowStatus.COMPLETE and len(w.announcements) == 120
    assert [("pageno=%d" % p) in u for p, u in zip((1, 2, 3), t.calls)] == [True, True, True]


def test_bse_page_cap_is_truncated_not_silent():
    full = (200, {"Table": [bse_row(i) for i in range(50)], "Table1": [{"ROWCNT": 500}]})
    c, _ = client({"AnnSubCategoryGetData": [full]})
    w = bse.BSEAnnouncements(c, max_pages=2).list_window(date(2026, 10, 8), date(2026, 10, 8))
    assert w.status == WindowStatus.TRUNCATED and any("stopped at 2 pages" in n for n in w.notes)


def test_bse_category_sweep_is_partial():
    c, t = client({"strCat=-1": [(200, b"")], "strCat=Result": [(200, {"Table": [bse_row(1)]})],
                   "AnnSubCategoryGetData": [(200, {"Table": []})]})
    w = bse.BSEAnnouncements(c).list_window(date(2026, 10, 8), date(2026, 10, 8))
    assert w.status == WindowStatus.PARTIAL and len(w.announcements) == 1
    assert any("category subset" in n for n in w.notes)
    assert len(t.calls) == 1 + len(bse.CATEGORIES)


def test_bse_everything_blocked():
    c, _ = client({"AnnSubCategoryGetData": [(403, b"")]})
    w = bse.BSEAnnouncements(c).list_window(date(2026, 10, 8), date(2026, 10, 8))
    assert w.status == WindowStatus.BLOCKED and w.announcements == []


# ---------------- download ----------------

def zip_of(members):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, data in members.items():
            z.writestr(name, data)
    return buf.getvalue()


@pytest.fixture
def pdf_bytes(tmp_path):
    p = make_pdf(tmp_path / "f.pdf", ["Revenue from operations 100"])
    return p.read_bytes()


def test_bse_attachlive_404_falls_back_to_attachhis(tmp_path, pdf_bytes):  # ported
    url = f"{bse.ATTACH_LIVE}/692815d2-2636-4325-babd-6c405e98eb88.pdf"
    c, t = client({"AttachLive": [(404, b"")], "AttachHis": [(200, pdf_bytes)]})
    d = download(url, Archive(tmp_path / "a"), c)
    assert d.status == DownloadStatus.OK and "AttachHis" in d.final_url
    assert d.pdfs[0].path.read_bytes() == pdf_bytes and d.original.sha256 == d.pdfs[0].sha256


def test_zip_keeps_every_pdf_and_the_original(tmp_path, pdf_bytes):
    z = zip_of({"a.pdf": pdf_bytes, "b.PDF": pdf_bytes + b"\n%x", "c.xlsx": b"xx"})
    c, _ = client({"nsearchives": [(200, z)]})
    d = download("https://nsearchives.nseindia.com/corporate/x.zip", Archive(tmp_path), c)
    assert d.status == DownloadStatus.OK and [p.name for p in d.pdfs] == ["a.pdf", "b.PDF"]
    assert d.original.path.read_bytes() == z and "c.xlsx" in d.note


@pytest.mark.parametrize("reply,status", [
    ((200, b""), DownloadStatus.EMPTY),
    ((403, b""), DownloadStatus.BLOCKED),
    ((404, b""), DownloadStatus.NOT_FOUND),
    ((200, b"<!DOCTYPE html><html>denied</html>"), DownloadStatus.BLOCKED),
    ((200, b"GIF89a...."), DownloadStatus.UNSUPPORTED_FORMAT),
])
def test_download_failures_are_explicit(tmp_path, reply, status):
    c, _ = client({"nsearchives": [reply]})
    assert download("https://nsearchives.nseindia.com/x.pdf", Archive(tmp_path), c).status == status


def test_zip_without_pdf(tmp_path):
    c, _ = client({"nsearchives": [(200, zip_of({"a.xml": b"<x/>"}))]})
    d = download("https://nsearchives.nseindia.com/x.zip", Archive(tmp_path), c)
    assert d.status == DownloadStatus.ZIP_NO_PDF and d.original is not None


def test_archive_is_idempotent(tmp_path):
    a = Archive(tmp_path)
    first, second = a.put(b"same", "x"), a.put(b"same", "y")
    assert first.path == second.path and len(list(tmp_path.rglob("*"))) == 2   # one dir, one file
