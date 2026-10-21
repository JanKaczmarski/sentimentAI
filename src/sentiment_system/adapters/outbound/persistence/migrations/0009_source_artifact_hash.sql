ALTER TABLE source_documents
    DROP CONSTRAINT source_documents_source_revision_key;

ALTER TABLE source_documents
    ADD COLUMN source_raw_sha256 char(64);

UPDATE source_documents
    SET source_raw_sha256 = raw_content_sha256;

ALTER TABLE source_documents
    ALTER COLUMN source_raw_sha256 SET NOT NULL;

ALTER TABLE source_documents
    ADD CONSTRAINT source_documents_source_revision_key
    UNIQUE (source, source_id, source_raw_sha256);
