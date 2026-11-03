-- 0039: emergent themes are versioned. A new phrase method re-indexes passages under its own version, and
-- snapshots/readers only look at their own version, so rows from an earlier method stay (append-only) but are ignored.
BEGIN;
ALTER TABLE theme_phrase_mentions DROP CONSTRAINT theme_phrase_mentions_issuer_id_source_key_quote_md5_key;
ALTER TABLE theme_phrase_mentions ADD CONSTRAINT theme_phrase_mentions_version_key
    UNIQUE (version, issuer_id, source_key, quote_md5);
CREATE INDEX emergent_theme_snapshots_version ON emergent_theme_snapshots (version, as_of);
INSERT INTO schema_migrations (version) VALUES ('0039_emergent_versions');
COMMIT;
