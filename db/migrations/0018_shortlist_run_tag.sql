-- 0018: several weekly shortlists per week, one per run tag.  'base' is the original run; a re-run under new
-- rules or with more data (e.g. 'rerun-3.4') builds its own shortlists, packets and decisions for the same weeks
-- without touching the base run, so the two can be compared.  Selected with INFLECTION_RUN_TAG.

ALTER TABLE triage_shortlists ADD COLUMN run_tag text NOT NULL DEFAULT 'base';
ALTER TABLE triage_shortlists DROP CONSTRAINT triage_shortlists_week_start_key;
ALTER TABLE triage_shortlists ADD CONSTRAINT triage_shortlists_week_run_key UNIQUE (week_start, run_tag);

INSERT INTO schema_migrations (version) VALUES ('0018_shortlist_run_tag');
