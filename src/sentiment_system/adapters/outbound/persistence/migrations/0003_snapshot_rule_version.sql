ALTER TABLE company_sentiment_snapshots
    ADD COLUMN rule_version text NOT NULL DEFAULT 'aggregation-personalization-v1';
