-- 0010: triage packets (spec sections 5.3, 6, 9 Mode A, 15 test 12, 17).
--
-- One frozen packet per shortlisted company per content version: the evidence the triage reads,
-- cut at the shortlist's cutoff with the shared as-of predicate.  Packets are append-only.  A
-- rebuild that finds the same content keeps the existing packet; different content (a filing
-- ingested late, a new fact version) adds a packet that supersedes the earlier one, which stays
-- as it was.  ``content`` is the structured packet, ``markdown`` the rendering a model reads, and
-- ``content_hash`` the SHA-256 of ``content`` (the packet hash a triage result refers to).
--
-- ``triage_shortlist_items.packet_id`` records the packet a triage result was given.

BEGIN;

CREATE TABLE triage_packets (
    packet_id        uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    shortlist_id     uuid NOT NULL,
    issuer_id        uuid NOT NULL,
    packet_version   text NOT NULL,
    schema_version   text NOT NULL,
    cutoff           timestamptz NOT NULL,
    mode             text NOT NULL
                     CHECK (mode IN ('LIVE','PUBLIC_INFORMATION_RECONSTRUCTION','ACTUAL_SYSTEM_REPLAY')),
    content          jsonb NOT NULL,
    markdown         text NOT NULL,
    token_budget     integer NOT NULL CHECK (token_budget > 0),
    token_estimate   integer NOT NULL CHECK (token_estimate > 0),
    truncated        boolean NOT NULL,
    completeness     text NOT NULL CHECK (completeness IN ('COMPLETE','PARTIAL','MINIMAL')),
    content_hash     text NOT NULL CHECK (content_hash ~ '^[0-9a-f]{64}$'),
    supersedes_id    uuid REFERENCES triage_packets,
    created_by       text NOT NULL DEFAULT 'system',
    created_at       timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (shortlist_id, issuer_id) REFERENCES triage_shortlist_items (shortlist_id, issuer_id),
    UNIQUE (shortlist_id, issuer_id, content_hash)
);
CREATE INDEX triage_packets_item ON triage_packets (shortlist_id, issuer_id, created_at DESC);

CREATE TRIGGER triage_packets_append_only BEFORE UPDATE OR DELETE ON triage_packets
    FOR EACH ROW EXECUTE FUNCTION forbid_mutation();

ALTER TABLE triage_shortlist_items ADD COLUMN packet_id uuid REFERENCES triage_packets;

INSERT INTO schema_migrations (version) VALUES ('0010_triage_packets');

COMMIT;
