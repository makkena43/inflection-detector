-- 0005: record archived bytes deleted to keep the archive under a size cap.
--
-- Owner decision of 10 Oct 2026 (docs/spec_open_issues.md #13): once the archive passes its cap,
-- PDFs whose filings are fully read (TEXT_READY) may be deleted, oldest filings first.  The
-- document_versions row (SHA-256, size, original filename), the publication's attachment URL and
-- the page text stay, so the bytes can be fetched again and checked against the hash.

BEGIN;

CREATE TABLE archive_purges (
    sha256      text PRIMARY KEY CHECK (sha256 ~ '^[0-9a-f]{64}$'),
    byte_size   bigint NOT NULL CHECK (byte_size >= 0),
    reason      text NOT NULL,
    purged_at   timestamptz NOT NULL DEFAULT now(),
    created_by  text NOT NULL
);

INSERT INTO schema_migrations (version) VALUES ('0005_archive_purges');

COMMIT;
