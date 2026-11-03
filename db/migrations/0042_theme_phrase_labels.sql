-- 0042: meaning labels for emergent-theme phrases (inflection.themes.labels). A local model answers once per phrase
-- whether it names a product, material, technology, sector or project type; answers are cached here (append-only,
-- one row per phrase and prompt version) so snapshots never call the model and every rerun reads the same labels.
-- A label is about what a word means, not about dates, so it does not break the point-in-time rule.
BEGIN;
CREATE TABLE theme_phrase_labels (
    prompt_version text NOT NULL,
    phrase         text NOT NULL,
    is_theme       boolean NOT NULL,
    answer         text NOT NULL,
    model          text NOT NULL,
    recorded_at    timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (prompt_version, phrase)
);
CREATE TRIGGER theme_phrase_labels_append_only BEFORE UPDATE OR DELETE ON theme_phrase_labels
    FOR EACH ROW EXECUTE FUNCTION forbid_mutation();
INSERT INTO schema_migrations (version) VALUES ('0042_theme_phrase_labels');
COMMIT;
