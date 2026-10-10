-- Inflection detector: initial schema (spec section 8).
-- One physical PostgreSQL database with separate logical responsibilities:
--   source layer (identity, sources, documents, facts, prices)  ->  events
--   -> candidate evaluations  ->  research queue (admitted cases only)
--   -> research versions, scenarios  ->  recommendations  ->  human decisions.
--
-- Rules carried from the spec:
--   * identity, timestamps, evidence references, queue state and authorization are relational;
--     JSONB only for versioned research payloads and scenario inputs;
--   * mutable workflow rows carry a revision for optimistic checks;
--   * research, evaluations, decisions, facts and the audit log are append-only (triggers below);
--   * no ticker-only primary keys.
-- Enumerations mirror src/inflection/states.py (tests/test_schema.py checks they agree).

BEGIN;

CREATE TABLE schema_migrations (
    version     text PRIMARY KEY,
    applied_at  timestamptz NOT NULL DEFAULT now()
);

-- Refuses UPDATE and DELETE on append-only tables.
CREATE FUNCTION forbid_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION '% is append-only; % is not allowed', TG_TABLE_NAME, TG_OP
        USING ERRCODE = 'integrity_constraint_violation';
END $$;

-- ---------------------------------------------------------------------------
-- Identity and universe
-- ---------------------------------------------------------------------------

