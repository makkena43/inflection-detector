-- 0037: MakroGraph India supply-gap themes, carried over and kept up to date.
--
-- theme_beneficiaries: one row per (source, as_of_date, theme, company). A row says "on as_of_date, from filings dated in
-- the lookback window before it, this company looked like a supplier to this constrained product". Rows are never
-- changed: a later run writes a later as_of_date, so a packet built for any past cutoff reads only what was known then.
--   source 'makrograph' = copied once from makrograph.mg_india_beneficiaries (year-ends 2020-2025, June/July 2026).
--   source 'inflection' = computed here by inflection.themes with the same MakroGraph code (vendored verbatim).
-- theme_catalog: theme name -> constrained product, the theme list later runs use.
-- theme_document_tags: per filing, the MakroGraph signal counts and theme entities found in its text.
-- theme_snapshots: MakroGraph's monthly India theme strength/momentum (Jan 2020 - Jun 2026), kept as frozen history.
BEGIN;

CREATE TABLE theme_catalog (
    theme_name          text PRIMARY KEY,
    constrained_product text NOT NULL,
    source              text NOT NULL,
    first_as_of         date,
    recorded_at         timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE theme_document_tags (
    publication_id  uuid PRIMARY KEY REFERENCES document_publications,
    issuer_id       uuid NOT NULL REFERENCES issuers,
    filed_ist       timestamp NOT NULL,             -- IST wall clock, as MakroGraph compared filed_at with dates
    signal_counts   jsonb NOT NULL,                 -- {signal_type: n} after MakroGraph's own de-duplication and caps
    entities        text[] NOT NULL,                -- lowercase theme entity names found (MakroGraph mg_document_entities)
    tagger_version  text NOT NULL,
    recorded_at     timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX theme_document_tags_filed ON theme_document_tags (filed_ist);
CREATE INDEX theme_document_tags_entities ON theme_document_tags USING gin (entities);
CREATE TRIGGER theme_document_tags_append_only BEFORE UPDATE OR DELETE ON theme_document_tags
    FOR EACH ROW EXECUTE FUNCTION forbid_mutation();

CREATE TABLE theme_beneficiaries (
    row_id                bigserial PRIMARY KEY,
    source                text NOT NULL CHECK (source IN ('makrograph', 'inflection')),
    as_of_date            date NOT NULL,
    lookback_days         integer,                  -- NULL for MakroGraph's live (non year-end) runs: not recorded there
    theme_name            text NOT NULL,
    constrained_product   text,
    supply_chain_node     text,
    supply_chain_stage    integer,
    role                  text,
    conviction_score      numeric NOT NULL,
    signal_count          integer,
    capex_signals         integer,
    supply_signals        integer,
    has_order_book        boolean,
    import_substitution   boolean,
    rationale             text,
    company               text NOT NULL,
    ticker                text,                     -- NSE symbol at the time (match against identifier_history)
    issuer_id             uuid REFERENCES issuers,  -- set when the row was written; NULL when the ticker did not resolve
    source_row_id         bigint,                   -- mg_india_beneficiaries.id for copied rows
    recorded_at           timestamptz NOT NULL DEFAULT now(),
    UNIQUE (source, as_of_date, theme_name, company)
);
CREATE INDEX theme_beneficiaries_ticker ON theme_beneficiaries (upper(ticker), as_of_date);
CREATE INDEX theme_beneficiaries_issuer ON theme_beneficiaries (issuer_id, as_of_date);
CREATE TRIGGER theme_beneficiaries_append_only BEFORE UPDATE OR DELETE ON theme_beneficiaries
    FOR EACH ROW EXECUTE FUNCTION forbid_mutation();

CREATE TABLE theme_snapshots (
    source          text NOT NULL DEFAULT 'makrograph',
    theme_slug      text NOT NULL,
    theme_name      text NOT NULL,
    snapshot_date   date NOT NULL,
    strength_score  double precision,
    momentum_score  double precision,
    doc_count       integer,
    company_count   integer,
    top_entities    jsonb,
    conviction      text,                           -- mg_themes.conviction at copy time (latest state, not dated)
    recorded_at     timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (source, theme_slug, snapshot_date)
);
CREATE TRIGGER theme_snapshots_append_only BEFORE UPDATE OR DELETE ON theme_snapshots
    FOR EACH ROW EXECUTE FUNCTION forbid_mutation();

INSERT INTO schema_migrations (version) VALUES ('0037_theme_beneficiaries');
COMMIT;
