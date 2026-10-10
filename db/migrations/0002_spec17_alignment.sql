-- Align the schema with spec v1.0 section 17 (implementation contracts) and the
-- vocabularies of sections 4, 5, 18 and 19.  No new features.
--
-- Written for a database that holds no production data yet: several new NOT NULL
-- columns have no default, so the migration stops with an error rather than
-- inventing values if rows already exist.
--
-- Shared conventions applied here:
--   * versioned records carry schema_version, created_by, content_hash (supersedes_id where it applies);
--   * amounts keep value, currency, magnitude scale and physical unit apart, plus original text;
--   * a missing value is NULL plus missing_reason, never zero;
--   * mutable workflow rows carry revision.

BEGIN;

CREATE EXTENSION IF NOT EXISTS btree_gist;

-- Section 17: amounts.  MONEY needs currency + scale; PER_SHARE needs currency;
-- PHYSICAL needs a physical unit.
CREATE FUNCTION amount_shape_ok(kind text, currency text, scale text, physical_unit text)
RETURNS boolean LANGUAGE sql IMMUTABLE AS $$
    SELECT CASE kind
        WHEN 'MONEY'     THEN currency IS NOT NULL AND scale IS NOT NULL
        WHEN 'PER_SHARE' THEN currency IS NOT NULL
        WHEN 'SHARES'    THEN scale IS NOT NULL
        WHEN 'PHYSICAL'  THEN physical_unit IS NOT NULL
        WHEN 'MONEY_PER_PHYSICAL' THEN currency IS NOT NULL AND scale IS NOT NULL AND physical_unit IS NOT NULL
        WHEN 'PERCENT'   THEN true
        WHEN 'MULTIPLE'  THEN true
        WHEN 'COUNT'     THEN true
        ELSE false END
$$;

-- ---------------------------------------------------------------------------
-- Identity
-- ---------------------------------------------------------------------------

ALTER TABLE issuers
    ADD COLUMN legal_identifier      text,                       -- e.g. CIN, when available
    ADD COLUMN classification_source text,
    ADD COLUMN identity_status       text NOT NULL DEFAULT 'PROVISIONAL'
        CHECK (identity_status IN ('VERIFIED','PROVISIONAL','UNRESOLVED','CONFLICT')),
    ADD COLUMN created_by            text NOT NULL DEFAULT 'system',
    ADD COLUMN revision              integer NOT NULL DEFAULT 1;

ALTER TABLE securities
    ADD COLUMN currency         text NOT NULL DEFAULT 'INR',
    ADD COLUMN lot_size         integer CHECK (lot_size > 0),    -- SME lots limit achievable fills
    ADD COLUMN exchange_segment text NOT NULL DEFAULT 'UNKNOWN'
        CHECK (exchange_segment IN ('MAINBOARD','SME','UNKNOWN')),
    ADD COLUMN valid_from       date,
    ADD COLUMN valid_to         date,
    ADD COLUMN created_by       text NOT NULL DEFAULT 'system',
    ADD CONSTRAINT securities_validity CHECK (valid_to IS NULL OR valid_from IS NULL OR valid_to >= valid_from);

ALTER TABLE identifier_history RENAME COLUMN recorded_at TO known_at;
ALTER TABLE identifier_history
    ADD COLUMN created_by text NOT NULL DEFAULT 'system',
    -- Section 17: overlapping conflicting spans are rejected.  The same identifier value may not
    -- point at two different securities on any shared day.
    ADD CONSTRAINT identifier_history_no_conflicting_overlap EXCLUDE USING gist (
        exchange WITH =, kind WITH =, value WITH =, security_id WITH <>,
        daterange(valid_from, valid_to, '[]') WITH &&);

-- ---------------------------------------------------------------------------
-- Sources and ingestion
-- ---------------------------------------------------------------------------

