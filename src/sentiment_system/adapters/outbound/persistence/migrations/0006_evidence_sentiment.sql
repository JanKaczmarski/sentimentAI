ALTER TABLE company_sentiment_snapshot_evidence
    ADD COLUMN sentiment_score numeric(6, 5),
    ADD COLUMN sentiment_label text,
    ADD COLUMN sentiment_confidence numeric(6, 5);

ALTER TABLE prediction_evidence
    ADD COLUMN sentiment_score numeric(6, 5),
    ADD COLUMN sentiment_label text,
    ADD COLUMN sentiment_confidence numeric(6, 5);

UPDATE company_sentiment_snapshot_evidence AS evidence
SET sentiment_score = scores.sentiment_score,
    sentiment_label = scores.sentiment_label,
    sentiment_confidence = scores.confidence
FROM chunk_scores AS scores
WHERE scores.chunk_id = evidence.chunk_id
  AND scores.run_id = evidence.run_id;

UPDATE prediction_evidence AS evidence
SET sentiment_score = scores.sentiment_score,
    sentiment_label = scores.sentiment_label,
    sentiment_confidence = scores.confidence
FROM chunk_scores AS scores
WHERE scores.chunk_id = evidence.chunk_id
  AND scores.run_id = evidence.run_id;

UPDATE company_sentiment_snapshot_evidence
SET sentiment_score = COALESCE(sentiment_score, 0.5),
    sentiment_label = COALESCE(sentiment_label, 'NEUTRAL'),
    sentiment_confidence = COALESCE(sentiment_confidence, 0.0);

UPDATE prediction_evidence
SET sentiment_score = COALESCE(sentiment_score, 0.5),
    sentiment_label = COALESCE(sentiment_label, 'NEUTRAL'),
    sentiment_confidence = COALESCE(sentiment_confidence, 0.0);

ALTER TABLE company_sentiment_snapshot_evidence
    ALTER COLUMN sentiment_score SET NOT NULL,
    ALTER COLUMN sentiment_label SET NOT NULL,
    ALTER COLUMN sentiment_confidence SET NOT NULL,
    ADD CONSTRAINT snapshot_evidence_sentiment_score_range CHECK (sentiment_score >= 0 AND sentiment_score <= 1),
    ADD CONSTRAINT snapshot_evidence_sentiment_confidence_range CHECK (sentiment_confidence >= 0 AND sentiment_confidence <= 1),
    ADD CONSTRAINT snapshot_evidence_sentiment_label_valid CHECK (sentiment_label IN ('NEGATIVE', 'NEUTRAL', 'POSITIVE'));

ALTER TABLE prediction_evidence
    ALTER COLUMN sentiment_score SET NOT NULL,
    ALTER COLUMN sentiment_label SET NOT NULL,
    ALTER COLUMN sentiment_confidence SET NOT NULL,
    ADD CONSTRAINT prediction_evidence_sentiment_score_range CHECK (sentiment_score >= 0 AND sentiment_score <= 1),
    ADD CONSTRAINT prediction_evidence_sentiment_confidence_range CHECK (sentiment_confidence >= 0 AND sentiment_confidence <= 1),
    ADD CONSTRAINT prediction_evidence_sentiment_label_valid CHECK (sentiment_label IN ('NEGATIVE', 'NEUTRAL', 'POSITIVE'));
