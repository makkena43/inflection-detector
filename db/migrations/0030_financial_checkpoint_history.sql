-- Preserve no-signal and withdrawn checkpoints as well as positive evaluations.
BEGIN;
CREATE TRIGGER financial_checkpoint_timing AFTER INSERT OR UPDATE OR DELETE ON financial_scans
    FOR EACH ROW EXECUTE FUNCTION capture_supplementary_version('publication_id','rules_version');
INSERT INTO supplementary_versions(source_table,source_key,data)
    SELECT 'financial_scans',publication_id::text||':'||rules_version,to_jsonb(f) FROM financial_scans f;
INSERT INTO schema_migrations(version) VALUES('0030_financial_checkpoint_history');
COMMIT;
