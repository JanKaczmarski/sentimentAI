CREATE TABLE source_documents (
    document_id text PRIMARY KEY,
    source_id text NOT NULL,
    company text NOT NULL,
    source text NOT NULL,
    published_at date NOT NULL,
    document_type text NOT NULL,
    raw_content text NOT NULL,
    cleaned_content text NOT NULL,
    raw_content_sha256 char(64) NOT NULL,
    cleaned_content_sha256 char(64) NOT NULL,
    ingested_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (source, source_id)
);

CREATE INDEX source_documents_company_published_idx
    ON source_documents (company, published_at, document_id);

CREATE TABLE chunks (
    chunk_id text PRIMARY KEY,
    document_id text NOT NULL REFERENCES source_documents (document_id) ON DELETE CASCADE,
    ordinal integer NOT NULL CHECK (ordinal >= 0),
    content text NOT NULL,
    content_sha256 char(64) NOT NULL,
    processing_config_version text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (document_id, ordinal)
);

CREATE INDEX chunks_document_idx ON chunks (document_id, ordinal, chunk_id);

CREATE TABLE experiment_runs (
    run_id text PRIMARY KEY,
    run_type text NOT NULL,
    status text NOT NULL CHECK (status IN ('started', 'completed', 'failed')),
    started_at timestamptz NOT NULL,
    completed_at timestamptz,
    configuration jsonb NOT NULL DEFAULT '{}'::jsonb,
    CHECK (completed_at IS NULL OR completed_at >= started_at)
);

CREATE TABLE experiment_provenance (
    run_id text PRIMARY KEY REFERENCES experiment_runs (run_id) ON DELETE CASCADE,
    input_source text NOT NULL,
    input_version text NOT NULL,
    processing_config jsonb NOT NULL,
    model_provider text NOT NULL,
    model_name text NOT NULL,
    prompt text NOT NULL,
    raw_response text NOT NULL,
    parsed_output jsonb NOT NULL,
    thesis_parameters jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL
);

CREATE TABLE chunk_scores (
    chunk_id text NOT NULL REFERENCES chunks (chunk_id) ON DELETE RESTRICT,
    run_id text NOT NULL REFERENCES experiment_runs (run_id) ON DELETE RESTRICT,
    sentiment_score numeric(5, 4) NOT NULL CHECK (sentiment_score BETWEEN 0 AND 1),
    sentiment_label text NOT NULL CHECK (sentiment_label IN ('NEGATIVE', 'NEUTRAL', 'POSITIVE')),
    importance_score numeric(5, 4) NOT NULL CHECK (importance_score BETWEEN 0 AND 1),
    confidence numeric(5, 4) NOT NULL CHECK (confidence BETWEEN 0 AND 1),
    excluded boolean NOT NULL,
    prompt text NOT NULL,
    raw_response text NOT NULL,
    parsed_output jsonb NOT NULL,
    token_usage jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (chunk_id, run_id)
);

CREATE INDEX chunk_scores_run_idx ON chunk_scores (run_id, chunk_id);

CREATE TABLE company_sentiment_snapshots (
    company text NOT NULL,
    as_of date NOT NULL,
    window_days integer NOT NULL CHECK (window_days IN (30, 90, 365)),
    sentiment_score numeric(5, 4) NOT NULL CHECK (sentiment_score BETWEEN 0 AND 1),
    sentiment_label text NOT NULL CHECK (sentiment_label IN ('NEGATIVE', 'NEUTRAL', 'POSITIVE')),
    confidence numeric(5, 4) NOT NULL CHECK (confidence BETWEEN 0 AND 1),
    run_id text NOT NULL REFERENCES experiment_runs (run_id) ON DELETE RESTRICT,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (company, as_of, window_days, run_id)
);

CREATE INDEX company_snapshots_lookup_idx
    ON company_sentiment_snapshots (company, as_of, window_days, run_id);

CREATE TABLE company_sentiment_snapshot_evidence (
    company text NOT NULL,
    as_of date NOT NULL,
    window_days integer NOT NULL,
    run_id text NOT NULL,
    evidence_rank integer NOT NULL CHECK (evidence_rank > 0),
    chunk_id text NOT NULL,
    published_at date NOT NULL,
    importance_score numeric(5, 4) NOT NULL CHECK (importance_score BETWEEN 0 AND 1),
    excerpt text NOT NULL,
    PRIMARY KEY (company, as_of, window_days, run_id, evidence_rank),
    FOREIGN KEY (company, as_of, window_days, run_id)
        REFERENCES company_sentiment_snapshots (company, as_of, window_days, run_id)
        ON DELETE CASCADE
);