CREATE TABLE issuers (
    issuer_id        uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    legal_name       text NOT NULL,
    country          text NOT NULL DEFAULT 'IN',
    issuer_model     text NOT NULL DEFAULT 'UNKNOWN'
        CHECK (issuer_model IN ('OPERATING','BANK','INSURER','NBFC','INVESTMENT_COMPANY','UNKNOWN')),
    created_at       timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE securities (
    security_id      uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    issuer_id        uuid NOT NULL REFERENCES issuers,
    isin             text NOT NULL CHECK (isin ~ '^[A-Z]{2}[A-Z0-9]{9}[0-9]$'),
    instrument_type  text NOT NULL DEFAULT 'EQUITY',
    created_at       timestamptz NOT NULL DEFAULT now(),
    UNIQUE (isin)
);

-- Dated aliases: exchange symbol / scrip code / series / board over time.
CREATE TABLE identifier_history (
    identifier_id    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    security_id      uuid NOT NULL REFERENCES securities,
    exchange         text NOT NULL CHECK (exchange IN ('NSE','BSE')),
    kind             text NOT NULL CHECK (kind IN ('SYMBOL','SCRIP_CODE')),
    value            text NOT NULL,
    series           text,
    board            text NOT NULL DEFAULT 'UNKNOWN' CHECK (board IN ('MAINBOARD','SME','UNKNOWN')),
    listing_status   text NOT NULL DEFAULT 'LISTED'
        CHECK (listing_status IN ('LISTED','SUSPENDED','DELISTED','MIGRATED')),
    valid_from       date NOT NULL,
    valid_to         date,
    recorded_at      timestamptz NOT NULL DEFAULT now(),   -- when the system learned the mapping (replay)
    source           text NOT NULL,
    CHECK (valid_to IS NULL OR valid_to >= valid_from)
);
CREATE INDEX identifier_history_lookup ON identifier_history (exchange, kind, value, valid_from);

CREATE TABLE universe_membership (
    membership_id    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    universe_version text NOT NULL,
    security_id      uuid NOT NULL REFERENCES securities,
    inclusion_reason text NOT NULL,
    valid_from       date NOT NULL,
    valid_to         date,
    UNIQUE (universe_version, security_id)
);

-- ---------------------------------------------------------------------------
-- Sources and ingestion
-- ---------------------------------------------------------------------------

CREATE TABLE sources (
    source_id        uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name             text NOT NULL UNIQUE,
    kind             text NOT NULL,                 -- announcements, financials, prices, corporate_actions ...
    access_policy    text NOT NULL,                 -- licence / terms summary; reviewed in Phase 0
    access_reviewed_at timestamptz,
    enabled          boolean NOT NULL DEFAULT false -- off until access review is recorded
);

CREATE TABLE ingestion_runs (
    run_id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    source_id        uuid NOT NULL REFERENCES sources,
    window_start     timestamptz NOT NULL,
    window_end       timestamptz NOT NULL,
    cursor           jsonb,
    expected_count   integer,
    received_count   integer NOT NULL DEFAULT 0,
    coverage_status  text NOT NULL DEFAULT 'NOT_ATTEMPTED'
        CHECK (coverage_status IN ('COMPLETE','PARTIAL','EMPTY_UNVERIFIED','FAILED','NOT_ATTEMPTED')),
    error_class      text,
    started_at       timestamptz NOT NULL DEFAULT now(),
    finished_at      timestamptz,
    next_retry_at    timestamptz,
    CHECK (window_end > window_start)
);

-- ---------------------------------------------------------------------------
-- Documents and text
-- ---------------------------------------------------------------------------

CREATE TABLE documents (
    document_id      uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    issuer_id        uuid REFERENCES issuers,       -- NULL until identity is resolved
    kind             text NOT NULL DEFAULT 'UNKNOWN',
    created_at       timestamptz NOT NULL DEFAULT now()
);

-- One row per distinct byte content of a document (re-filings are new versions, never overwrites).
CREATE TABLE document_versions (
    document_version_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id      uuid NOT NULL REFERENCES documents,
    sha256           text NOT NULL CHECK (sha256 ~ '^[0-9a-f]{64}$'),
    storage_key      text NOT NULL,
    byte_size        bigint NOT NULL CHECK (byte_size >= 0),
    media_type       text NOT NULL,
    supersedes_id    uuid REFERENCES document_versions,
    created_at       timestamptz NOT NULL DEFAULT now(),
    UNIQUE (document_id, sha256)
);

-- Where and when a version was published.  published_at is the proven dissemination time;
-- date-only publications are recorded as such and are not tradable at that day's close.
CREATE TABLE document_publications (
    publication_id   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    document_version_id uuid NOT NULL REFERENCES document_versions,
    source_id        uuid NOT NULL REFERENCES sources,
    external_id      text NOT NULL,
    external_version text NOT NULL DEFAULT '',
    source_url       text NOT NULL,
    published_at     timestamptz,
    published_date_only date,
    timestamp_basis  text NOT NULL
        CHECK (timestamp_basis IN ('EXCHANGE_TIMESTAMP','DATE_ONLY','UNKNOWN')),
    ingested_at      timestamptz NOT NULL DEFAULT now(),
    ingestion_run_id uuid REFERENCES ingestion_runs,
    UNIQUE (source_id, external_id, external_version),
    CHECK ((timestamp_basis = 'EXCHANGE_TIMESTAMP') = (published_at IS NOT NULL)),
    CHECK ((timestamp_basis = 'DATE_ONLY') = (published_date_only IS NOT NULL))
);

CREATE TABLE text_artifacts (
    text_artifact_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    document_version_id uuid NOT NULL REFERENCES document_versions,
    extraction_method text NOT NULL,
    extraction_version text NOT NULL,
    status           text NOT NULL CHECK (status IN (
        'COMPLETE','PARTIAL','OCR_REQUIRED','PARSE_FAILED_RETRYABLE','ENCRYPTED','EMPTY',
        'UNSUPPORTED_FORMAT','RESOURCE_LIMIT')),
    pages_expected   integer,
    pages_processed  integer NOT NULL DEFAULT 0,
    pages_with_text  integer NOT NULL DEFAULT 0,
    text_sha256      text,
    storage_key      text,                          -- page-preserving text; pages separated by form feed
    quality_issues   text[] NOT NULL DEFAULT '{}',
    created_at       timestamptz NOT NULL DEFAULT now(),
    UNIQUE (document_version_id, extraction_method, extraction_version)
);
CREATE TRIGGER text_artifacts_append_only BEFORE UPDATE OR DELETE ON text_artifacts
    FOR EACH ROW EXECUTE FUNCTION forbid_mutation();

-- Page text for full-text search (spec section 10: PostgreSQL full-text first, no embeddings by default).
CREATE TABLE text_pages (
    text_artifact_id uuid NOT NULL REFERENCES text_artifacts,
    page_no          integer NOT NULL CHECK (page_no >= 1),
    body             text NOT NULL,
    tsv              tsvector GENERATED ALWAYS AS (to_tsvector('english', body)) STORED,
    PRIMARY KEY (text_artifact_id, page_no)
);
CREATE INDEX text_pages_tsv ON text_pages USING gin (tsv);

-- ---------------------------------------------------------------------------
-- Financial facts, prices, corporate actions (versioned, never overwritten)
-- ---------------------------------------------------------------------------

CREATE TABLE financial_facts (
    fact_id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    issuer_id        uuid NOT NULL REFERENCES issuers,
    metric           text NOT NULL,
    period_start     date,
    period_end       date NOT NULL,
    scope            text NOT NULL CHECK (scope IN ('CONSOLIDATED','STANDALONE','SEGMENT','UNKNOWN')),
    segment          text,
    value            numeric NOT NULL,
    unit             text NOT NULL,
    available_at     timestamptz,                   -- NULL = provenance unknown: screening context only
    provider         text NOT NULL,
    provider_version text NOT NULL,
    document_version_id uuid REFERENCES document_versions,
    supersedes_id    uuid REFERENCES financial_facts,
    recorded_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX financial_facts_lookup ON financial_facts (issuer_id, metric, period_end);
CREATE TRIGGER financial_facts_append_only BEFORE UPDATE OR DELETE ON financial_facts
    FOR EACH ROW EXECUTE FUNCTION forbid_mutation();

CREATE TABLE prices (
    security_id      uuid NOT NULL REFERENCES securities,
    trade_date       date NOT NULL,
    provider         text NOT NULL,
    provider_version text NOT NULL,
    open             numeric, high numeric, low numeric,
    close            numeric NOT NULL,
    volume           numeric,
    adjustment       text NOT NULL CHECK (adjustment IN ('UNADJUSTED','SPLIT_BONUS_ADJUSTED','TOTAL_RETURN')),
    recorded_at      timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (security_id, trade_date, provider, provider_version, adjustment)
);

CREATE TABLE corporate_actions (
    action_id        uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    security_id      uuid NOT NULL REFERENCES securities,
    kind             text NOT NULL,                 -- SPLIT, BONUS, DIVIDEND, RIGHTS, MERGER, DELISTING ...
    ex_date          date NOT NULL,
    details          jsonb NOT NULL,
    provider         text NOT NULL,
    provider_version text NOT NULL,
    reconciled       boolean NOT NULL DEFAULT false,-- unreconciled actions make returns UNVERIFIED
    recorded_at      timestamptz NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------------
-- Events and evidence
-- ---------------------------------------------------------------------------

CREATE TABLE events (
    event_id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    issuer_id        uuid NOT NULL REFERENCES issuers,
    created_at       timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE event_versions (
    event_version_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    event_id         uuid NOT NULL REFERENCES events,
    version_no       integer NOT NULL CHECK (version_no >= 1),
    stream           text,
    facility         text,
    counterparty     text,
    stage            text NOT NULL,
    magnitude        numeric,
    magnitude_unit   text,
    deadline         date,
    novelty          text,
    duplicate_of     uuid REFERENCES events,
    recorded_at      timestamptz NOT NULL DEFAULT now(),
    UNIQUE (event_id, version_no),
    CHECK ((magnitude IS NULL) = (magnitude_unit IS NULL))
);
CREATE TRIGGER event_versions_append_only BEFORE UPDATE OR DELETE ON event_versions
    FOR EACH ROW EXECUTE FUNCTION forbid_mutation();

-- Evidence reference contract: exact span on a page of a specific text artifact.
CREATE TABLE evidence_links (
    evidence_id      uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    document_version_id uuid NOT NULL REFERENCES document_versions,
    text_artifact_id uuid NOT NULL REFERENCES text_artifacts,
    page_no          integer NOT NULL CHECK (page_no >= 1),
    section          text,
    span_start       integer NOT NULL CHECK (span_start >= 0),
    span_end         integer NOT NULL,
    quote            text NOT NULL CHECK (length(quote) > 0),
    source_url       text NOT NULL,
    published_at     timestamptz NOT NULL,
    assertion_type   text NOT NULL CHECK (assertion_type IN (
        'REPORTED_FACT','MANAGEMENT_STATEMENT','COMMERCIAL_COMMITMENT','THIRD_PARTY_STATEMENT')),
    event_version_id uuid REFERENCES event_versions,
    created_at       timestamptz NOT NULL DEFAULT now(),
    CHECK (span_end > span_start)
);

-- ---------------------------------------------------------------------------
-- Candidate evaluation (append-only) and research queue (admitted cases only)
-- ---------------------------------------------------------------------------

CREATE TABLE candidate_evaluations (
    evaluation_id    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id           uuid NOT NULL,
    issuer_id        uuid NOT NULL REFERENCES issuers,
    as_of            timestamptz NOT NULL,
    mode             text NOT NULL CHECK (mode IN ('LIVE','PUBLIC_INFORMATION_RECONSTRUCTION','ACTUAL_SYSTEM_REPLAY')),
    policy_version   text NOT NULL,
    route            text NOT NULL,
    components       jsonb NOT NULL,
    outcome          text NOT NULL CHECK (outcome IN ('ADMIT','DEFER','REJECT')),
    reasons          text[] NOT NULL,
    queue_priority   numeric,
    created_at       timestamptz NOT NULL DEFAULT now(),
    CHECK (cardinality(reasons) > 0)
);
CREATE TRIGGER candidate_evaluations_append_only BEFORE UPDATE OR DELETE ON candidate_evaluations
    FOR EACH ROW EXECUTE FUNCTION forbid_mutation();

CREATE TABLE research_cases (
    case_id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    issuer_id        uuid NOT NULL REFERENCES issuers,
    admitted_by      uuid NOT NULL REFERENCES candidate_evaluations,
    workflow_state   text NOT NULL DEFAULT 'QUEUED' CHECK (workflow_state IN (
        'QUEUED','TRIAGING','WATCH','RESEARCHING','AWAITING_INVESTMENT_POLICY','READY_FOR_INVESTOR_REVIEW',
        'REJECTED','DATA_REPAIR','DEFERRED','DEFERRED_BUDGET','CLOSED')),
    business_state   text NOT NULL DEFAULT 'UNKNOWN' CHECK (business_state IN (
        'EMERGING','COMMERCIALLY_VALIDATED','SCALING','DETERIORATING','UNKNOWN')),
    cutoff           timestamptz NOT NULL,
    next_review_at   timestamptz,
    revision         integer NOT NULL DEFAULT 1,
    created_at       timestamptz NOT NULL DEFAULT now(),
    updated_at       timestamptz NOT NULL DEFAULT now()
);
-- At most one open case per issuer.
CREATE UNIQUE INDEX research_cases_one_open ON research_cases (issuer_id)
    WHERE workflow_state NOT IN ('REJECTED','CLOSED');

CREATE TABLE research_tasks (
    task_id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    case_id          uuid NOT NULL REFERENCES research_cases,
    task_type        text NOT NULL,
    status           text NOT NULL DEFAULT 'OPEN' CHECK (status IN ('OPEN','CLAIMED','COMPLETED','CANCELLED')),
    packet_hash      text,
    lease_owner      text,
    lease_expires_at timestamptz,
    base_revision    integer NOT NULL,
    retry_count      integer NOT NULL DEFAULT 0 CHECK (retry_count BETWEEN 0 AND 2),
    revision         integer NOT NULL DEFAULT 1,
    created_at       timestamptz NOT NULL DEFAULT now(),
    CHECK ((status = 'CLAIMED') = (lease_owner IS NOT NULL AND lease_expires_at IS NOT NULL))
);
CREATE UNIQUE INDEX research_tasks_one_active ON research_tasks (case_id, task_type)
    WHERE status IN ('OPEN','CLAIMED');

-- Every submission is stored, including ones that fail validation.
CREATE TABLE research_submissions (
    submission_id    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    task_id          uuid NOT NULL REFERENCES research_tasks,
    packet_hash      text NOT NULL,
    expected_revision integer NOT NULL,
    idempotency_key  text NOT NULL UNIQUE,
    schema_version   text NOT NULL,
    payload          jsonb NOT NULL,
    author_kind      text NOT NULL CHECK (author_kind IN ('MODEL','ANALYST')),
    author_identity  text NOT NULL,                 -- model + prompt version, or analyst id
    validation_status text NOT NULL CHECK (validation_status IN ('PENDING','VALID','INVALID')),
    validation_errors jsonb NOT NULL DEFAULT '[]',
    created_at       timestamptz NOT NULL DEFAULT now()
);

-- Only validated submissions become research versions.
CREATE TABLE research_versions (
    research_version_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    case_id          uuid NOT NULL REFERENCES research_cases,
    submission_id    uuid NOT NULL UNIQUE REFERENCES research_submissions,
    version_no       integer NOT NULL,
    schema_version   text NOT NULL,
    payload          jsonb NOT NULL,
    source_manifest  jsonb NOT NULL,
    created_at       timestamptz NOT NULL DEFAULT now(),
    UNIQUE (case_id, version_no)
);
CREATE TRIGGER research_versions_append_only BEFORE UPDATE OR DELETE ON research_versions
    FOR EACH ROW EXECUTE FUNCTION forbid_mutation();

-- ---------------------------------------------------------------------------
-- Scenarios (deterministic engine output)
-- ---------------------------------------------------------------------------

CREATE TABLE scenario_inputs (
    input_id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    research_version_id uuid NOT NULL REFERENCES research_versions,
    stream           text NOT NULL,
    period           text NOT NULL,
    scenario         text NOT NULL CHECK (scenario IN ('DOWNSIDE','BASE','UPSIDE')),
    name             text NOT NULL,
    value            numeric NOT NULL,
    low              numeric,
    high             numeric,
    unit             text NOT NULL,
    status           text NOT NULL CHECK (status IN ('OBSERVED','MANAGEMENT_GUIDANCE','ANALYST_ASSUMPTION','DERIVED')),
    evidence_ids     uuid[] NOT NULL DEFAULT '{}',
    rationale        text,
    -- An observed value must cite evidence; assumptions must not pretend to.
    CHECK (status <> 'OBSERVED' OR cardinality(evidence_ids) > 0),
    CHECK (low IS NULL OR high IS NULL OR low <= high),
    UNIQUE (research_version_id, stream, period, scenario, name)
);

CREATE TABLE scenario_outputs (
    output_id        uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    research_version_id uuid NOT NULL REFERENCES research_versions,
    engine_version   text NOT NULL,
    inputs_hash      text NOT NULL,
    scenario         text NOT NULL CHECK (scenario IN ('DOWNSIDE','BASE','UPSIDE')),
    period           text NOT NULL,
    result           jsonb NOT NULL,
    created_at       timestamptz NOT NULL DEFAULT now(),
    UNIQUE (research_version_id, engine_version, inputs_hash, scenario, period)
);

-- ---------------------------------------------------------------------------
-- Investor policy, recommendations, decisions
-- ---------------------------------------------------------------------------

-- Required before READY_FOR_INVESTOR_REVIEW.  No defaults: every limit must be set by the investor.
CREATE TABLE investment_policies (
    policy_version   text PRIMARY KEY,
    return_hurdle_pct numeric NOT NULL,
    max_downside_pct numeric NOT NULL,
    max_position_pct numeric NOT NULL,
    min_liquidity    jsonb NOT NULL,
    portfolio_constraints jsonb NOT NULL,
    set_by           text NOT NULL,
    effective_from   timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE recommendations (
    recommendation_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    case_id          uuid NOT NULL REFERENCES research_cases,
    research_version_id uuid NOT NULL REFERENCES research_versions,
    state            text NOT NULL CHECK (state IN (
        'CONSIDER_WITHIN_PRICE_BAND','WATCH_MILESTONE','PASS_VALUATION','PASS_RISK',
        'INSUFFICIENT_EVIDENCE','REVIEW_EXISTING_POSITION')),
    price_basis      numeric,
    price_date       date NOT NULL,
    band_low         numeric,
    band_high        numeric,
    horizon_months   integer,
    policy_version   text REFERENCES investment_policies,
    expires_at       timestamptz NOT NULL,
    superseded_by    uuid REFERENCES recommendations,
    created_at       timestamptz NOT NULL DEFAULT now(),
    CHECK (state <> 'CONSIDER_WITHIN_PRICE_BAND'
           OR (band_low IS NOT NULL AND band_high IS NOT NULL AND band_low <= band_high
               AND policy_version IS NOT NULL AND horizon_months IS NOT NULL))
);

-- Signed human decisions only; never written by a model tool.
CREATE TABLE investor_decisions (
    decision_id      uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    recommendation_id uuid NOT NULL REFERENCES recommendations,
    decision         text NOT NULL CHECK (decision IN (
        'NOT_REVIEWED','APPROVED','CHANGES_REQUESTED','DECLINED','DEFERRED','REVOKED')),
    actor            text NOT NULL,
    note             text,
    decided_at       timestamptz NOT NULL DEFAULT now()
);
CREATE TRIGGER investor_decisions_append_only BEFORE UPDATE OR DELETE ON investor_decisions
    FOR EACH ROW EXECUTE FUNCTION forbid_mutation();

-- ---------------------------------------------------------------------------
-- Milestones, guidance history, counterparties
-- ---------------------------------------------------------------------------

CREATE TABLE milestones (
    milestone_id     uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    case_id          uuid NOT NULL REFERENCES research_cases,
    description      text NOT NULL,
    original_promise_evidence uuid REFERENCES evidence_links,
    deadline         date,
    status           text NOT NULL DEFAULT 'PENDING' CHECK (status IN ('PENDING','MET','MISSED','REVISED','CANCELLED')),
    observed_outcome text,
    outcome_evidence uuid REFERENCES evidence_links,
    next_trigger     text,
    revision         integer NOT NULL DEFAULT 1
);

CREATE TABLE guidance_history (
    guidance_id      uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    issuer_id        uuid NOT NULL REFERENCES issuers,
    metric           text NOT NULL,
    target_period    text NOT NULL,
    target_value     numeric,
    target_low       numeric,
    target_high      numeric,
    unit             text NOT NULL,
    evidence_id      uuid NOT NULL REFERENCES evidence_links,
    revises_id       uuid REFERENCES guidance_history,
    revision_explanation text,
    stated_at        timestamptz NOT NULL
);

CREATE TABLE counterparty_assessments (
    assessment_id    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    case_id          uuid NOT NULL REFERENCES research_cases,
    counterparty     text NOT NULL,
    relationship     text NOT NULL CHECK (relationship IN (
        'CONFIRMED_RELATED','ISSUER_ASSERTED_UNRELATED','INDEPENDENTLY_SUPPORTED_UNRELATED','UNKNOWN')),
    commitment       text NOT NULL CHECK (commitment IN ('BINDING','PROVISIONAL','NON_BINDING','NOT_APPLICABLE')),
    evidence_ids     uuid[] NOT NULL DEFAULT '{}',
    corroboration_note text,                        -- "customer corroboration unavailable" is a valid answer
    assessed_at      timestamptz NOT NULL DEFAULT now(),
    CHECK (relationship NOT IN ('CONFIRMED_RELATED','INDEPENDENTLY_SUPPORTED_UNRELATED')
           OR cardinality(evidence_ids) > 0)
);

-- ---------------------------------------------------------------------------
-- Budget, audit, outcomes
-- ---------------------------------------------------------------------------

-- Monthly budget set by the investor.  Paid calls default OFF.
CREATE TABLE budgets (
    budget_month     date PRIMARY KEY CHECK (extract(day FROM budget_month) = 1),
    currency         text NOT NULL,
    limit_amount     numeric NOT NULL CHECK (limit_amount >= 0),
    paid_calls_enabled boolean NOT NULL DEFAULT false,
    set_by           text NOT NULL,
    set_at           timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE model_prices (
    provider         text NOT NULL,
    model            text NOT NULL,
    currency         text NOT NULL,
    input_per_mtok   numeric NOT NULL CHECK (input_per_mtok >= 0),
    output_per_mtok  numeric NOT NULL CHECK (output_per_mtok >= 0),
    cache_read_per_mtok numeric,
    effective_from   date NOT NULL,
    source           text NOT NULL,
    PRIMARY KEY (provider, model, effective_from)
);

CREATE TABLE budget_ledger (
    entry_id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    budget_month     date NOT NULL REFERENCES budgets,
    case_id          uuid REFERENCES research_cases,
    provider         text NOT NULL,
    model            text NOT NULL,
    status           text NOT NULL CHECK (status IN ('RESERVED','SETTLED','RELEASED')),
    reserved_amount  numeric NOT NULL CHECK (reserved_amount >= 0),
    actual_amount    numeric,
    input_tokens     integer,
    output_tokens    integer,
    fee_breakdown    jsonb,
    created_at       timestamptz NOT NULL DEFAULT now(),
    settled_at       timestamptz,
    CHECK ((status = 'SETTLED') = (actual_amount IS NOT NULL))
);

CREATE TABLE audit_log (
    audit_id         bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    actor            text NOT NULL,
    actor_kind       text NOT NULL CHECK (actor_kind IN ('HUMAN','MODEL','SYSTEM')),
    action           text NOT NULL,
    target_table     text,
    target_id        text,
    details          jsonb NOT NULL DEFAULT '{}',
    at               timestamptz NOT NULL DEFAULT now()
);
CREATE TRIGGER audit_log_append_only BEFORE UPDATE OR DELETE ON audit_log
    FOR EACH ROW EXECUTE FUNCTION forbid_mutation();

-- Future outcomes, kept out of analyst-facing views to limit hindsight bias.
CREATE SCHEMA outcomes;
CREATE TABLE outcomes.evaluation_outcomes (
    outcome_id       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    case_id          uuid NOT NULL REFERENCES research_cases,
    measured_at      timestamptz NOT NULL,
    horizon_months   integer NOT NULL,
    metric           text NOT NULL,
    value            numeric,
    verification     text NOT NULL CHECK (verification IN ('VERIFIED','UNVERIFIED')),
    notes            text
);

INSERT INTO schema_migrations (version) VALUES ('0001_init');

COMMIT;
