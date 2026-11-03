-- Match the dated pending-work query, including date-only source publications.
CREATE INDEX IF NOT EXISTS document_publications_attachment_queue
    ON document_publications(source_id,
        (coalesce(published_at,published_date::timestamp AT TIME ZONE 'Asia/Kolkata')),first_seen_at)
    WHERE attachment_url IS NOT NULL AND pipeline_state IN ('DISCOVERED','FAILED');
INSERT INTO schema_migrations(version) VALUES('0025_attachment_repair_queue') ON CONFLICT DO NOTHING;