ALTER TABLE sources
    ADD COLUMN adapter_name            text,
    ADD COLUMN adapter_version         text,
    ADD COLUMN access_mode             text NOT NULL DEFAULT 'BLOCKED'
        CHECK (access_mode IN ('LICENSED_FEED','PUBLIC_PERMITTED','USER_EXPORT','MANUAL_IMPORT','BLOCKED')),
    ADD COLUMN entitlement_expires_at  timestamptz,
    ADD COLUMN retention_allowed       boolean NOT NULL DEFAULT false,
    ADD COLUMN share_with_model_allowed boolean NOT NULL DEFAULT false,
    ADD COLUMN request_limits          jsonb NOT NULL DEFAULT '{}',
    ADD COLUMN cost_note               text,
    ADD COLUMN owner                   text,
    ADD COLUMN last_coverage_test_at   timestamptz,
    ADD COLUMN revision                integer NOT NULL DEFAULT 1,
    ADD CONSTRAINT sources_blocked_not_enabled CHECK (NOT (enabled AND access_mode = 'BLOCKED'));

ALTER TABLE ingestion_runs
    ADD COLUMN segment               text,
    ADD COLUMN reconciliation_result jsonb,
    ADD COLUMN revision              integer NOT NULL DEFAULT 1;

-- ---------------------------------------------------------------------------
-- Documents.  `document_versions` is the spec's immutable `document` (bytes);
-- `document_publications` is where and when it appeared.
-- ---------------------------------------------------------------------------

ALTER TABLE document_versions
    ADD COLUMN page_count        integer CHECK (page_count >= 0),
    ADD COLUMN original_filename text,
    ADD COLUMN schema_version    text NOT NULL DEFAULT 'document.v1',
    ADD COLUMN created_by        text NOT NULL DEFAULT 'system';
CREATE TRIGGER document_versions_append_only BEFORE UPDATE OR DELETE ON document_versions
    FOR EACH ROW EXECUTE FUNCTION forbid_mutation();

ALTER TABLE document_publications RENAME COLUMN timestamp_basis TO publication_basis;
ALTER TABLE document_publications RENAME COLUMN published_date_only TO published_date;
ALTER TABLE document_publications RENAME COLUMN ingested_at TO first_seen_at;
-- A publication is discovered before its bytes are downloaded.
ALTER TABLE document_publications ALTER COLUMN document_version_id DROP NOT NULL;
ALTER TABLE document_publications
    ADD COLUMN issuer_id           uuid REFERENCES issuers,
    ADD COLUMN original_category   text,
    ADD COLUMN original_subcategory text,
    ADD COLUMN title               text,
    ADD COLUMN attachment_url      text,
    ADD COLUMN response_sha256     text CHECK (response_sha256 ~ '^[0-9a-f]{64}$'),
    ADD COLUMN event_date          date,
    ADD COLUMN period_end          date,
    ADD COLUMN ingested_at         timestamptz,                -- bytes stored; NULL until downloaded
    ADD COLUMN pipeline_state      text NOT NULL DEFAULT 'DISCOVERED' CHECK (pipeline_state IN (
        'DISCOVERED','DOWNLOADED','TEXT_READY','OCR_REQUIRED','PARTIAL_TEXT','FAILED','SUPERSEDED')),
    ADD COLUMN failure_reason      text,
    ADD COLUMN revision            integer NOT NULL DEFAULT 1,
    ADD CONSTRAINT document_publications_bytes_after_download
        CHECK (pipeline_state IN ('DISCOVERED','FAILED') OR document_version_id IS NOT NULL),
    ADD CONSTRAINT document_publications_failure_reason
        CHECK ((pipeline_state = 'FAILED') = (failure_reason IS NOT NULL));

ALTER TABLE text_artifacts
    ADD COLUMN parser_config     jsonb NOT NULL DEFAULT '{}',
    ADD COLUMN missing_pages     integer[] NOT NULL DEFAULT '{}',
    ADD COLUMN ocr_provenance    text,
    ADD COLUMN schema_version    text NOT NULL DEFAULT 'text_artifact.v1',
    ADD COLUMN created_by        text NOT NULL DEFAULT 'system';

-- ---------------------------------------------------------------------------
-- Financial facts: currency / scale / unit apart, period type, missing reason.
-- ---------------------------------------------------------------------------

