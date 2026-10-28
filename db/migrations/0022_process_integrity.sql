-- Preserve raw immutable facts while exposing honest availability to all as-of readers.
-- Legacy BSE snapshots have no dissemination timestamp and may contain later restatements.
-- The earliest proven availability of such a snapshot is when it was recorded here.
BEGIN;
CREATE OR REPLACE VIEW financial_facts_asof AS
SELECT fact_id, issuer_id, metric, period_start, period_end, scope, segment, value,
       CASE WHEN provider='bse_results_snapshot' AND provider_version='bse-results-snapshot-1'
            THEN recorded_at ELSE available_at END AS available_at,
       provider, provider_version, document_version_id, supersedes_id, recorded_at,
       value_kind, currency, scale, physical_unit, original_text, missing_reason,
       period_type, cumulative, accounting_basis, publication_id, schema_version, created_by, content_hash,
       available_at AS source_available_at,
       CASE WHEN provider='bse_results_snapshot' THEN 'SNAPSHOT_OBSERVED'
            WHEN publication_id IS NOT NULL THEN 'FILING_DISCLOSURE'
            ELSE 'PROVIDER_REPORTED' END AS availability_basis
FROM financial_facts;
INSERT INTO schema_migrations(version) VALUES ('0022_process_integrity') ON CONFLICT DO NOTHING;
COMMIT;
