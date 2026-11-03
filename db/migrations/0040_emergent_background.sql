-- 0040: background phrase frequencies for emergent themes (inflection.themes.emergent, version emergent-3).
-- A phrase is a theme candidate only when it is much more common in order / capacity / launch passages than in
-- ordinary filing sentences. The ordinary-sentence counts come from a fixed sample of filings that have no
-- commercial passage, built once per method version by `python -m inflection.themes emergent-background`.
BEGIN;

CREATE TABLE theme_background_runs (
    version      text PRIMARY KEY,
    built_from   date NOT NULL,
    built_to     date NOT NULL,
    documents    integer NOT NULL,
    sentences    bigint NOT NULL,
    recorded_at  timestamptz NOT NULL DEFAULT now()
);
CREATE TRIGGER theme_background_runs_append_only BEFORE UPDATE OR DELETE ON theme_background_runs
    FOR EACH ROW EXECUTE FUNCTION forbid_mutation();

CREATE TABLE theme_phrase_background (
    version    text NOT NULL REFERENCES theme_background_runs,
    phrase     text NOT NULL,
    sentences  integer NOT NULL,                -- background sentences containing the phrase
    PRIMARY KEY (version, phrase)
);
CREATE TRIGGER theme_phrase_background_append_only BEFORE UPDATE OR DELETE ON theme_phrase_background
    FOR EACH ROW EXECUTE FUNCTION forbid_mutation();

INSERT INTO schema_migrations (version) VALUES ('0040_emergent_background');
COMMIT;
