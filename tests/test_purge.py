"""Archive purge: only fully read bytes go, oldest filings first, and every deletion is recorded."""

from inflection import ingest
from inflection.purge import archive_bytes, purge_archive
from inflection.sources.download import Archive, sha256
from pdf_fixtures import make_pdf
from test_ingest import nse_row, nse_window
from test_sources import client, zip_of


def _processed_archive(db, tmp_path):
    full = make_pdf(tmp_path / "a.pdf", ["Capacity utilisation rose to 85%"]).read_bytes()
    gap = make_pdf(tmp_path / "b.pdf", ["Page one text", ""]).read_bytes()
    two = zip_of({"x.pdf": full, "y.pdf": make_pdf(tmp_path / "c.pdf", ["Second annexure"]).read_bytes()})
    nopdf = zip_of({"a.xml": b"<x/>"})
    ingest.record_window(db, nse_window([nse_row(i, f"https://h/{n}") for i, n in
                                         enumerate(["full.pdf", "gap.pdf", "two.zip", "nopdf.zip"], 1)]))
    archive = Archive(tmp_path / "archive")
    c, _ = client({"full.pdf": [(200, full)], "gap.pdf": [(200, gap)], "two.zip": [(200, two)],
                   "nopdf.zip": [(200, nopdf)]})
    ingest.download_pending(db, archive, c)
    ingest.extract_pending(db, archive)
    return archive, dict(full=sha256(full), gap=sha256(gap), two=sha256(two), nopdf=sha256(nopdf))


def _exists(archive, sha):
    return (archive.root / sha[:2] / sha).exists()


def test_purge_does_nothing_under_the_cap(db, tmp_path):
    archive, _ = _processed_archive(db, tmp_path)
    size = archive_bytes(archive.root)
    r = purge_archive(db, archive, cap=size)
    assert (r.files_deleted, r.size_after, r.still_over_cap) == (0, size, False)


def test_dry_run_deletes_nothing(db, tmp_path):
    archive, sha = _processed_archive(db, tmp_path)
    r = purge_archive(db, archive, cap=0, dry_run=True)
    assert r.files_deleted == 3 and r.dry_run
    assert all(_exists(archive, s) for s in sha.values())
    assert db.execute("SELECT count(*) FROM archive_purges").fetchone()[0] == 0


def test_purge_removes_only_fully_read_bytes_and_records_them(db, tmp_path):
    archive, sha = _processed_archive(db, tmp_path)
    versions = db.execute("SELECT count(*) FROM document_versions").fetchone()[0]
    r = purge_archive(db, archive, cap=0)
    # full.pdf (also inside two.zip), two.zip and its other member: every filing using them is TEXT_READY
    assert r.files_deleted == 3 and r.still_over_cap                 # unread bytes stay, so still over 0
    assert not _exists(archive, sha["full"]) and not _exists(archive, sha["two"])
    assert _exists(archive, sha["gap"]) and _exists(archive, sha["nopdf"])   # PARTIAL_TEXT / FAILED keep bytes
    assert db.execute("SELECT count(*), sum(byte_size) FROM archive_purges").fetchone() == (3, r.bytes_freed)
    # text, hashes and URLs stay; nothing gets downloaded or extracted again
    assert db.execute("SELECT count(*) FROM text_pages").fetchone()[0] > 0
    assert db.execute("SELECT count(*) FROM document_versions").fetchone()[0] == versions
    assert ingest.extract_pending(db, archive) == {}
    assert purge_archive(db, archive, cap=0).files_deleted == 0


def test_include_read_also_removes_partly_read_bytes_but_keeps_failed(db, tmp_path):
    archive, sha = _processed_archive(db, tmp_path)
    r = purge_archive(db, archive, cap=0, include_read=True)
    assert not _exists(archive, sha["gap"])                          # PARTIAL_TEXT: extraction already ran
    assert _exists(archive, sha["nopdf"])                            # FAILED keeps its bytes for a retry
    assert r.files_deleted == 4
    assert db.execute("SELECT count(*) FROM text_pages").fetchone()[0] > 0
