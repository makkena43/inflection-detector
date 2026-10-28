"""Phase 1 slice: listing windows -> publications -> archive -> page text -> coverage (real PostgreSQL,
fake exchange transport).  Covers spec section 14 Phase 1 acceptance: duplicate NSE/BSE copies share one
document lineage, outages are visible, pages are accounted for, unknown dates stay unknown, reruns are
idempotent."""

from datetime import date, datetime

from inflection import ingest
from inflection.sources import bse, nse
from inflection.sources.common import IST, WindowStatus
from inflection.sources.download import Archive
from inflection.states import CoverageStatus
from pdf_fixtures import make_pdf
from test_sources import NSE_ROW, bse_row, client, zip_of

DAY = date(2026, 10, 8)


def nse_window(rows, reply=None):
    c, _ = client({"corporate-announcements": [reply or (200, rows)], "nseindia.com": [(200, b"")]})
    return nse.NSEAnnouncements(c).list_window(DAY, DAY)


def nse_row(i, url):
    return {**NSE_ROW, "seq_id": str(i), "attchmntFile": url}


def test_window_statuses_are_coverage_statuses():
    assert {s.value for s in WindowStatus} <= {s.value for s in CoverageStatus}


def test_record_window_is_idempotent_and_keeps_publication_time(db):
    rows = [nse_row(1, "https://x/a.pdf"), {**nse_row(2, "-"), "an_dt": "08-Oct-2026"}]
    first = ingest.record_window(db, nse_window(rows))
    seen = db.execute("SELECT first_seen_at FROM document_publications WHERE external_id = '1'").fetchone()[0]
    second = ingest.record_window(db, nse_window(rows))
    assert (first.inserted, second.inserted, second.received) == (2, 0, 2)
    assert db.execute("SELECT count(*) FROM ingestion_runs").fetchone()[0] == 2
    p1 = db.execute("SELECT published_at, published_date, publication_basis, first_seen_at, raw_time, "
                    "raw_metadata->>'_symbol', pipeline_state FROM document_publications "
                    "WHERE external_id = '1'").fetchone()
    assert p1[0] == datetime(2026, 10, 8, 15, 10, 22, tzinfo=IST) and p1[1] is None
    assert p1[2:] == ("EXCHANGE_TIMESTAMP", seen, "08-Oct-2026 15:10:22", "ABC", "DISCOVERED")
    p2 = db.execute("SELECT published_at, published_date, publication_basis, attachment_url, source_url "
                    "FROM document_publications WHERE external_id = '2'").fetchone()
    assert p2[:4] == (None, DAY, "DATE_ONLY", None) and p2[4] == nse.ANNOUNCEMENTS_URL


def test_blocked_window_is_recorded_not_silent(db):
    r = ingest.record_window(db, nse_window([], reply=(403, b"")))
    assert r.coverage_status == CoverageStatus.BLOCKED
    row = db.execute("SELECT coverage_status, error_class, received_count, reconciliation_result->'notes' "
                     "FROM ingestion_runs").fetchone()
    assert row[:3] == ("BLOCKED", "BLOCKED", 0) and row[3] == ["HTTP 403"]
    rep = ingest.coverage_report(db, DAY, DAY)
    assert rep["windows"] == [dict(source="nse_announcements", segment="equities", status="BLOCKED",
                                   windows=1, rows=0)]


def test_download_states_and_retry(db, tmp_path):
    pdf = make_pdf(tmp_path / "f.pdf", ["Revenue from operations 100"]).read_bytes()
    ingest.record_window(db, nse_window([nse_row(1, "https://h/ok.pdf"), nse_row(2, "https://h/gone.pdf"),
                                         nse_row(3, "https://h/blocked.pdf")]))
    archive = Archive(tmp_path / "archive")
    c, _ = client({"ok.pdf": [(200, pdf)], "gone.pdf": [(404, b"")], "blocked.pdf": [(403, b"")]})
    assert ingest.download_pending(db, archive, c) == {"OK": 1, "NOT_FOUND": 1, "BLOCKED": 1}
    states = dict(db.execute("SELECT external_id, pipeline_state || ' ' || coalesce(failure_reason, '') "
                             "FROM document_publications").fetchall())
    assert states["1"] == "DOWNLOADED " and states["2"].startswith("FAILED NOT_FOUND")
    assert states["3"].startswith("FAILED BLOCKED")
    v = db.execute("SELECT v.media_type, v.storage_key, p.response_sha256 = v.sha256 FROM document_publications p "
                   "JOIN document_versions v USING (document_version_id)").fetchone()
    assert v[0] == "application/pdf" and (archive.root / v[1]).read_bytes() == pdf and v[2]

    assert ingest.download_pending(db, archive, c) == {}                       # nothing new
    c2, t2 = client({"blocked.pdf": [(200, pdf)], "gone.pdf": [(200, pdf)]})
    assert ingest.download_pending(db, archive, c2, retry_failed=True) == {"OK": 1}
    assert not any("gone.pdf" in u for u in t2.calls)                          # 404 is not retried


