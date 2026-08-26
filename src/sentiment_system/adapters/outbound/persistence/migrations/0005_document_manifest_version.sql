ALTER TABLE source_documents
    ADD COLUMN manifest_version text NOT NULL DEFAULT 'unspecified';
