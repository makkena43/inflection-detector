-- Mutable supplementary imports previously had no trustworthy revision time.
-- Start history at observation time; do not fabricate historical availability.
BEGIN;
CREATE TABLE supplementary_versions (
    version_id bigserial PRIMARY KEY,
    source_table text NOT NULL,
    source_key text NOT NULL,
    observed_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    deleted boolean NOT NULL DEFAULT false,
    data jsonb NOT NULL
);
CREATE INDEX supplementary_versions_asof ON supplementary_versions(source_table,source_key,observed_at DESC,version_id DESC);
CREATE TRIGGER supplementary_versions_append_only BEFORE UPDATE OR DELETE ON supplementary_versions
    FOR EACH ROW EXECUTE FUNCTION forbid_mutation();
CREATE FUNCTION capture_supplementary_version() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE payload jsonb; identity text;
BEGIN
    payload := CASE WHEN TG_OP='DELETE' THEN to_jsonb(OLD) ELSE to_jsonb(NEW) END;
    IF TG_OP='UPDATE' AND to_jsonb(OLD)=payload THEN RETURN NEW; END IF;
    identity := payload->>TG_ARGV[0];
    IF TG_NARGS>1 THEN identity := identity || ':' || (payload->>TG_ARGV[1]); END IF;
    INSERT INTO supplementary_versions(source_table,source_key,deleted,data)
        VALUES(TG_TABLE_NAME,identity,TG_OP='DELETE',payload);
    IF TG_OP='DELETE' THEN RETURN OLD; END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER shareholding_timing AFTER INSERT OR UPDATE OR DELETE ON shareholding_patterns
    FOR EACH ROW EXECUTE FUNCTION capture_supplementary_version('source_ref');
CREATE TRIGGER programme_timing AFTER INSERT OR UPDATE OR DELETE ON govt_programmes
    FOR EACH ROW EXECUTE FUNCTION capture_supplementary_version('programme_id');
CREATE TRIGGER mention_timing AFTER INSERT OR UPDATE OR DELETE ON programme_mentions
    FOR EACH ROW EXECUTE FUNCTION capture_supplementary_version('programme_id','publication_id');
CREATE TRIGGER pli_timing AFTER INSERT OR UPDATE OR DELETE ON pli_beneficiaries
    FOR EACH ROW EXECUTE FUNCTION capture_supplementary_version('pli_id');
CREATE TRIGGER action_timing AFTER INSERT OR UPDATE OR DELETE ON corporate_actions
    FOR EACH ROW EXECUTE FUNCTION capture_supplementary_version('action_id');
INSERT INTO supplementary_versions(source_table,source_key,data)
    SELECT 'shareholding_patterns',source_ref,to_jsonb(s) FROM shareholding_patterns s;
INSERT INTO supplementary_versions(source_table,source_key,data)
    SELECT 'govt_programmes',programme_id::text,to_jsonb(g) FROM govt_programmes g;
INSERT INTO supplementary_versions(source_table,source_key,data)
    SELECT 'programme_mentions',programme_id::text||':'||publication_id::text,to_jsonb(m) FROM programme_mentions m;
INSERT INTO supplementary_versions(source_table,source_key,data)
    SELECT 'pli_beneficiaries',pli_id::text,to_jsonb(p) FROM pli_beneficiaries p;
INSERT INTO supplementary_versions(source_table,source_key,data)
    SELECT 'corporate_actions',action_id::text,to_jsonb(a) FROM corporate_actions a;
INSERT INTO schema_migrations(version) VALUES('0029_supplementary_timing');
COMMIT;
