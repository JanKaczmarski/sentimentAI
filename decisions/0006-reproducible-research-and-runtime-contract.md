# Reproducible Research And Runtime Contract

**Status:** Accepted

**Date:** 2026-08-25

## Purpose

This record closes the remaining corpus, evaluation, API, and storage decisions
for the thesis v0.2 implementation. It defines contracts and derivation rules;
the concrete source dates are materialized in each immutable acquisition
manifest rather than chosen after inspecting evaluation results.

## Corpus And Chronological Split

- The research universe is the approved thesis sample: `AAPL`, `MSFT`, `NVDA`,
  `JPM`, `XOM`, and `JNJ`.
- A corpus manifest is versioned and immutable. Each record contains company,
  source, source identifier, document type, publication date, retrieval URL,
  retrieval timestamp, raw-content SHA-256, cleaned-content SHA-256, raw path,
  parser version, and manifest version. Secrets are never stored in the
  manifest.
- The corpus window is the five years ending at the manifest cutoff date. The
  first three years are development data and the final two years are the
  held-out evaluation period.
- The manifest cutoff is the latest included publication date. The development
  period ends exactly two calendar years before that cutoff; the evaluation
  period starts at the first included publication date after that boundary.
- Documents outside the five-year window are retained in the source cache when
  acquired, but are excluded from the v1 research manifest.
- A prediction uses only documents published before its as-of date. Market
  alignment starts on the first trading day after publication.

The 1-, 5-, 20-, 60-, and 252-trading-day forward horizons are included.

## Benchmark Protocol

The acquisition manifest records the source-reported GICS sector for each
research company at acquisition time. Sector returns use these fixed SPDR
sector ETFs:

| GICS sector | Benchmark |
|---|---|
| Communication Services | `XLC` |
| Consumer Discretionary | `XLY` |
| Consumer Staples | `XLP` |
| Energy | `XLE` |
| Financials | `XLF` |
| Health Care | `XLV` |
| Industrials | `XLI` |
| Information Technology | `XLK` |
| Materials | `XLB` |
| Real Estate | `XLRE` |
| Utilities | `XLU` |

If a sector is unavailable, unsupported, or has no valid price series for a
comparison date, `SPY` is used as the deterministic fallback. Reports always
include the sector result, fallback count, and an S&P 500 sensitivity result.

## API Contract

- Identifiers are server-generated UUID strings. Dates are ISO-8601 dates for
  market as-of values and UTC timestamps for run/provenance values.
- Account creation is `POST /user/account` with `email` and `username`; the
  response returns `user_id` and the raw `api_key` once. Only its one-way digest
  is persisted.
- Thesis writes use `POST /user/strategy?api_key=...` and
  `PUT /user/strategy/{thesis_id}?api_key=...`; the request contains approved
  company tickers, risk tolerance, investment horizon, investment style, and an
  optional explanatory description.
- Thesis reads use `GET /user/strategy?api_key=...` and
  `GET /user/strategy/{ticker}?api_key=...`.
- Prediction reads use `GET /companies/{company_id}/prediction` with an account
  key, lookback window, and forward horizon. Allowed lookbacks are 30, 90, and
  365 days; allowed forward horizons are 1, 5, 20, 60, and 252 trading days.
- A prediction response contains company, as-of date, lookback, forward
  horizon, base and personalized sentiment score/label, confidence,
  explanation, source chunk IDs and excerpts, rule/configuration version, and
  experiment run ID.
- Fixture-based communication ingestion remains
  `POST /companies/{company_id}`. It accepts source metadata and raw content;
  normalization owns cleaned content and deterministic chunk lineage.

Invalid requests use framework validation responses; missing resources return
`404`; duplicate account email returns `409` with detail `email in use`.

## Persistence Contract

PostgreSQL is the authoritative durable store. The v0.2 model contains:

- accounts and one-way API-key digests;
- the canonical companies and thesis-to-company assignments;
- immutable raw/cleaned documents and chunks;
- append-only chunk scores and company snapshots;
- predictions and their source evidence;
- experiment runs and secret-free provenance artifacts.

Research records are append-only by run/version. Reprocessing creates a new
score, snapshot, or prediction record and never overwrites historical evidence.
Raw and cleaned content, source IDs, publication dates, model/provider settings,
prompt versions, parsed outputs, and run IDs remain linked across the record
chain.
