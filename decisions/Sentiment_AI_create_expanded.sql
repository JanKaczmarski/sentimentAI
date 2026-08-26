-- Expanded PostgreSQL schema proposal for the thesis implementation.
--
-- This file is intentionally separate from Sentiment_AI_create.sql, the
-- preserved Redgate export. It is designed to initialize a fresh database;
-- it is not an ALTER script to run over the legacy schema.
--
-- Major changes from the legacy draft:
--   * UUID primary keys and server-side UUID generation;
--   * structured, user-owned Investment Theses;
--   * raw and cleaned source-document retention;
--   * immutable scoring, snapshot, prediction, and provenance records;
--   * prediction evidence linked to the scored source chunks.

CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- Canonical approved company registry. Seed data belongs in a separate
-- migration so the registry can be reviewed independently of this schema.
CREATE TABLE companies (
    company_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    ticker varchar(16) NOT NULL UNIQUE,
    company_name varchar(255) NOT NULL,
    market_routing_value varchar(64) NOT NULL,
    trading_currency char(3) NOT NULL,
    cik char(10),
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT ck_companies_ticker_uppercase CHECK (ticker = upper(ticker)),
    CONSTRAINT ck_companies_currency_uppercase CHECK (trading_currency = upper(trading_currency))
);

-- Raw API keys are never stored. The application returns a generated key only
-- at account creation and stores a one-way digest in api_key_digest.
CREATE TABLE users (
    user_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    email varchar(255) NOT NULL,
    username varchar(100) NOT NULL,
    api_key_digest varchar(255) NOT NULL UNIQUE,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX uq_users_email_case_insensitive ON users (lower(email));

CREATE UNIQUE INDEX uq_users_username_case_insensitive ON users (lower(username));

-- A thesis is owned by one user. Its assigned companies are stored separately
-- so one thesis can cover one company or a group without a named-group entity.
CREATE TABLE investment_theses (
    thesis_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES users (user_id) ON DELETE RESTRICT,
    risk_tolerance varchar(16) NOT NULL,
    investment_horizon varchar(16) NOT NULL,
    investment_style varchar(16) NOT NULL,
    description text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT ck_investment_theses_risk_tolerance
        CHECK (risk_tolerance IN ('low', 'medium', 'high')),
    CONSTRAINT ck_investment_theses_investment_horizon
        CHECK (investment_horizon IN ('short_term', 'long_term')),
    CONSTRAINT ck_investment_theses_investment_style
        CHECK (investment_style IN ('passive', 'active'))
);

CREATE INDEX ix_investment_theses_user_id ON investment_theses (user_id);

CREATE TABLE investment_thesis_companies (
    thesis_id uuid NOT NULL REFERENCES investment_theses (thesis_id) ON DELETE CASCADE,
    company_id uuid NOT NULL REFERENCES companies (company_id) ON DELETE RESTRICT,
    PRIMARY KEY (thesis_id, company_id)
);

CREATE INDEX ix_investment_thesis_companies_company_id
    ON investment_thesis_companies (company_id);

-- Every normalized source keeps the original material and a separately cleaned
-- representation. Hashes make retained content verifiable without replacing it.
CREATE TABLE source_documents (
    document_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    source_id varchar(255) NOT NULL,
    company_id uuid NOT NULL REFERENCES companies (company_id) ON DELETE RESTRICT,
    source_type varchar(32) NOT NULL,
    document_type varchar(64) NOT NULL,
    published_at date NOT NULL,
    raw_content text NOT NULL,
    cleaned_content text NOT NULL,
    raw_content_sha256 char(64) NOT NULL,
    cleaned_content_sha256 char(64) NOT NULL,
    ingested_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_source_documents_source_identity UNIQUE (source_type, source_id),
    CONSTRAINT ck_source_documents_source_type
        CHECK (source_type IN ('sec', 'investor_relations', 'company_communication'))
);

CREATE INDEX ix_source_documents_company_published_at
    ON source_documents (company_id, published_at);

CREATE TABLE chunks (
    chunk_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id uuid NOT NULL REFERENCES source_documents (document_id) ON DELETE CASCADE,
    ordinal integer NOT NULL,
    content text NOT NULL,
    content_sha256 char(64) NOT NULL,
    chunking_config_version varchar(64) NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_chunks_document_ordinal UNIQUE (document_id, ordinal),
    CONSTRAINT ck_chunks_ordinal_non_negative CHECK (ordinal >= 0)
);

CREATE INDEX ix_chunks_document_id ON chunks (document_id);

-- A run identifies the reproducible execution that produced related scores,
-- snapshots, predictions, and provenance.
CREATE TABLE experiment_runs (
    run_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    run_type varchar(32) NOT NULL,
    status varchar(16) NOT NULL DEFAULT 'started',
    started_at timestamptz NOT NULL DEFAULT now(),
    completed_at timestamptz,
    configuration jsonb NOT NULL DEFAULT '{}'::jsonb,
    CONSTRAINT ck_experiment_runs_status
        CHECK (status IN ('started', 'completed', 'failed')),
    CONSTRAINT ck_experiment_runs_completion
        CHECK (completed_at IS NULL OR completed_at >= started_at)
);

-- Provenance is secret-free. Raw source documents and keys are not copied into
-- JSON payloads, prompts, or model responses stored by this table.
CREATE TABLE experiment_provenance (
    run_id uuid PRIMARY KEY REFERENCES experiment_runs (run_id) ON DELETE CASCADE,
    input_source varchar(255) NOT NULL,
    input_version varchar(255) NOT NULL,
    processing_config jsonb NOT NULL,
    model_provider varchar(128) NOT NULL,
    model_name varchar(255) NOT NULL,
    prompt text NOT NULL,
    raw_response text NOT NULL,
    parsed_output jsonb NOT NULL,
    thesis_parameters jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now()
);

-- Scores are append-only by run: a future run creates new rows instead of
-- overwriting audit evidence from an earlier scoring run.
CREATE TABLE chunk_scores (
    chunk_score_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    chunk_id uuid NOT NULL REFERENCES chunks (chunk_id) ON DELETE RESTRICT,
    run_id uuid NOT NULL REFERENCES experiment_runs (run_id) ON DELETE RESTRICT,
    sentiment_score numeric(5,4) NOT NULL,
    sentiment_label varchar(16) NOT NULL,
    importance_score numeric(5,4) NOT NULL,
    confidence numeric(5,4) NOT NULL,
    excluded boolean NOT NULL DEFAULT false,
    prompt text NOT NULL,
    raw_response text NOT NULL,
    parsed_output jsonb NOT NULL,
    token_usage jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_chunk_scores_chunk_run UNIQUE (chunk_id, run_id),
    CONSTRAINT ck_chunk_scores_sentiment_score
        CHECK (sentiment_score BETWEEN 0 AND 1),
    CONSTRAINT ck_chunk_scores_sentiment_label
        CHECK (sentiment_label IN ('NEGATIVE', 'NEUTRAL', 'POSITIVE')),
    CONSTRAINT ck_chunk_scores_importance_score
        CHECK (importance_score BETWEEN 0 AND 1),
    CONSTRAINT ck_chunk_scores_confidence
        CHECK (confidence BETWEEN 0 AND 1)
);

CREATE INDEX ix_chunk_scores_chunk_id ON chunk_scores (chunk_id);
CREATE INDEX ix_chunk_scores_run_id ON chunk_scores (run_id);

CREATE TABLE company_sentiment_snapshots (
    snapshot_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id uuid NOT NULL REFERENCES companies (company_id) ON DELETE RESTRICT,
    as_of date NOT NULL,
    window_days integer NOT NULL,
    sentiment_score numeric(5,4) NOT NULL,
    sentiment_label varchar(16) NOT NULL,
    confidence numeric(5,4) NOT NULL,
    run_id uuid NOT NULL REFERENCES experiment_runs (run_id) ON DELETE RESTRICT,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_company_sentiment_snapshots_identity
        UNIQUE (company_id, as_of, window_days, run_id),
    CONSTRAINT ck_company_sentiment_snapshots_window_days
        CHECK (window_days IN (30, 90, 365)),
    CONSTRAINT ck_company_sentiment_snapshots_score
        CHECK (sentiment_score BETWEEN 0 AND 1),
    CONSTRAINT ck_company_sentiment_snapshots_label
        CHECK (sentiment_label IN ('NEGATIVE', 'NEUTRAL', 'POSITIVE')),
    CONSTRAINT ck_company_sentiment_snapshots_confidence
        CHECK (confidence BETWEEN 0 AND 1)
);

CREATE INDEX ix_company_sentiment_snapshots_company_as_of
    ON company_sentiment_snapshots (company_id, as_of);

-- This lineage states which scored chunks contributed to a snapshot.
CREATE TABLE company_sentiment_snapshot_evidence (
    snapshot_id uuid NOT NULL REFERENCES company_sentiment_snapshots (snapshot_id) ON DELETE CASCADE,
    chunk_score_id uuid NOT NULL REFERENCES chunk_scores (chunk_score_id) ON DELETE RESTRICT,
    PRIMARY KEY (snapshot_id, chunk_score_id)
);

CREATE TABLE stock_pricing (
    company_id uuid NOT NULL REFERENCES companies (company_id) ON DELETE RESTRICT,
    price_date date NOT NULL,
    price numeric(15,4) NOT NULL,
    currency char(3) NOT NULL,
    source varchar(64) NOT NULL,
    fetched_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (company_id, price_date, source),
    CONSTRAINT ck_stock_pricing_positive_price CHECK (price > 0),
    CONSTRAINT ck_stock_pricing_currency_uppercase CHECK (currency = upper(currency))
);

-- A personalized prediction retains both general and thesis-adjusted results.
CREATE TABLE predictions (
    prediction_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES users (user_id) ON DELETE RESTRICT,
    thesis_id uuid NOT NULL REFERENCES investment_theses (thesis_id) ON DELETE RESTRICT,
    company_id uuid NOT NULL REFERENCES companies (company_id) ON DELETE RESTRICT,
    as_of date NOT NULL,
    lookback_days integer NOT NULL,
    forecast_horizon_days integer NOT NULL,
    base_sentiment_score numeric(5,4) NOT NULL,
    base_sentiment_label varchar(16) NOT NULL,
    personalized_sentiment_score numeric(5,4) NOT NULL,
    personalized_sentiment_label varchar(16) NOT NULL,
    confidence numeric(5,4) NOT NULL,
    reasoning text,
    run_id uuid NOT NULL REFERENCES experiment_runs (run_id) ON DELETE RESTRICT,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_predictions_identity
        UNIQUE (user_id, thesis_id, company_id, as_of, lookback_days, forecast_horizon_days, run_id),
    CONSTRAINT ck_predictions_lookback_days CHECK (lookback_days IN (30, 90, 365)),
    CONSTRAINT ck_predictions_forecast_horizon_days CHECK (forecast_horizon_days > 0),
    CONSTRAINT ck_predictions_base_score CHECK (base_sentiment_score BETWEEN 0 AND 1),
    CONSTRAINT ck_predictions_base_label
        CHECK (base_sentiment_label IN ('NEGATIVE', 'NEUTRAL', 'POSITIVE')),
    CONSTRAINT ck_predictions_personalized_score
        CHECK (personalized_sentiment_score BETWEEN 0 AND 1),
    CONSTRAINT ck_predictions_personalized_label
        CHECK (personalized_sentiment_label IN ('NEGATIVE', 'NEUTRAL', 'POSITIVE')),
    CONSTRAINT ck_predictions_confidence CHECK (confidence BETWEEN 0 AND 1)
);

CREATE INDEX ix_predictions_user_created_at ON predictions (user_id, created_at DESC);
CREATE INDEX ix_predictions_company_as_of ON predictions (company_id, as_of);

-- Excerpts make an API response reviewable while foreign keys preserve the
-- complete evidence path: prediction -> score -> chunk -> source document.
CREATE TABLE prediction_evidence (
    prediction_id uuid NOT NULL REFERENCES predictions (prediction_id) ON DELETE CASCADE,
    chunk_score_id uuid NOT NULL REFERENCES chunk_scores (chunk_score_id) ON DELETE RESTRICT,
    evidence_rank integer NOT NULL,
    excerpt text NOT NULL,
    PRIMARY KEY (prediction_id, chunk_score_id),
    CONSTRAINT uq_prediction_evidence_rank UNIQUE (prediction_id, evidence_rank),
    CONSTRAINT ck_prediction_evidence_rank_positive CHECK (evidence_rank > 0)
);

-- Legacy mapping:
--   reports             -> source_documents
--   chunks              -> chunks (now keyed by UUID and document lineage)
--   strategies and subscriptions -> investment_theses and investment_thesis_companies
--   past_predictions    -> predictions and prediction_evidence
--   stock_pricing       -> stock_pricing (now records source and currency)
