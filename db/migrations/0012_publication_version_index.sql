-- Publications by archived document version.  The commercial scan looks up, for every text
-- artifact, the earliest publication of its document; without this index that lookup scans all
-- publications once per artifact (minutes per run once announcements are backfilled).
CREATE INDEX IF NOT EXISTS document_publications_version
    ON document_publications (document_version_id) WHERE document_version_id IS NOT NULL;

INSERT INTO schema_migrations (version) VALUES ('0012_publication_version_index');
