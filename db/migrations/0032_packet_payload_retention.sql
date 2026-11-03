BEGIN;
CREATE INDEX IF NOT EXISTS triage_packets_supersedes ON triage_packets(supersedes_id) WHERE supersedes_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS triage_packets_hash ON triage_packets(content_hash);
CREATE INDEX IF NOT EXISTS triage_items_packet ON triage_shortlist_items(packet_id) WHERE packet_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS triage_reviews_packet ON triage_reviews(packet_id) WHERE packet_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS triage_reviews_packet_hash ON triage_reviews(packet_hash) WHERE packet_hash IS NOT NULL;
CREATE INDEX IF NOT EXISTS audit_log_packet_hash ON audit_log((details->>'packet_hash'));
ALTER TABLE triage_packets ADD COLUMN IF NOT EXISTS payload_purged_at timestamptz;

CREATE TABLE packet_payload_purges (
    packet_id uuid PRIMARY KEY REFERENCES triage_packets,
    content_hash text NOT NULL,
    original_payload_bytes bigint NOT NULL,
    retained_payload_bytes bigint NOT NULL,
    purged_at timestamptz NOT NULL,
    reason text NOT NULL
);
CREATE TRIGGER packet_payload_purges_append_only BEFORE UPDATE OR DELETE ON packet_payload_purges
    FOR EACH ROW EXECUTE FUNCTION forbid_mutation();

CREATE FUNCTION packet_payload_retirable(p triage_packets) RETURNS boolean LANGUAGE sql STABLE AS $$
 SELECT p.payload_purged_at IS NULL AND p.mode<>'ACTUAL_SYSTEM_REPLAY'
 AND EXISTS(SELECT 1 FROM triage_packets child WHERE child.supersedes_id=p.packet_id
     AND child.shortlist_id=p.shortlist_id AND child.issuer_id=p.issuer_id
     AND CASE WHEN child.content->'manifest'->>'generation' ~ '^[0-9]+$'
         THEN (child.content->'manifest'->>'generation')::numeric ELSE 0 END
       > CASE WHEN p.content->'manifest'->>'generation' ~ '^[0-9]+$'
         THEN (p.content->'manifest'->>'generation')::numeric ELSE 0 END)
 AND NOT EXISTS(SELECT 1 FROM triage_shortlist_items i WHERE i.packet_id=p.packet_id)
 AND NOT EXISTS(SELECT 1 FROM triage_reviews r WHERE r.packet_id=p.packet_id)
 AND NOT EXISTS(SELECT 1 FROM triage_reviews r WHERE r.packet_hash=p.content_hash)
 AND NOT EXISTS(SELECT 1 FROM audit_log a WHERE a.details->>'packet_hash'=p.content_hash)
$$;

CREATE FUNCTION guard_packet_retention() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_OP='UPDATE' AND current_setting('inflection.packet_retention',true)='owner_authorized'
    AND OLD.payload_purged_at IS NULL AND NEW.payload_purged_at IS NOT NULL
    AND (to_jsonb(NEW)-ARRAY['content','markdown','payload_purged_at'])=
        (to_jsonb(OLD)-ARRAY['content','markdown','payload_purged_at'])
    AND NEW.markdown=''
    AND NEW.content=jsonb_build_object('manifest',OLD.content->'manifest','retention',
        jsonb_build_object('reason','OWNER_REQUESTED_SUPERSEDED_PACKET_REMOVAL',
            'original_content_hash',OLD.content_hash,'removed_at',NEW.payload_purged_at))
    AND packet_payload_retirable(OLD) THEN RETURN NEW;
 END IF;
 RAISE EXCEPTION 'triage_packets is append-only; only authorized unreferenced superseded payload retention is permitted';
END $$;
DROP TRIGGER triage_packets_append_only ON triage_packets;
CREATE TRIGGER triage_packets_append_only BEFORE UPDATE OR DELETE ON triage_packets
    FOR EACH ROW EXECUTE FUNCTION guard_packet_retention();

-- Lock before checking so a new decision and retention cannot pass each other.
CREATE FUNCTION guard_retained_packet_reference() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE saved record; bound_hash text;
BEGIN
 bound_hash=to_jsonb(NEW)->>'packet_hash';
 FOR saved IN SELECT p.packet_id,p.payload_purged_at FROM triage_packets p
   WHERE p.packet_id=NEW.packet_id OR (bound_hash IS NOT NULL AND p.content_hash=bound_hash)
   FOR KEY SHARE
 LOOP
   IF saved.payload_purged_at IS NOT NULL THEN
     RAISE EXCEPTION 'Packet payload was removed; a retained packet is required for a decision';
   END IF;
 END LOOP;
 RETURN NEW;
END $$;
CREATE TRIGGER triage_items_retained_packet BEFORE INSERT OR UPDATE OF packet_id ON triage_shortlist_items
    FOR EACH ROW EXECUTE FUNCTION guard_retained_packet_reference();
CREATE TRIGGER triage_reviews_retained_packet BEFORE INSERT OR UPDATE OF packet_id,packet_hash ON triage_reviews
    FOR EACH ROW EXECUTE FUNCTION guard_retained_packet_reference();
INSERT INTO schema_migrations(version) VALUES('0032_packet_payload_retention');
COMMIT;
