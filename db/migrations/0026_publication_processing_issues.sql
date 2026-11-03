-- A usable but incomplete publication can have processing issues without being FAILED.
-- Keep the existing failure_reason invariant; unread ZIP members are a distinct condition.
ALTER TABLE document_publications ADD COLUMN IF NOT EXISTS processing_issues text[] NOT NULL DEFAULT '{}';
DO $$ BEGIN
    IF NOT EXISTS(SELECT 1 FROM pg_constraint WHERE conname='document_publications_complete_members'
                  AND conrelid='document_publications'::regclass) THEN
        ALTER TABLE document_publications ADD CONSTRAINT document_publications_complete_members
            CHECK (pipeline_state<>'TEXT_READY' OR NOT ('ZIP_INCOMPLETE'=ANY(processing_issues))) NOT VALID;
    END IF;
END $$;
ALTER TABLE document_publications VALIDATE CONSTRAINT document_publications_complete_members;
INSERT INTO schema_migrations(version) VALUES('0026_publication_processing_issues') ON CONFLICT DO NOTHING;