ALTER TABLE financial_facts DROP COLUMN unit;
ALTER TABLE financial_facts ALTER COLUMN value DROP NOT NULL;
ALTER TABLE financial_facts
    ADD COLUMN value_kind       text NOT NULL,
    ADD COLUMN currency         text,
    ADD COLUMN scale            text CHECK (scale IN ('UNITS','THOUSAND','LAKH','MILLION','CRORE','BILLION')),
    ADD COLUMN physical_unit    text,
    ADD COLUMN original_text    text,
    ADD COLUMN missing_reason   text
        CHECK (missing_reason IN ('NOT_APPLICABLE','NOT_DISCLOSED','FETCH_FAILED','UNVERIFIED')),
    ADD COLUMN period_type      text NOT NULL CHECK (period_type IN ('QUARTER','HALF_YEAR','NINE_MONTHS','ANNUAL')),
    ADD COLUMN cumulative       boolean NOT NULL DEFAULT false,
    ADD COLUMN accounting_basis text NOT NULL DEFAULT 'UNKNOWN' CHECK (accounting_basis IN ('IND_AS','IGAAP','UNKNOWN')),
    ADD COLUMN publication_id   uuid REFERENCES document_publications,
    ADD COLUMN schema_version   text NOT NULL DEFAULT 'financial_fact.v1',
    ADD COLUMN created_by       text NOT NULL DEFAULT 'system',
    ADD COLUMN content_hash     text NOT NULL,
    ADD CONSTRAINT financial_facts_missing CHECK ((value IS NULL) = (missing_reason IS NOT NULL)),
    ADD CONSTRAINT financial_facts_amount_shape CHECK (amount_shape_ok(value_kind, currency, scale, physical_unit));

-- ---------------------------------------------------------------------------
-- Events and evidence
-- ---------------------------------------------------------------------------

ALTER TABLE event_versions DROP COLUMN magnitude_unit;
ALTER TABLE event_versions RENAME COLUMN stage TO commercial_stage;
ALTER TABLE event_versions
    ADD CONSTRAINT event_versions_stage CHECK (commercial_stage IN (
        'AMBITION','FUNDED_PLAN','QUALIFIED','BINDING_DEMAND','COMMERCIAL_SHIPMENT','REPEAT_SHIPMENT',
        'CANCELLED','UNKNOWN')),
    ADD COLUMN event_type          text NOT NULL,
    ADD COLUMN observation_status  text NOT NULL CHECK (observation_status IN ('OBSERVED','FORECAST')),
    ADD COLUMN amount_basis        text NOT NULL DEFAULT 'UNQUANTIFIED' CHECK (amount_basis IN (
        'FIRM','CEILING','GUARANTEED_MINIMUM','EXECUTABLE_RELEASE','NON_BINDING','UNQUANTIFIED')),
    ADD COLUMN magnitude_currency  text,
    ADD COLUMN magnitude_scale     text CHECK (magnitude_scale IN ('UNITS','THOUSAND','LAKH','MILLION','CRORE','BILLION')),
    ADD COLUMN magnitude_missing_reason text
        CHECK (magnitude_missing_reason IN ('NOT_APPLICABLE','NOT_DISCLOSED','FETCH_FAILED','UNVERIFIED')),
    ADD COLUMN execution_start     date,
    ADD COLUMN execution_end       date,
    ADD COLUMN ownership_scope     text NOT NULL DEFAULT 'UNKNOWN' CHECK (ownership_scope IN (
        'ISSUER','SUBSIDIARY','JOINT_VENTURE','ASSOCIATE','UNKNOWN')),
    ADD COLUMN contradiction_status text NOT NULL DEFAULT 'NONE_KNOWN'
        CHECK (contradiction_status IN ('NONE_KNOWN','CONTRADICTED','UNRESOLVED')),
    ADD COLUMN supersedes_id       uuid REFERENCES event_versions,
    ADD COLUMN schema_version      text NOT NULL DEFAULT 'event_version.v1',
    ADD COLUMN created_by          text NOT NULL DEFAULT 'system',
    ADD COLUMN content_hash        text NOT NULL,
    ADD CONSTRAINT event_versions_novelty CHECK (novelty IN ('NEW','REVISION','REPETITION','HISTORY_UNAVAILABLE')),
    ADD CONSTRAINT event_versions_magnitude CHECK (
        (magnitude IS NULL AND magnitude_currency IS NULL AND magnitude_scale IS NULL)
        OR (magnitude IS NOT NULL AND magnitude_currency IS NOT NULL AND magnitude_scale IS NOT NULL)),
    ADD CONSTRAINT event_versions_magnitude_missing CHECK ((magnitude IS NULL) = (magnitude_missing_reason IS NOT NULL)),
    -- "up to" without a minimum and MOUs are never presented as firm amounts.
    ADD CONSTRAINT event_versions_unquantified_basis CHECK (magnitude IS NOT NULL OR amount_basis = 'UNQUANTIFIED'),
    ADD CONSTRAINT event_versions_execution CHECK (execution_end IS NULL OR execution_start IS NULL
                                                   OR execution_end >= execution_start);

