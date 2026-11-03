-- Owner decision (2026-11-01): no company may be left without financials.  A BSE results snapshot
-- figure has no dissemination time of its own, but the company's results announcement for that period
-- does: the figure is treated as public from that announcement (the earliest results filing of the
-- issuer published after the period ended, within the listing deadline window).  Snapshot values are
-- BSE's latest presentation, so a later restatement can differ from the figure first reported; readers
-- see availability_basis 'SNAPSHOT_TIMED_BY_FILING'.  Snapshots without such a filing keep the
-- observation time.  Raw facts stay unchanged; the timing is an auditable, append-only table.
BEGIN;
CREATE TABLE financial_snapshot_timing (
    fact_id uuid PRIMARY KEY REFERENCES financial_facts,
    publication_id uuid NOT NULL REFERENCES document_publications,
    available_at timestamptz NOT NULL,
    rule text NOT NULL,
    recorded_at timestamptz NOT NULL DEFAULT now()
);
CREATE TRIGGER financial_snapshot_timing_append_only BEFORE UPDATE OR DELETE ON financial_snapshot_timing
    FOR EACH ROW EXECUTE FUNCTION forbid_mutation();

CREATE OR REPLACE VIEW financial_facts_asof AS
SELECT f.fact_id, f.issuer_id, f.metric, f.period_start, f.period_end, f.scope, f.segment, f.value,
       CASE WHEN f.provider='bse_results_snapshot' AND f.provider_version='bse-results-snapshot-1'
            THEN coalesce(t.available_at, f.recorded_at) ELSE f.available_at END AS available_at,
       f.provider, f.provider_version, f.document_version_id, f.supersedes_id, f.recorded_at,
       f.value_kind, f.currency, f.scale, f.physical_unit, f.original_text, f.missing_reason,
       f.period_type, f.cumulative, f.accounting_basis, f.publication_id, f.schema_version, f.created_by, f.content_hash,
       f.available_at AS source_available_at,
       CASE WHEN f.provider='bse_results_snapshot' AND t.fact_id IS NOT NULL THEN 'SNAPSHOT_TIMED_BY_FILING'
            WHEN f.provider='bse_results_snapshot' THEN 'SNAPSHOT_OBSERVED'
            WHEN f.publication_id IS NOT NULL THEN 'FILING_DISCLOSURE'
            ELSE 'PROVIDER_REPORTED' END AS availability_basis
FROM financial_facts f LEFT JOIN financial_snapshot_timing t USING (fact_id);
INSERT INTO schema_migrations(version) VALUES ('0034_snapshot_filing_time') ON CONFLICT DO NOTHING;
COMMIT;
