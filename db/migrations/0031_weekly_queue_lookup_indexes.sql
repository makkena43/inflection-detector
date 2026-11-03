BEGIN;
-- Broad weekly reconstructions use these lookups for every eligible evaluation.
-- Preserve the same source supersession and issuer identity predicates.
CREATE INDEX IF NOT EXISTS financial_scans_evaluation
    ON financial_scans (evaluation_id) WHERE evaluation_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS securities_issuer
    ON securities (issuer_id);
INSERT INTO schema_migrations(version) VALUES('0031_weekly_queue_lookup_indexes');
COMMIT;