def test_same_bytes_on_nse_and_bse_share_one_document(db, tmp_path):
    pdf = make_pdf(tmp_path / "f.pdf", ["Order win of Rs 120 crore"]).read_bytes()
    ingest.record_window(db, nse_window([nse_row(1, "https://nsearchives.nseindia.com/x.pdf")]))
    c, _ = client({"AnnSubCategoryGetData": [(200, {"Table": [bse_row(1)], "Table1": [{"ROWCNT": 1}]})]})
    ingest.record_window(db, bse.BSEAnnouncements(c).list_window(DAY, DAY))
    dl, _ = client({"nsearchives": [(200, pdf)], "AttachLive": [(200, pdf)]})
    assert ingest.download_pending(db, Archive(tmp_path / "a"), dl) == {"OK": 2}
    assert db.execute("SELECT count(DISTINCT v.document_id), count(DISTINCT p.source_id) FROM document_publications p "
                      "JOIN document_versions v USING (document_version_id)").fetchone() == (1, 2)


def test_extract_text_states(db, tmp_path):
    full = make_pdf(tmp_path / "a.pdf", ["Capacity utilisation rose to 85%"]).read_bytes()
    gap = make_pdf(tmp_path / "b.pdf", ["Page one text", ""]).read_bytes()
    two = zip_of({"x.pdf": full, "y.pdf": make_pdf(tmp_path / "c.pdf", ["Second annexure"]).read_bytes()})
    nopdf = zip_of({"a.xml": b"<x/>"})
    ingest.record_window(db, nse_window([nse_row(i, f"https://h/{n}") for i, n in
                                         enumerate(["full.pdf", "gap.pdf", "two.zip", "nopdf.zip"], 1)]))
    archive = Archive(tmp_path / "archive")
    c, _ = client({"full.pdf": [(200, full)], "gap.pdf": [(200, gap)], "two.zip": [(200, two)],
                   "nopdf.zip": [(200, nopdf)]})
    assert ingest.download_pending(db, archive, c) == {"OK": 3, "ZIP_NO_PDF": 1}
    assert ingest.extract_pending(db, archive) == {"TEXT_READY": 2, "PARTIAL_TEXT": 1, "FAILED": 1}
    assert ingest.extract_pending(db, archive) == {}                           # rerun does nothing
    states = dict(db.execute("SELECT external_id, pipeline_state FROM document_publications").fetchall())
    assert states == {"1": "TEXT_READY", "2": "PARTIAL_TEXT", "3": "TEXT_READY", "4": "FAILED"}
    assert db.execute("SELECT missing_pages FROM text_artifacts WHERE status = 'PARTIAL'").fetchone()[0] == [2]
    assert db.execute("SELECT count(*) FROM text_artifacts").fetchone()[0] == 4        # zip members each read
    hit = db.execute("SELECT page_no FROM text_pages WHERE tsv @@ plainto_tsquery('english', 'capacity utilisation')"
                     ).fetchall()
    assert hit and all(p == (1,) for p in hit)
    rep = {(r["state"]): r["count"] for r in ingest.coverage_report(db, DAY, DAY)["publications"]}
    assert rep == {"TEXT_READY": 2, "PARTIAL_TEXT": 1, "FAILED": 1}


def test_download_retry_limit_excludes_terminal_failures_and_honors_dates(db,tmp_path):
    from inflection import financials
    old=nse_row(1,'https://h/terminal.pdf');new=nse_row(2,'https://h/current.pdf')
    ingest.record_window(db,nse_window([old,new]))
    db.execute("UPDATE document_publications SET pipeline_state='FAILED',failure_reason='NOT_FOUND: HTTP 404' WHERE external_id='1'")
    pdf=make_pdf(tmp_path/'current.pdf',['Useful text']).read_bytes()
    dl,t=client({'current.pdf':[(200,pdf)]})
    out=ingest.download_pending(db,Archive(tmp_path/'archive'),dl,limit=1,retry_failed=True,start=DAY,end=DAY)
    assert out=={'OK':1} and len(t.calls)==1
    # No results-source publication may enter the announcement downloader.
    src=financials.ensure_source(db)
    db.execute("INSERT INTO document_publications(source_id,external_id,source_url,attachment_url,published_at,publication_basis) VALUES(%s,'native','https://h/native.xml','https://h/native.xml',%s,'EXCHANGE_TIMESTAMP')",(src,datetime(2026,10,8,15,tzinfo=IST)))
    assert ingest.download_pending(db,Archive(tmp_path/'archive'),dl)=={}
    assert ingest.extract_pending(db,Archive(tmp_path/'archive'),start=date(2026,10,9),end=date(2026,10,9))=={}
    assert ingest.extract_pending(db,Archive(tmp_path/'archive'),start=DAY,end=DAY)=={'TEXT_READY':1}


def test_cached_text_survives_a_purged_archive(db,tmp_path,monkeypatch):
    from inflection.text_extraction import extraction_version
    import inflection.ingest as I
    doc=db.execute('INSERT INTO documents DEFAULT VALUES RETURNING document_id').fetchone()[0]
    vid=db.execute("INSERT INTO document_versions(document_id,sha256,storage_key,byte_size,media_type) VALUES(%s,%s,'purged',1,'application/pdf') RETURNING document_version_id",(doc,'c'*64)).fetchone()[0]
    db.execute("INSERT INTO text_artifacts(document_version_id,extraction_method,extraction_version,status) VALUES(%s,'pdfplumber',%s,'COMPLETE')",(vid,extraction_version()))
    def unexpected(*args):raise AssertionError('cached PDF was parsed again')
    monkeypatch.setattr(I,'extract_pdf',unexpected)
    assert I._artifact(db,vid,tmp_path/'missing.pdf').value=='COMPLETE'
