CREATE TABLE evaluation_reports (
    report_id text PRIMARY KEY,
    created_at timestamptz NOT NULL,
    corpus_manifest_version text NOT NULL,
    market_snapshot_version text NOT NULL,
    observations jsonb NOT NULL,
    exclusions jsonb NOT NULL,
    metrics jsonb NOT NULL
);
