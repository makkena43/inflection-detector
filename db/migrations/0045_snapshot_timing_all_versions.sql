-- 0045: the filing timing of 0034 applied to every BSE results snapshot version, not only
-- 'bse-results-snapshot-1' (version 2, loaded 2026-11-08/09, was public only from its observation time),
-- and to face values derived for those snapshots (provider 'bse_listing_face_value': the face value is
-- printed in the same results statement as the paid-up capital it goes with).  Owner decision 2026-11-10.
-- Untimed version-1 figures keep recorded_at as before; others keep their own available_at.
BEGIN;
CREATE OR REPLACE VIEW financial_facts_asof AS
SELECT f.fact_id, f.issuer_id, f.metric, f.period_start, f.period_end, f.scope, f.segment, f.value,
       CASE WHEN f.provider='bse_results_snapshot' AND f.provider_version='bse-results-snapshot-1'
            THEN coalesce(t.available_at, f.recorded_at)
            WHEN f.provider IN ('bse_results_snapshot', 'bse_listing_face_value')
            THEN coalesce(t.available_at, f.available_at)
            ELSE f.available_at END AS available_at,
       f.provider, f.provider_version, f.document_version_id, f.supersedes_id, f.recorded_at,
       f.value_kind, f.currency, f.scale, f.physical_unit, f.original_text, f.missing_reason,
       f.period_type, f.cumulative, f.accounting_basis, f.publication_id, f.schema_version, f.created_by, f.content_hash,
       f.available_at AS source_available_at,
       CASE WHEN f.provider IN ('bse_results_snapshot', 'bse_listing_face_value') AND t.fact_id IS NOT NULL THEN 'SNAPSHOT_TIMED_BY_FILING'
            WHEN f.provider='bse_results_snapshot' THEN 'SNAPSHOT_OBSERVED'
            WHEN f.publication_id IS NOT NULL THEN 'FILING_DISCLOSURE'
            ELSE 'PROVIDER_REPORTED' END AS availability_basis
FROM financial_facts f LEFT JOIN financial_snapshot_timing t USING (fact_id);
INSERT INTO schema_migrations(version) VALUES ('0045_snapshot_timing_all_versions') ON CONFLICT DO NOTHING;
COMMIT;
