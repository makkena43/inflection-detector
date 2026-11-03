-- 0038: emergent themes discovered from inflection's own commercial passages (inflection.themes.emergent).
-- theme_phrase_mentions: key phrases of each order / capacity / launch passage (one row per publication + quote).
-- emergent_theme_snapshots / emergent_theme_companies: one weekly snapshot per as_of, computed only from passages
-- published before it; append-only so any past packet reads what was known then.
BEGIN;

CREATE TABLE theme_phrase_mentions (
    row_id        bigserial PRIMARY KEY,
    mention_id    uuid NOT NULL REFERENCES commercial_mentions,
    issuer_id     uuid NOT NULL REFERENCES issuers,
    source_key    text NOT NULL,                    -- publication_id, or document_version_id when there is none
    quote_md5     text NOT NULL,
    published_at  timestamptz NOT NULL,
    family        text NOT NULL,
    phrases       text[] NOT NULL,
    value_cr      numeric,                          -- INR crore, firm / executable / guaranteed amounts only
    version       text NOT NULL,
    recorded_at   timestamptz NOT NULL DEFAULT now(),
    UNIQUE (issuer_id, source_key, quote_md5)
);
CREATE INDEX theme_phrase_mentions_published ON theme_phrase_mentions (published_at);
CREATE TRIGGER theme_phrase_mentions_append_only BEFORE UPDATE OR DELETE ON theme_phrase_mentions
    FOR EACH ROW EXECUTE FUNCTION forbid_mutation();

CREATE TABLE emergent_theme_snapshots (
    as_of           date NOT NULL,
    theme_key       text NOT NULL,                  -- stable across snapshots while the theme's phrases overlap
    name            text NOT NULL,
    phrases         text[] NOT NULL,
    companies       integer NOT NULL,               -- distinct companies in the last 180 days
    companies_prior integer NOT NULL,               -- same 180 days a year earlier
    growth_pct      numeric,
    order_value_cr  numeric NOT NULL,
    stage           integer NOT NULL CHECK (stage BETWEEN 0 AND 5),
    first_detected  date NOT NULL,
    version         text NOT NULL,
    recorded_at     timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (as_of, theme_key)
);
CREATE TRIGGER emergent_theme_snapshots_append_only BEFORE UPDATE OR DELETE ON emergent_theme_snapshots
    FOR EACH ROW EXECUTE FUNCTION forbid_mutation();

CREATE TABLE emergent_theme_companies (
    as_of       date NOT NULL,
    theme_key   text NOT NULL,
    issuer_id   uuid NOT NULL REFERENCES issuers,
    mentions    integer NOT NULL,
    value_cr    numeric NOT NULL,
    first_seen  date NOT NULL,
    recorded_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (as_of, theme_key, issuer_id),
    FOREIGN KEY (as_of, theme_key) REFERENCES emergent_theme_snapshots (as_of, theme_key)
);
CREATE INDEX emergent_theme_companies_issuer ON emergent_theme_companies (issuer_id, as_of);
CREATE TRIGGER emergent_theme_companies_append_only BEFORE UPDATE OR DELETE ON emergent_theme_companies
    FOR EACH ROW EXECUTE FUNCTION forbid_mutation();

INSERT INTO schema_migrations (version) VALUES ('0038_emergent_themes');
COMMIT;
