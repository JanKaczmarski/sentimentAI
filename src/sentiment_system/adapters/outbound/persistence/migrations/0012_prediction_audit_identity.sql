-- Preserve existing predictions/evidence while allowing independent investors and
-- immutable structured-thesis variants to reuse one company scoring run.
ALTER TABLE predictions
    ADD COLUMN prediction_id text,
    ADD COLUMN rule_version text,
    ADD COLUMN run_metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN thesis_parameters jsonb NOT NULL DEFAULT '{}'::jsonb;

UPDATE predictions
SET prediction_id = 'legacy:' || jsonb_build_array(company, as_of, lookback_days, forecast_horizon_days, run_id)::text;
ALTER TABLE predictions ALTER COLUMN prediction_id SET NOT NULL;

ALTER TABLE prediction_evidence ADD COLUMN prediction_id text;
UPDATE prediction_evidence AS evidence
SET prediction_id = prediction.prediction_id
FROM predictions AS prediction
WHERE (evidence.company, evidence.as_of, evidence.lookback_days, evidence.forecast_horizon_days, evidence.run_id)
    = (prediction.company, prediction.as_of, prediction.lookback_days, prediction.forecast_horizon_days, prediction.run_id);
ALTER TABLE prediction_evidence ALTER COLUMN prediction_id SET NOT NULL;

-- Resolve the original auto-generated FK name through the catalog; identifiers
-- are database-owned and quoted, never supplied by an API caller.
DO $$
DECLARE original_fk text;
BEGIN
    FOR original_fk IN
        SELECT conname FROM pg_constraint
        WHERE conrelid = 'prediction_evidence'::regclass
          AND confrelid = 'predictions'::regclass AND contype = 'f'
    LOOP
        EXECUTE format('ALTER TABLE prediction_evidence DROP CONSTRAINT %I', original_fk);
    END LOOP;
END $$;

ALTER TABLE prediction_evidence DROP CONSTRAINT prediction_evidence_pkey;
ALTER TABLE predictions DROP CONSTRAINT predictions_pkey;
ALTER TABLE predictions ADD PRIMARY KEY (prediction_id);
ALTER TABLE prediction_evidence ADD PRIMARY KEY (prediction_id, evidence_rank);
ALTER TABLE prediction_evidence ADD CONSTRAINT prediction_evidence_prediction_id_fkey
    FOREIGN KEY (prediction_id) REFERENCES predictions (prediction_id) ON DELETE CASCADE;
