"""Keep the PDF archive under a size cap by deleting bytes that are fully processed.

Only bytes whose filings are all TEXT_READY are deleted: their page text is in the database and
every PDF among them extracted COMPLETE.  Downloaded-but-unread, PARTIAL_TEXT, OCR_REQUIRED and
FAILED filings keep their bytes, because OCR or a retry still needs them.  With ``include_read`` (owner
decision 2026-10-14, to keep the disk from filling) PARTIAL_TEXT and OCR_REQUIRED bytes go too: their
extraction has run and whatever text it got is stored; OCR would fetch them again.  Oldest filings go first,
and the archive is brought down to ``target`` (90% of the cap by default) so that each run does not
purge a sliver.  Each deletion is recorded in ``archive_purges`` before the file is removed; the
SHA-256 and attachment URL stay, so a purged file can be fetched again and verified.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .sources.download import Archive

GB = 1024 ** 3
CREATED_BY = "inflection.purge"
REASON = "archive over size cap; filing text stored (TEXT_READY)"
REASON_READ = "archive over size cap; extraction done (TEXT_READY, PARTIAL_TEXT or OCR_REQUIRED)"
READ_STATES = ("TEXT_READY", "PARTIAL_TEXT", "OCR_REQUIRED")

_CANDIDATES = """
SELECT v.sha256, max(v.byte_size)
  FROM document_versions v
  JOIN document_versions pv ON pv.document_id = v.document_id
  JOIN document_publications p ON p.document_version_id = pv.document_version_id
 WHERE NOT EXISTS (SELECT 1 FROM archive_purges a WHERE a.sha256 = v.sha256)
   AND (v.media_type <> 'application/pdf' OR EXISTS (
           SELECT 1 FROM text_artifacts t WHERE t.document_version_id = v.document_version_id
                                            AND t.status = 'COMPLETE'))
 GROUP BY v.sha256
HAVING bool_and(p.pipeline_state = 'TEXT_READY')
 ORDER BY min(coalesce(p.published_at, p.published_date::timestamptz, p.first_seen_at)), v.sha256"""


_CANDIDATES_READ = """
SELECT v.sha256, max(v.byte_size)
  FROM document_versions v
  JOIN document_versions pv ON pv.document_id = v.document_id
  JOIN document_publications p ON p.document_version_id = pv.document_version_id
 WHERE NOT EXISTS (SELECT 1 FROM archive_purges a WHERE a.sha256 = v.sha256)
   AND (v.media_type <> 'application/pdf' OR EXISTS (
           SELECT 1 FROM text_artifacts t WHERE t.document_version_id = v.document_version_id))
 GROUP BY v.sha256
HAVING bool_and(p.pipeline_state = ANY(%s))
 ORDER BY min(coalesce(p.published_at, p.published_date::timestamptz, p.first_seen_at)), v.sha256"""


# Bytes purged once can come back: another filing attaches the same PDF and the downloader stores it
# again.  Those copies are already recorded in archive_purges, so they are deleted again on sight once
# every filing using them is read.
_REDOWNLOADED = """
SELECT a.sha256 FROM archive_purges a
  JOIN document_versions v ON v.sha256 = a.sha256
  JOIN document_versions pv ON pv.document_id = v.document_id
  JOIN document_publications p ON p.document_version_id = pv.document_version_id
 GROUP BY a.sha256
HAVING bool_and(p.pipeline_state = ANY(%s))"""


def archive_bytes(root: Path) -> int:
    total = 0
    for dirpath, _, files in os.walk(root):
        for f in files:
            try:
                total += os.stat(os.path.join(dirpath, f)).st_size
            except FileNotFoundError:
                pass
    return total


@dataclass(frozen=True)
class PurgeResult:
    size_before: int
    size_after: int
    cap: int
    target: int
    files_deleted: int
    bytes_freed: int
    dry_run: bool

    @property
    def still_over_cap(self) -> bool:
        return self.size_after > self.cap

    def as_dict(self) -> dict:
        return dict(size_before_gb=round(self.size_before / GB, 2), size_after_gb=round(self.size_after / GB, 2),
                    cap_gb=round(self.cap / GB, 2), target_gb=round(self.target / GB, 2),
                    files_deleted=self.files_deleted, freed_gb=round(self.bytes_freed / GB, 2),
                    still_over_cap=self.still_over_cap, dry_run=self.dry_run)


def purge_archive(conn, archive: Archive, cap: int, target: Optional[int] = None, dry_run: bool = False,
                  include_read: bool = False) -> PurgeResult:
    """Delete fully processed bytes, oldest filings first, until the archive is at or below ``target``.

    Does nothing while the archive is at or below ``cap``.  When processed bytes run out first the
    archive stays over the cap and ``still_over_cap`` is true: the rest is waiting to be read."""
    target = int(cap * 0.9) if target is None else min(target, cap)
    size = before = archive_bytes(archive.root)
    deleted = freed = 0
    if size > cap and not dry_run:
        states = list(READ_STATES) if include_read else ["TEXT_READY"]
        for (sha,) in conn.execute(_REDOWNLOADED, (states,)).fetchall():
            path = archive.root / sha[:2] / sha
            if path.exists():
                n = path.stat().st_size
                path.unlink()
                deleted, freed, size = deleted + 1, freed + n, size - n
    if size > cap:
        rows = (conn.execute(_CANDIDATES_READ, (list(READ_STATES),)) if include_read else conn.execute(_CANDIDATES))
        reason = REASON_READ if include_read else REASON
        for sha, _ in rows.fetchall():
            if size <= target:
                break
            path = archive.root / sha[:2] / sha
            if not path.exists():
                continue
            n = path.stat().st_size
            if not dry_run:
                conn.execute("""INSERT INTO archive_purges (sha256, byte_size, reason, created_by)
                                VALUES (%s, %s, %s, %s) ON CONFLICT (sha256) DO NOTHING""",
                             (sha, n, reason, CREATED_BY))
                path.unlink()
            deleted, freed, size = deleted + 1, freed + n, size - n
    return PurgeResult(before, size, cap, target, deleted, freed, dry_run)


def main(argv: Optional[list[str]] = None) -> int:
    """python -m inflection.purge --archive DIR [--max-gb 100] [--target-gb 90] [--dry-run]

    Connects with INFLECTION_DSN."""
    import argparse
    import json

    import psycopg

    ap = argparse.ArgumentParser(prog="python -m inflection.purge")
    ap.add_argument("--archive", type=Path, required=True)
    ap.add_argument("--max-gb", type=float, default=100.0, help="purge only when the archive is above this")
    ap.add_argument("--target-gb", type=float, help="purge down to this (default 90%% of --max-gb)")
    ap.add_argument("--include-read", action="store_true",
                    help="also delete PARTIAL_TEXT and OCR_REQUIRED bytes (extraction already ran)")
    ap.add_argument("--dry-run", action="store_true", help="report what would be deleted; delete nothing")
    a = ap.parse_args(argv)
    with psycopg.connect(os.environ["INFLECTION_DSN"], autocommit=True) as conn:
        r = purge_archive(conn, Archive(a.archive), int(a.max_gb * GB),
                          int(a.target_gb * GB) if a.target_gb is not None else None, a.dry_run,
                          a.include_read)
    print(json.dumps(r.as_dict(), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