ALTER TABLE evidence_links
    ADD COLUMN publication_id uuid REFERENCES document_publications,
    ADD COLUMN claim_id       text,                               -- owning claim in a research version
    ADD COLUMN relation       text NOT NULL DEFAULT 'SUPPORTS' CHECK (relation IN ('SUPPORTS','CONTRADICTS','CONTEXT')),
    ADD COLUMN created_by     text NOT NULL DEFAULT 'system',
    ADD CONSTRAINT evidence_links_owner CHECK (event_version_id IS NOT NULL OR claim_id IS NOT NULL);
CREATE TRIGGER evidence_links_append_only BEFORE UPDATE OR DELETE ON evidence_links
    FOR EACH ROW EXECUTE FUNCTION forbid_mutation();

-- ---------------------------------------------------------------------------
-- Candidate evaluation (sections 5, 18)
-- ---------------------------------------------------------------------------

ALTER TABLE candidate_evaluations
    ADD COLUMN policy_hash        text NOT NULL,
    ADD COLUMN trigger_event_version_ids uuid[] NOT NULL DEFAULT '{}',
    ADD COLUMN priority_class     text NOT NULL CHECK (priority_class IN ('U0','P1','P2','P3','D')),
    ADD COLUMN materiality        text NOT NULL DEFAULT 'MATERIALITY_UNKNOWN'
        CHECK (materiality IN ('MATERIAL_POTENTIAL','MATERIALITY_UNKNOWN','IMMATERIAL')),
    ADD COLUMN funding            text CHECK (funding IN ('FUNDED','UNRESOLVED','STRESSED')),
    ADD COLUMN coverage           jsonb NOT NULL DEFAULT '{}',
    ADD COLUMN queue_allocation   text NOT NULL DEFAULT 'NONE'
        CHECK (queue_allocation IN ('UPDATE','RANKED','EXPLORATION','AUDIT','NONE')),
    ADD COLUMN ranking_tuple      jsonb,
    ADD COLUMN schema_version     text NOT NULL DEFAULT 'candidate_evaluation.v1',
    ADD COLUMN created_by         text NOT NULL DEFAULT 'system',
    ADD COLUMN content_hash       text NOT NULL;

-- ---------------------------------------------------------------------------
-- Research queue, tasks, submissions
-- ---------------------------------------------------------------------------

ALTER TABLE research_cases DROP CONSTRAINT research_cases_workflow_state_check;
ALTER TABLE research_cases
    ADD CONSTRAINT research_cases_workflow_state_check CHECK (workflow_state IN (
        'QUEUED','TRIAGING','WATCH','RESEARCHING','AWAITING_INVESTMENT_POLICY','READY_FOR_INVESTOR_REVIEW',
        'REJECTED','DATA_REPAIR','DEFERRED','DEFERRED_BUDGET','STALE_UNRESEARCHED','CLOSED')),
    ADD COLUMN queue_entered_at        timestamptz NOT NULL DEFAULT now(),   -- kept across deferrals
    ADD COLUMN active_hypotheses       jsonb NOT NULL DEFAULT '[]',
    ADD COLUMN current_packet_hash     text,
    ADD COLUMN current_recommendation_id uuid;          -- FK added below, after recommendations change

