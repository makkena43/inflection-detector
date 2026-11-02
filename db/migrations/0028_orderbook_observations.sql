-- Keep legacy inferred dates/amounts for audit; new observations carry explicit provenance.
BEGIN;
CREATE TABLE orderbook_scans (
    publication_id uuid NOT NULL REFERENCES document_publications,
    extractor_version text NOT NULL,
    input_fingerprint text NOT NULL,
    source_document_version_id uuid NOT NULL REFERENCES document_versions,
    available_at timestamptz NOT NULL,
    status text NOT NULL CHECK(status IN ('SCANNED','NO_MATCH')),
    observations integer NOT NULL,
    issues jsonb NOT NULL DEFAULT '{}',
    scanned_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY(publication_id,extractor_version)
);
CREATE TABLE orderbook_scan_history (
    scan_id bigserial PRIMARY KEY,
    publication_id uuid NOT NULL REFERENCES document_publications,
    extractor_version text NOT NULL,
    input_fingerprint text NOT NULL,
    source_document_version_id uuid NOT NULL REFERENCES document_versions,
    available_at timestamptz NOT NULL,
    status text NOT NULL,
    observations integer NOT NULL,
    issues jsonb NOT NULL,
    scanned_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE INDEX orderbook_scan_history_source ON orderbook_scan_history(publication_id,extractor_version,scanned_at DESC);
CREATE TRIGGER orderbook_scan_history_append_only BEFORE UPDATE OR DELETE ON orderbook_scan_history
    FOR EACH ROW EXECUTE FUNCTION forbid_mutation();
CREATE TABLE orderbook_observations (
    observation_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    issuer_id uuid NOT NULL REFERENCES issuers,
    publication_id uuid NOT NULL REFERENCES document_publications,
    text_artifact_id uuid REFERENCES text_artifacts,
    page_no integer,
    kind text NOT NULL CHECK(kind IN ('BOOK','INFLOW')),
    period_end date,
    period_basis text NOT NULL,
    amount_cr numeric NOT NULL CHECK(amount_cr>=0),
    currency text NOT NULL CHECK(currency='INR'),
    scope text NOT NULL,
    quality text NOT NULL,
    published_at timestamptz NOT NULL,
    quote text NOT NULL,
    metadata jsonb NOT NULL,
    extractor_version text NOT NULL,
    input_fingerprint text NOT NULL,
    content_hash text NOT NULL,
    recorded_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE(publication_id,extractor_version,input_fingerprint,content_hash)
);
CREATE INDEX orderbook_observations_issuer ON orderbook_observations(issuer_id,period_end,published_at);
CREATE TRIGGER orderbook_observations_append_only BEFORE UPDATE OR DELETE ON orderbook_observations
    FOR EACH ROW EXECUTE FUNCTION forbid_mutation();
INSERT INTO schema_migrations(version) VALUES('0028_orderbook_observations');
COMMIT;
