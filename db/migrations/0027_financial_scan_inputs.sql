-- Cache a financial read by its eligible immutable fact IDs, not transaction start time.
-- A prior filing can commit after a scan even when recorded_at predates that scan.
BEGIN;
ALTER TABLE financial_scans ADD COLUMN input_fingerprint text;
INSERT INTO schema_migrations(version) VALUES('0027_financial_scan_inputs');
COMMIT;
