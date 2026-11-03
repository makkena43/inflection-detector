-- The existing pending index requires attachment_url and cannot serve all extraction jobs.
-- Keep this index small: it contains only the live downloaded-but-unread queue.
CREATE INDEX IF NOT EXISTS document_publications_downloaded_queue
    ON document_publications(published_at,publication_id) WHERE pipeline_state='DOWNLOADED';
INSERT INTO schema_migrations(version) VALUES('0024_downloaded_queue') ON CONFLICT DO NOTHING;