ALTER TABLE research_tasks RENAME COLUMN retry_count TO attempt_count;
ALTER TABLE research_tasks DROP CONSTRAINT research_tasks_check;
ALTER TABLE research_tasks
    ADD COLUMN cutoff           timestamptz NOT NULL,
    ADD COLUMN lease_token      uuid,
    ADD COLUMN estimated_cost   numeric,
    ADD COLUMN actual_cost      numeric,
    ADD COLUMN cost_currency    text,
    ADD COLUMN idempotency_key  text UNIQUE,
    ADD CONSTRAINT research_tasks_lease
        CHECK ((status = 'CLAIMED') = (lease_owner IS NOT NULL AND lease_expires_at IS NOT NULL
                                       AND lease_token IS NOT NULL)),
    ADD CONSTRAINT research_tasks_cost_currency
        CHECK ((estimated_cost IS NULL AND actual_cost IS NULL) OR cost_currency IS NOT NULL);

ALTER TABLE research_submissions RENAME COLUMN expected_revision TO base_revision;
ALTER TABLE research_submissions DROP CONSTRAINT research_submissions_validation_status_check;
ALTER TABLE research_submissions
    ADD CONSTRAINT research_submissions_validation_status_check
        CHECK (validation_status IN ('PENDING','VALID','INVALID','CONFLICT')),   -- CONFLICT: expired lease / stale
    ADD COLUMN prior_submission_id uuid REFERENCES research_submissions,
    ADD COLUMN created_by       text NOT NULL DEFAULT 'system',
    ADD COLUMN content_hash     text NOT NULL;
CREATE TRIGGER research_submissions_append_only BEFORE DELETE ON research_submissions
    FOR EACH ROW EXECUTE FUNCTION forbid_mutation();

ALTER TABLE research_versions
    ADD COLUMN created_by   text NOT NULL DEFAULT 'system',
    ADD COLUMN content_hash text NOT NULL;

-- Section 17: tenant + operation + idempotency key for every write.  A retry with the same
-- key and body returns the stored response; the same key with a different body is refused.
CREATE TABLE idempotency_keys (
    tenant           text NOT NULL,
    operation        text NOT NULL,
    idempotency_key  text NOT NULL,
    request_sha256   text NOT NULL CHECK (request_sha256 ~ '^[0-9a-f]{64}$'),
    response         jsonb,
    created_at       timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant, operation, idempotency_key)
);

-- ---------------------------------------------------------------------------
-- Scenarios
-- ---------------------------------------------------------------------------

ALTER TABLE scenario_inputs DROP COLUMN unit;
ALTER TABLE scenario_inputs
    ADD COLUMN value_kind    text NOT NULL,
    ADD COLUMN currency      text,
    ADD COLUMN scale         text CHECK (scale IN ('UNITS','THOUSAND','LAKH','MILLION','CRORE','BILLION')),
    ADD COLUMN physical_unit text,
    ADD CONSTRAINT scenario_inputs_amount_shape CHECK (amount_shape_ok(value_kind, currency, scale, physical_unit));

ALTER TABLE scenario_outputs
    ADD COLUMN currency       text NOT NULL,
    ADD COLUMN schema_version text NOT NULL DEFAULT 'scenario_output.v1',
    ADD COLUMN created_by     text NOT NULL DEFAULT 'system';
CREATE TRIGGER scenario_outputs_append_only BEFORE UPDATE OR DELETE ON scenario_outputs
    FOR EACH ROW EXECUTE FUNCTION forbid_mutation();

-- ---------------------------------------------------------------------------
-- Recommendations and decisions
-- ---------------------------------------------------------------------------

