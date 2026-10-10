-- 0003: record exchange listing windows and their raw metadata.
--
-- * ingestion_runs.coverage_status gains BLOCKED (401/403/429 or a bot-protection page) and
--   TRUNCATED (the source reports more rows than were fetched).  Both are coverage gaps, not
--   "no filings" (spec section 15 test 11).
-- * document_publications keeps the exchange's original row and time text for audit (spec 6.1).

ALTER TABLE ingestion_runs DROP CONSTRAINT ingestion_runs_coverage_status_check;
ALTER TABLE ingestion_runs ADD CONSTRAINT ingestion_runs_coverage_status_check
    CHECK (coverage_status IN ('COMPLETE','PARTIAL','TRUNCATED','EMPTY_UNVERIFIED','BLOCKED','FAILED','NOT_ATTEMPTED'));

ALTER TABLE document_publications
    ADD COLUMN raw_time     text,
    ADD COLUMN raw_metadata jsonb NOT NULL DEFAULT '{}';

CREATE INDEX document_publications_pending ON document_publications (pipeline_state, published_at)
    WHERE attachment_url IS NOT NULL;
