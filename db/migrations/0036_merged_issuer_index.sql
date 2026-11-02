BEGIN;
-- queue.evaluation_rows leaves out companies merged into another; this keeps that check an index lookup.
CREATE INDEX IF NOT EXISTS audit_log_merged_issuer ON audit_log ((details->>'merged_issuer'))
    WHERE action = 'MERGE_DUPLICATE_ISSUER';
INSERT INTO schema_migrations(version) VALUES ('0036_merged_issuer_index') ON CONFLICT DO NOTHING;
COMMIT;
