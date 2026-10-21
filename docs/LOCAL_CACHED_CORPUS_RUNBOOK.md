# Local Cached-Corpus Workflow

The current core research sample is **META, CRM, V, DIS, WHR, T**; see
`RESEARCH_HISTORY_ACQUISITION.md` and the external inventory for current source
coverage. The six-company functional snapshot described below is the original
demonstration and remains useful historical verification evidence.

This runbook starts the normal local application path using the external
`sentimentAI-data` cache. The current functional snapshot covers `AAPL`, `MSFT`,
`NVDA`, `JPM`, `XOM`, and `JNJ`; the cache also contains historical AMAT records
that can be processed through the same workflow.

## Prerequisites

- The application repository and sibling `sentimentAI-data` repository exist.
- Ollama is running on the host at `http://127.0.0.1:11434`.
- The local models are available:

    ollama pull llama3.1:8b
    ollama pull nomic-embed-text

Create `.env` from `.env.example` if needed. An existing `.env` must contain the
normal cached-corpus settings:

    APP_ENV=research
    SENTIMENT_DATA_ROOT=../sentimentAI-data
    LLM_BACKEND=ollama
    LLM_MODEL=llama3.1:8b
    EMBEDDING_BACKEND=ollama
    EMBEDDING_MODEL=nomic-embed-text
    QDRANT_COLLECTION=research_chunks

No special source manifest or company-specific environment variable is needed.

Research/production startup requires `DATABASE_URL`, `QDRANT_URL`, and
`SENTIMENT_DATA_ROOT`. PostgreSQL and Qdrant must identify durable servers; the
cache directory must exist and contain supported source records. Missing settings
fail startup before database migration or fixture fallback. Compose supplies the
server URLs automatically. Direct `uv` startup needs all three settings.

For deliberate fixture/in-memory development, set `APP_ENV=development`,
`LLM_BACKEND=deterministic`, and `EMBEDDING_BACKEND=mock`, and leave those three
dependency settings unset. This mode is suitable for workflow tests.

## Start The Application

Run from the application repository:

    docker compose up --build -d postgres qdrant app
    curl --fail http://localhost:8000/health

The application reads the external cache through the normal cached-corpus source.
The data volume is mounted read-only. Ollama remains host-managed and is reached
from the container through the Compose-configured host gateway.

## Use The Browser

Open `http://localhost:8000/ui/` and:

1. Create an account with a unique email and username.
2. Create an Investment Thesis for one or more cached companies.
3. Configure risk tolerance, investment horizon, investment style, and optional description.
4. Select one company in the prediction section.
5. Set an as-of date that is not later than the available source snapshot.
6. Click `Run batch`.

For the six-company functional snapshot, use `2026-06-30`. For a reproducible
AMAT run against the currently available historical records, use `2026-05-14`.
The AMAT run processes the normal cached AMAT history available by that date,
not a fixed two-document subset.

The page displays the completed batch count, base sentiment, personalized
sentiment, confidence, and ranked evidence excerpts. Repeat the batch for each
ticker when a multi-company comparison is required; batches are intentionally
run one company at a time.

## Boundary

This is a local cached-corpus workflow, not the final five-year thesis corpus,
held-out evaluation manifest, live SEC/IR acquisition service, or market-outcome
evaluation. The cache preserves source identifiers, publication dates, raw
content, and source hashes for reproducibility.

## Explicit Frozen-Corpus Batch

`POST /batch/run` accepts `source_scope`, defaulting to `operational` for the
normal broad cached-company workflow. Select `frozen` explicitly to load only
the active immutable `thesis-v2-current-cache-sec-form-aware-v2` manifest:

```json
{
  "company": "META",
  "as_of": "2026-08-28",
  "source_scope": "frozen"
}
```

Omitting `company` processes all companies in that scope. Frozen mode fails and
records a failed run if its manifest is unavailable; it never falls back to the
broad cache or development fixtures. Frozen loading does not read unrelated
operational history. Original/cleaned checksums and manifest evidence are
verified by the existing cache reader.

All batches use **publication strictly before `as_of`**. An August 28 snapshot
may use August 27 documents; an August 27 snapshot may not. The frozen source
cutoff and held-out split remain unchanged.

Read a prediction with the same `as_of` and `source_scope=frozen`, for example
`GET /companies/META/prediction?api_key=...&as_of=2026-08-28&source_scope=frozen`.
The optional prediction scope prevents selecting operational runs when a frozen
experiment is requested. Within that scope, FEAT-038 still requires the latest
relevant run to be completed with both exact-date thesis windows. There is no
older-run fallback. Without the optional scope, the existing latest-relevant-run
selection considers both scopes.