ALTER TABLE recommendations RENAME COLUMN expires_at TO valid_until;
ALTER TABLE recommendations
    ADD COLUMN security_id        uuid REFERENCES securities,
    ADD COLUMN valuation_date     date,
    ADD COLUMN price_currency     text,
    ADD COLUMN scenario_output_ids uuid[] NOT NULL DEFAULT '{}',
    ADD COLUMN limitations        text[] NOT NULL DEFAULT '{}',
    ADD COLUMN validity_status    text NOT NULL DEFAULT 'VALID'
        CHECK (validity_status IN ('VALID','NEEDS_REVIEW','EXPIRED','SUPERSEDED')),
    ADD COLUMN schema_version     text NOT NULL DEFAULT 'recommendation.v1',
    ADD COLUMN created_by         text NOT NULL DEFAULT 'system',
    ADD COLUMN content_hash       text NOT NULL,
    ADD COLUMN revision           integer NOT NULL DEFAULT 1,
    -- Section 20: a price band needs validated scenarios, a priced security and a policy.
    ADD CONSTRAINT recommendations_band_requirements CHECK (state <> 'CONSIDER_WITHIN_PRICE_BAND' OR (
        security_id IS NOT NULL AND valuation_date IS NOT NULL AND price_basis IS NOT NULL
        AND price_currency IS NOT NULL AND cardinality(scenario_output_ids) > 0));

ALTER TABLE research_cases
    ADD CONSTRAINT research_cases_current_recommendation
        FOREIGN KEY (current_recommendation_id) REFERENCES recommendations;

ALTER TABLE investor_decisions RENAME COLUMN note TO rationale;
ALTER TABLE investor_decisions RENAME COLUMN actor TO investor_subject;   -- authenticated identity
ALTER TABLE investor_decisions
    ADD COLUMN approved_constraints jsonb NOT NULL DEFAULT '{}',
    ADD COLUMN auth_method          text NOT NULL,
    ADD COLUMN schema_version       text NOT NULL DEFAULT 'investor_decision.v1',
    ADD COLUMN content_hash         text NOT NULL;

-- ---------------------------------------------------------------------------
-- Milestones
-- ---------------------------------------------------------------------------

ALTER TABLE milestones
    ADD COLUMN event_id        uuid REFERENCES events,
    ADD COLUMN stream          text,
    ADD COLUMN original_expected_date date,
    ADD COLUMN due_window_start date,
    ADD COLUMN due_window_end   date,
    ADD COLUMN metric          text,
    ADD COLUMN operator        text CHECK (operator IN ('>=','<=','=','>','<')),
    ADD COLUMN target_value    numeric,
    ADD COLUMN evidence_needed text,
    ADD COLUMN next_check_at   timestamptz,
    ADD CONSTRAINT milestones_measurable CHECK ((metric IS NULL) = (operator IS NULL)
                                                AND (operator IS NULL) = (target_value IS NULL)),
    ADD CONSTRAINT milestones_window CHECK (due_window_end IS NULL OR due_window_start IS NULL
                                            OR due_window_end >= due_window_start);

-- ---------------------------------------------------------------------------
-- Budget reservations (section 17 budget_reservation; section 19 unresolved usage)
-- ---------------------------------------------------------------------------

ALTER TABLE budget_ledger DROP CONSTRAINT budget_ledger_status_check;
ALTER TABLE budget_ledger DROP CONSTRAINT budget_ledger_check;
ALTER TABLE budget_ledger
    ADD COLUMN task_id         uuid REFERENCES research_tasks,
    ADD COLUMN currency        text NOT NULL,
    ADD COLUMN pricing_version date NOT NULL,       -- model_prices.effective_from used for the estimate
    ADD COLUMN expires_at      timestamptz,
    -- UNRESOLVED: the call was dispatched but usage is unknown; the reservation keeps counting.
    ADD CONSTRAINT budget_ledger_status_check CHECK (status IN ('RESERVED','SETTLED','RELEASED','UNRESOLVED')),
    ADD CONSTRAINT budget_ledger_settled_actual CHECK ((status = 'SETTLED') = (actual_amount IS NOT NULL));

INSERT INTO schema_migrations (version) VALUES ('0002_spec17_alignment');

COMMIT;
