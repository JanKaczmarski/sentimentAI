ALTER TABLE source_documents
    DROP CONSTRAINT source_documents_source_source_id_key;

ALTER TABLE source_documents
    ADD COLUMN manifest_provenance jsonb NOT NULL DEFAULT '{}'::jsonb;

ALTER TABLE source_documents
    ADD CONSTRAINT source_documents_source_revision_key
    UNIQUE (source, source_id, raw_content_sha256);
