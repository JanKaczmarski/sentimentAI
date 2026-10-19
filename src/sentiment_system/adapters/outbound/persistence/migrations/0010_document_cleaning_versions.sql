-- Preserve original source revisions across immutable cleaning materializations.
ALTER TABLE source_documents
    DROP CONSTRAINT source_documents_source_revision_key;

ALTER TABLE source_documents
    ADD CONSTRAINT source_documents_source_revision_key
    UNIQUE (source, source_id, source_raw_sha256, manifest_version);
