-- 0007: the commercial discovery route (spec sections 5.1, 5.2, 18).
--
-- Filings are stored per day and issuer (document_publications); commercial events are stored per
-- issuer, and every change is a new dated version (events -> event_versions).  This migration adds
-- the layer between them:
--
-- * ``commercial_scans``: one row per text artifact and rules version, saying whether the filing was
--   read, and if not why (no issuer, no publication time, a skipped category).  A filing whose issuer
--   is linked later is scanned again.
-- * ``commercial_mentions``: every passage the rules found, with its page, character span, quote,
--   amount (currency and scale apart), stage wording, modality and parsed terms.  Append-only:
--   rules locate passages and nominate leads; they do not establish facts.
-- * ``commercial_resolutions``: what each mention did to the issuer's events: started one (NEW),
--   changed one (REVISION), repeated one (REPETITION, linked as context, not independent evidence),
--   or revealed an earlier disclosure of one (EARLIER_DISCLOSURE, for backfill read out of order).
--
-- Events gain their type, first public time and the rules version that created them; versions gain
-- a ``details`` document for parsed terms (duration, reference, product, relationship ...).

BEGIN;

CREATE TABLE commercial_scans (
    text_artifact_id    uuid NOT NULL REFERENCES text_artifacts,
    rules_version       text NOT NULL,
    document_version_id uuid NOT NULL REFERENCES document_versions,
    publication_id      uuid REFERENCES document_publications,
    issuer_id           uuid REFERENCES issuers,
    published_at        timestamptz,                    -- availability time (asof.available_at)
    status              text NOT NULL CHECK (status IN ('SCANNED','NO_ISSUER','NO_TIMESTAMP','SKIPPED_CATEGORY')),
    sentences           integer NOT NULL DEFAULT 0,
    mentions            integer NOT NULL DEFAULT 0,
    scanned_at          timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (text_artifact_id, rules_version)
);
CREATE INDEX commercial_scans_issuer ON commercial_scans (issuer_id, published_at);

CREATE TABLE commercial_mentions (
    mention_id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    rules_version       text NOT NULL,
    text_artifact_id    uuid NOT NULL REFERENCES text_artifacts,
    document_version_id uuid NOT NULL REFERENCES document_versions,
    publication_id      uuid REFERENCES document_publications,
    issuer_id           uuid NOT NULL REFERENCES issuers,
    published_at        timestamptz NOT NULL,
    source_url          text NOT NULL,
    page_no             integer NOT NULL CHECK (page_no >= 1),
    span_start          integer NOT NULL CHECK (span_start >= 0),
    span_end            integer NOT NULL,
    quote               text NOT NULL CHECK (length(quote) > 0),
    family              text NOT NULL,                  -- ORDER, QUALIFICATION, COMMERCIAL_START, CAPACITY ...
    event_type          text NOT NULL,
    commercial_stage    text NOT NULL CHECK (commercial_stage IN (
        'AMBITION','FUNDED_PLAN','QUALIFIED','BINDING_DEMAND','COMMERCIAL_SHIPMENT','REPEAT_SHIPMENT',
        'CANCELLED','UNKNOWN')),
    lifecycle           text CHECK (lifecycle IN ('CANCELLED','EXPIRED','AMENDED','EXECUTED')),
    modality            text NOT NULL CHECK (modality IN ('REALIZED','FORWARD','CONDITIONAL','NEGATED')),
    observation_status  text NOT NULL CHECK (observation_status IN ('OBSERVED','FORECAST')),
    amount              numeric,
    currency            text,
    scale               text CHECK (scale IN ('UNITS','THOUSAND','LAKH','MILLION','CRORE','BILLION')),
    amount_text         text,
    amount_basis        text NOT NULL CHECK (amount_basis IN (
        'FIRM','CEILING','GUARANTEED_MINIMUM','EXECUTABLE_RELEASE','NON_BINDING','UNQUANTIFIED')),
    counterparty        text,
    counterparty_named  boolean NOT NULL DEFAULT false,
    relationship        text NOT NULL CHECK (relationship IN (
        'CONFIRMED_RELATED','ISSUER_ASSERTED_UNRELATED','INDEPENDENTLY_SUPPORTED_UNRELATED','UNKNOWN')),
    ownership_scope     text NOT NULL DEFAULT 'UNKNOWN' CHECK (ownership_scope IN (
        'ISSUER','SUBSIDIARY','JOINT_VENTURE','ASSOCIATE','UNKNOWN')),
    details             jsonb NOT NULL DEFAULT '{}',
    created_at          timestamptz NOT NULL DEFAULT now(),
    CHECK (span_end > span_start),
    CHECK ((amount IS NULL) = (currency IS NULL) AND (amount IS NULL) = (scale IS NULL)),
    CHECK (amount IS NOT NULL OR amount_basis = 'UNQUANTIFIED'),
    UNIQUE (text_artifact_id, page_no, span_start, rules_version, family)
);
CREATE INDEX commercial_mentions_issuer ON commercial_mentions (issuer_id, published_at);
CREATE TRIGGER commercial_mentions_append_only BEFORE UPDATE OR DELETE ON commercial_mentions
    FOR EACH ROW EXECUTE FUNCTION forbid_mutation();

CREATE TABLE commercial_resolutions (
    mention_id          uuid PRIMARY KEY REFERENCES commercial_mentions,
    outcome             text NOT NULL CHECK (outcome IN (
        'NEW','REVISION','REPETITION','EARLIER_DISCLOSURE','NOT_AN_EVENT')),
    event_id            uuid REFERENCES events,
    event_version_id    uuid REFERENCES event_versions,
    evidence_id         uuid REFERENCES evidence_links,
    note                text NOT NULL DEFAULT '',
    run_id              uuid NOT NULL,
    resolved_at         timestamptz NOT NULL DEFAULT now(),
    CHECK (outcome = 'NOT_AN_EVENT' OR event_id IS NOT NULL)
);
CREATE TRIGGER commercial_resolutions_append_only BEFORE UPDATE OR DELETE ON commercial_resolutions
    FOR EACH ROW EXECUTE FUNCTION forbid_mutation();

ALTER TABLE events
    ADD COLUMN event_type       text,
    ADD COLUMN first_public_at  timestamptz,           -- earliest dated disclosure known
    ADD COLUMN rules_version    text,
    ADD COLUMN created_by       text NOT NULL DEFAULT 'system';
CREATE INDEX events_issuer ON events (issuer_id, event_type);

ALTER TABLE event_versions
    ADD COLUMN details          jsonb NOT NULL DEFAULT '{}',
    ADD COLUMN rules_version    text,
    ADD COLUMN published_at     timestamptz;           -- availability time of the disclosure behind this version
CREATE INDEX event_versions_event ON event_versions (event_id, version_no DESC);
CREATE INDEX evidence_links_version ON evidence_links (event_version_id);
CREATE INDEX candidate_evaluations_issuer ON candidate_evaluations (issuer_id, as_of);

INSERT INTO schema_migrations (version) VALUES ('0007_commercial_route');

COMMIT;
