# Thesis Research Decisions

Working decisions agreed during the research-definition discussion. This is a
living scope document for the thesis-focused rebuild, not a production
specification.

## Research Model

- Use a two-stage pipeline:
  1. Calculate reusable, investor-independent sentiment and importance at chunk level.
  2. Aggregate it and apply the investor's Investment Thesis with deterministic rules.
- Represent sentiment with both:
  - a polarity score from `0.0` (strongly negative) to `1.0` (strongly positive), with `0.5` neutral;
  - a derived `NEGATIVE`, `NEUTRAL`, or `POSITIVE` label.
- Use initial label thresholds: `< 0.4` negative, `0.4..0.6` neutral, `> 0.6` positive.
- Store model confidence separately from polarity.
- Calculate sentiment at `chunk -> document -> company/time-window` granularity.
- Aggregate scores with an importance- and recency-weighted mean.
- Use company sentiment lookback windows of 30, 90, and 365 days.

## Investment Thesis

- Store an Investment Thesis per company or company group.
- Use structured fields for the deterministic algorithm: risk tolerance, investment horizon, investment style, and company/group assignment.
- Keep optional free-text thesis descriptions for explanation and documentation only; do not interpret them automatically in the core algorithm.
- Use an explicit rule-based personalization algorithm:
  - investment horizon selects relevant sentiment windows;
  - risk tolerance changes decision thresholds;
  - investment style changes short- versus long-term weighting.
- Define rules before evaluation and run sensitivity analysis rather than tuning them against final results.

## Data Scope

- Use five years of historical source data and a two-year held-out evaluation period.
- The initial thesis and evaluation sample remains `AAPL`, `MSFT`, `NVDA`,
  `JPM`, `XOM`, and `JNJ` until a broader research universe is explicitly
  approved.
- Local development snapshots may contain a broader candidate company
  universe. Their presence does not change the thesis sample or approve a
  production/ingestion registry.
- Text sources:
  - SEC EDGAR `10-K`, `10-Q`, and relevant `8-K` filings;
  - official company investor-relations earnings releases.
- Use cached Yahoo Finance historical prices for market evaluation, not necessarily as LLM text context.
- Use a fixture-based email/webhook-shaped adapter for company communications rather than private live email integration.
- Keep raw and cleaned document representations and compare them experimentally.
- Cleaning should remove clearly irrelevant boilerplate, navigation text, duplicated legal language, and formatting noise without discarding the raw source.

## RAG And Scoring

- Assign each chunk both polarity and a general importance/relevance score from `0.0` to `1.0`.
- Generate importance with the LLM during the corpus batch; embeddings may narrow candidates but are not the authoritative importance value.
- Exclude chunks below `0.05` after three consecutive low-importance batch scores.
- Use soft exclusion rather than physical deletion so historical evidence remains auditable.
- Evaluate standard chunking and contextual RAG as separate variants.
- Contextual RAG means generating a document summary and prepending it to its chunks.
- Enforce a 15,000-token input budget per LLM request; select chunks by importance and retrieval score and record truncation.

## Evaluation

- Use a daily scheduled batch plus a manual trigger; event-driven processing is out of scope for the thesis.
- Align each document signal to the first trading day after publication and prevent later information from entering the context.
- Evaluate multiple forward horizons: 1, 5, 20, 60, and optionally 252 trading days.
- Measure market usefulness with forward excess return against a sector benchmark, using the S&P 500 as fallback.
- Report sensitivity against the S&P 500 benchmark.
- Use rank/Spearman correlation as the primary market metric and directional hit rate as a secondary metric.
- Use the existing deterministic keyword heuristic as the text baseline.
- Use a no-signal/market benchmark for return evaluation.
- Use a small manual review as a secondary sanity check, not as unquestionable financial ground truth.
- Do not use an LLM judge as the sole ground truth.

## Runtime And Architecture

- Revise the architecture into a thesis-focused v0.2 before rebuilding the code.
- Preserve the conceptual boundaries of Orchestrator, Data Ingest, and RAG, but add explicit scoring, personalization, and evaluation components.
- Use Groq as the primary LLM backend initially; keep a local Llama-compatible backend as an optional alternative.
- Keep Cyfronet integration as a stretch goal for large prompts/private hosted models.
- Require real local semantic embeddings for thesis results; mock hash embeddings are development-only.
- Persist full audit artifacts: source dates and IDs, chunk scores, model/provider configuration, prompts, raw LLM responses, parsed results, strategy parameters, and run IDs. Never store secrets.
- Rebuild the core draft API endpoints for accounts, company/group Investment Thesis CRUD, predictions, prediction history, and fixture-based company communication ingestion.
- Prediction responses should expose base and personalized scores/labels, dates and horizons, confidence, explanation, source excerpts/IDs, importance scores, and run metadata.
- REST API and Swagger are sufficient; no separate frontend is required.
- Authentication, user roles, and admin authorization are out of scope and should be documented as POC limitations.
- Use Docker Compose from the beginning with the application, persistent Qdrant, PostgreSQL, Prometheus, and Grafana. Keep observability focused on useful batch, retrieval, LLM, and evaluation metrics.

## Open Decisions

- Exact chronological development/test split inside the five-year corpus.
- Exact recency-decay function and initial rule-table coefficients.
- Whether the 252-trading-day horizon is included in the final evaluation.
- Exact data-download mechanisms, caching format, and reproducibility process for SEC, investor-relations, and Yahoo data.
- Exact model/runtime choice for the optional local Llama backend.
- Final v0.2 API schemas and database tables.
