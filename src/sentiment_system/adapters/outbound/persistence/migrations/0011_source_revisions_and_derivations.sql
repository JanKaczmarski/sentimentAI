-- Original artifacts and their immutable text derivations are distinct identities.
-- Keep every legacy document/chunk ID and all foreign-key references intact.
ALTER TABLE source_documents DROP CONSTRAINT source_documents_source_revision_key;
ALTER TABLE source_documents ADD COLUMN legacy_source_raw_sha256 char(64);
UPDATE source_documents SET legacy_source_raw_sha256 = source_raw_sha256;
ALTER TABLE source_documents ALTER COLUMN source_raw_sha256 DROP NOT NULL;

-- 0009 copied text hashes even for PDF-extracted text. Only manifest provenance
-- can establish original-byte identity without consulting verified source files.
UPDATE source_documents SET source_raw_sha256 = CASE
    WHEN manifest_provenance->>'raw_sha256' ~ '^[0-9a-f]{64}$'
    THEN manifest_provenance->>'raw_sha256' ELSE NULL END;

CREATE TABLE source_revisions (
    source_revision_id text PRIMARY KEY,
    company text NOT NULL,
    source text NOT NULL,
    source_id text NOT NULL,
    raw_sha256 char(64) NOT NULL,
    UNIQUE (company, source, source_id, raw_sha256)
);
ALTER TABLE source_documents ADD COLUMN source_revision_id text REFERENCES source_revisions(source_revision_id);
ALTER TABLE source_documents ADD COLUMN source_artifact jsonb NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE source_documents ADD COLUMN cleaning_version text NOT NULL DEFAULT 'legacy-unverified';
INSERT INTO source_revisions
SELECT DISTINCT company || ':' || source || ':' || source_id || ':' || source_raw_sha256,
    company, source, source_id, source_raw_sha256
FROM source_documents WHERE source_raw_sha256 IS NOT NULL;
UPDATE source_documents SET
    source_revision_id = company || ':' || source || ':' || source_id || ':' || source_raw_sha256,
    cleaning_version = COALESCE(manifest_provenance->>'parser_version', 'legacy-unverified')
WHERE source_raw_sha256 IS NOT NULL;

CREATE TABLE document_derivations (
    derivation_id text PRIMARY KEY,
    document_id text NOT NULL REFERENCES source_documents(document_id) ON DELETE RESTRICT
);
-- Several historical materializations may contain an identical derivation.
-- Retain all historical rows, but choose one deterministic identity for reuse.
INSERT INTO document_derivations
SELECT 'derived:' || source_revision_id || ':' || cleaning_version || ':' || cleaned_content_sha256,
       min(document_id)
FROM source_documents WHERE source_revision_id IS NOT NULL
GROUP BY source_revision_id, cleaning_version, cleaned_content_sha256;

CREATE TABLE document_manifest_memberships (
    document_id text NOT NULL REFERENCES source_documents(document_id) ON DELETE RESTRICT,
    manifest_version text NOT NULL,
    provenance jsonb NOT NULL,
    PRIMARY KEY (document_id, manifest_version)
);
INSERT INTO document_manifest_memberships
SELECT document_id, manifest_version, manifest_provenance FROM source_documents;

ALTER TABLE chunks DROP CONSTRAINT chunks_document_id_ordinal_key;
ALTER TABLE chunks ADD CONSTRAINT chunks_document_configuration_ordinal_key
    UNIQUE (document_id, processing_config_version, ordinal);
