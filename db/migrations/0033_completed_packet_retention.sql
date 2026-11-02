BEGIN;
CREATE INDEX IF NOT EXISTS triage_packets_issuer_cutoff ON triage_packets(issuer_id,cutoff);
CREATE TABLE packet_retention_completed_shortlists (
    shortlist_id uuid PRIMARY KEY REFERENCES triage_shortlists,
    week_start date NOT NULL,
    run_tag text NOT NULL,
    authorized_at timestamptz NOT NULL DEFAULT now()
);
CREATE TRIGGER packet_retention_completed_append_only BEFORE UPDATE OR DELETE ON packet_retention_completed_shortlists
    FOR EACH ROW EXECUTE FUNCTION forbid_mutation();

CREATE FUNCTION retired_packet_content(body jsonb,digest text,removed timestamptz) RETURNS jsonb LANGUAGE sql STABLE AS $$
 SELECT jsonb_build_object('manifest',coalesce(body->'manifest','{}'::jsonb)||jsonb_build_object(
    'completeness','MINIMAL','nomination_status','VERIFICATION_REQUIRED',
    'nomination_issues',coalesce(body->'manifest'->'nomination_issues','[]'::jsonb)||jsonb_build_array('Packet payload removed under owner retention policy; rebuild required'),
    'missing_evidence',coalesce(body->'manifest'->'missing_evidence','[]'::jsonb)||jsonb_build_array('Packet payload removed under owner retention policy; rebuild required')),
    'retention',jsonb_build_object('reason','OWNER_REQUESTED_OLD_PACKET_REMOVAL',
        'original_content_hash',digest,'removed_at',removed))
$$;

CREATE OR REPLACE FUNCTION packet_payload_retirable(p triage_packets) RETURNS boolean LANGUAGE sql STABLE AS $$
 SELECT p.payload_purged_at IS NULL AND p.mode<>'ACTUAL_SYSTEM_REPLAY'
 AND (EXISTS(SELECT 1 FROM triage_packets child WHERE child.supersedes_id=p.packet_id
     AND child.shortlist_id=p.shortlist_id AND child.issuer_id=p.issuer_id
     AND CASE WHEN child.content->'manifest'->>'generation' ~ '^[0-9]+$'
         THEN (child.content->'manifest'->>'generation')::numeric ELSE 0 END
       > CASE WHEN p.content->'manifest'->>'generation' ~ '^[0-9]+$'
         THEN (p.content->'manifest'->>'generation')::numeric ELSE 0 END)
 OR (p.created_by='inflection.quality_repair' AND EXISTS(
     SELECT 1 FROM packet_retention_completed_shortlists completed
      WHERE completed.shortlist_id=p.shortlist_id AND EXISTS(
       SELECT 1 FROM triage_packets newer JOIN triage_shortlists ns USING(shortlist_id)
        WHERE newer.issuer_id=p.issuer_id AND newer.cutoff>p.cutoff
          AND newer.payload_purged_at IS NULL AND newer.created_by='inflection.quality_repair'
          AND ns.run_tag=completed.run_tag AND newer.mode=p.mode))))
 AND NOT EXISTS(SELECT 1 FROM triage_shortlist_items i WHERE i.packet_id=p.packet_id)
 AND NOT EXISTS(SELECT 1 FROM triage_reviews r WHERE r.packet_id=p.packet_id)
 AND NOT EXISTS(SELECT 1 FROM triage_reviews r WHERE r.packet_hash=p.content_hash)
 AND NOT EXISTS(SELECT 1 FROM audit_log a WHERE a.details->>'packet_hash'=p.content_hash)
$$;

CREATE OR REPLACE FUNCTION guard_packet_retention() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_OP='UPDATE' AND current_setting('inflection.packet_retention',true)='owner_authorized'
    AND OLD.payload_purged_at IS NULL AND NEW.payload_purged_at IS NOT NULL
    AND (to_jsonb(NEW)-ARRAY['content','markdown','payload_purged_at','completeness'])=
        (to_jsonb(OLD)-ARRAY['content','markdown','payload_purged_at','completeness'])
    AND NEW.markdown='' AND NEW.completeness='MINIMAL'
    AND NEW.content=retired_packet_content(OLD.content,OLD.content_hash,NEW.payload_purged_at)
    AND packet_payload_retirable(OLD) THEN RETURN NEW;
 END IF;
 RAISE EXCEPTION 'triage_packets is append-only; only authorized unreferenced superseded payload retention is permitted';
END $$;
INSERT INTO schema_migrations(version) VALUES('0033_completed_packet_retention');
COMMIT;
