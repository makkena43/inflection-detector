BEGIN;
-- Hot lookups in financial input fingerprints and packet evidence (2026-11-02 run profiling):
-- a company's events by first public date, and a company's filings by pipeline state and date.
CREATE INDEX IF NOT EXISTS events_issuer_first_public ON events (issuer_id, first_public_at);
CREATE INDEX IF NOT EXISTS document_publications_issuer_state ON document_publications (issuer_id, pipeline_state, published_at);
INSERT INTO schema_migrations(version) VALUES ('0035_hot_lookup_indexes') ON CONFLICT DO NOTHING;
COMMIT;