The response and stored history include `prediction_id`, `rule_version`,
`run_metadata`, and the structured `thesis_parameters`. The hash-based prediction
identity includes the account, scoring run, forecast settings, rule version and
thesis parameters. Multiple investors and changed theses can reuse one scoring
run while retaining independent historical results.

## Prepare One Company Without Scoring

`POST /companies/{company}/ingest` synchronously prepares cached documents without
scoring, creating snapshots or requiring an Investment Thesis. For example:

```bash
curl --fail-with-body http://localhost:8000/companies/META/ingest \
  -H 'Content-Type: application/json' \
  -d '{"as_of":"2026-08-28","source_scope":"frozen"}'
```

`source_scope` defaults to `operational`; `as_of` defaults to today. Both scopes
require publication strictly before the date. Frozen scope never falls back to
operational sources. The source adapter reads its cache snapshot at startup;
restart the application after publishing additional cached source files.

The HTTP 200 response contains `status`, a fresh `run_id`, canonical `company`,
`source_scope`, and these counts:

| Field | Meaning |
|---|---|
| `document_count` | Total selected documents, including existing documents |
| `chunk_count` | Total resulting chunks, including existing chunks |
| `indexed_chunk_count` | Total confirmed indexed chunks, including reused vectors |
| `embedded_chunk_count` | Chunks newly embedded and indexed during this attempt |
| `reused_chunk_count` | Compatible vector points reused without an embedding call |

Repeat the request to verify that `embedded_chunk_count` becomes zero and
`reused_chunk_count` equals `indexed_chunk_count`. Every request has a distinct
audit run; underlying documents/chunks/points retain their identities. Approved
companies without eligible sources return zero counts. Unsupported tickers or
invalid request fields return HTTP 422. Preparation failures return HTTP 500
with `ingestion run failed: <run_id>` and persist the failed stage/exception type.
An explicit retry reuses confirmed prior indexing batches and repairs missing
points. Inspect run/provenance repositories for audit artifacts; this feature
does not add a status-polling endpoint.

Existing points without embedding-configuration fingerprints are re-indexed
once. Compatibility requires matching source/chunk content and the configured
embedding identity; a model change cannot silently reuse old vectors. A changed
model dimension requires a separately configured Qdrant collection, since the
application never deletes/recreates an incompatible collection. Keep mutable
model aliases stable for a declared identity. See
[decision 0020](../decisions/0020-on-demand-company-ingestion-and-embedding-reuse.md).

The combined `/batch/run` also reuses compatible embeddings while still executing
scoring and aggregation. Preparation alone produces no new prediction, and its
newer run does not hide an existing prediction. The browser still exposes the
combined batch action until FEAT-034 adds separate controls.

## Run Records And Failure Evidence

Batches record ingestion, indexing, scoring, aggregation, and exclusion-sync
stage timestamps/status, counts, processing version, source IDs/checksums/chunk
lineage, embedding/scoring identities, and the frozen manifest version/hash.
The batch retains ownership of run completion through every stage.

Failures return HTTP 500 with the run ID. Stored failure evidence identifies the
stage and exception type, completed ingestion lineage, and successful scoring
outputs. Exception messages and connection strings are not stored. Finalized and
legacy provenance is retained; only explicitly active provenance can be updated.
Provider-specific malformed/failed raw-response capture remains FEAT-023.

Indexing preserves the last completed score's exclusion state. After successful
scoring/aggregation, payload-only vector updates synchronize exclusion or recovery
without embedding a second time. PostgreSQL remains authoritative; a vector-sync
failure fails the batch and makes that latest run unavailable for prediction.

Migration `0012_prediction_audit_identity.sql` preserves existing prediction
values/evidence and attaches opaque legacy identities. It leaves unknown legacy
rule/configuration metadata empty instead of inventing provenance. It then permits
independent investor/thesis predictions and stores new audit metadata.

## Workflow Verification

The regular `uv run pytest` loop remains Docker-free. Deterministic providers
exercise the complete pipeline, and infrastructure tests run only when their
explicit test settings are supplied. Full external-corpus replay is opt-in:

```bash
SENTIMENT_DATA_ROOT=../sentimentAI-data uv run pytest tests/integration/test_frozen_pipeline.py
```

That test processes all 363 actual frozen source records with development-only
deterministic providers, creates 18 snapshots and serves predictions for two
investors. It verifies orchestration, not research sentiment quality or market
performance. Production scoring/tokenizer compliance and actual evaluation remain
in their dedicated features.

Explicit durable integration uses `POSTGRES_TEST_DSN` and `QDRANT_TEST_URL` with
`tests/integration/test_pipeline_persistence.py`; it creates isolated database
schemas and vector collections and cleans up its own artifacts.

## Stop Services

    docker compose down

Do not use `docker compose down -v` unless deleting local experiment data is
intentional.
