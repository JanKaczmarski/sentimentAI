CREATE TABLE predictions (
    company text NOT NULL,
    as_of date NOT NULL,
    lookback_days integer NOT NULL CHECK (lookback_days IN (30, 90, 365)),
    forecast_horizon_days integer NOT NULL CHECK (forecast_horizon_days IN (1, 5, 20, 60, 252)),
    user_id uuid REFERENCES user_accounts (user_id) ON DELETE RESTRICT,
    base_score numeric(5, 4) NOT NULL CHECK (base_score BETWEEN 0 AND 1),
    base_label text NOT NULL CHECK (base_label IN ('NEGATIVE', 'NEUTRAL', 'POSITIVE')),
    base_confidence numeric(5, 4) NOT NULL CHECK (base_confidence BETWEEN 0 AND 1),
    personalized_score numeric(5, 4) NOT NULL CHECK (personalized_score BETWEEN 0 AND 1),
    personalized_label text NOT NULL CHECK (personalized_label IN ('NEGATIVE', 'NEUTRAL', 'POSITIVE')),
    personalized_confidence numeric(5, 4) NOT NULL CHECK (personalized_confidence BETWEEN 0 AND 1),
    confidence numeric(5, 4) NOT NULL CHECK (confidence BETWEEN 0 AND 1),
    reasoning text,
    run_id text NOT NULL REFERENCES experiment_runs (run_id) ON DELETE RESTRICT,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (company, as_of, lookback_days, forecast_horizon_days, run_id)
);

CREATE INDEX predictions_user_idx ON predictions (user_id, as_of, company);

CREATE TABLE prediction_evidence (
    company text NOT NULL,
    as_of date NOT NULL,
    lookback_days integer NOT NULL,
    forecast_horizon_days integer NOT NULL,
    run_id text NOT NULL,
    evidence_rank integer NOT NULL CHECK (evidence_rank > 0),
    chunk_id text NOT NULL,
    published_at date NOT NULL,
    importance_score numeric(5, 4) NOT NULL CHECK (importance_score BETWEEN 0 AND 1),
    excerpt text NOT NULL,
    PRIMARY KEY (company, as_of, lookback_days, forecast_horizon_days, run_id, evidence_rank),
    FOREIGN KEY (company, as_of, lookback_days, forecast_horizon_days, run_id)
        REFERENCES predictions (company, as_of, lookback_days, forecast_horizon_days, run_id)
        ON DELETE CASCADE
);
