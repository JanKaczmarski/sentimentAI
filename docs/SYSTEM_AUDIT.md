# System implementation audit — 2026-10-19

Baseline: `develop` at `3b1e3c46bc084318d83718c7bb0225d32b8cdd59`, after
PR #54 merged. This audit compares `FEATURES.yaml` against the active
`src/sentiment_system` implementation, composition root, API, Compose,
monitoring files and tests. It does not treat the legacy `poc/` as implemented
functionality of the rebuild.

## Working foundations

- Domain entities, ports, accounts/theses, aggregation, deterministic
  personalization, prediction/history APIs and the local browser console exist.
- Real PostgreSQL repositories exist in
  `adapters/outbound/persistence/postgres.py`, with migrations 0001–0011,
  original-byte source identities, immutable derivations/chunks, manifest
  memberships and persisted scores/runs/snapshots/predictions/evaluation reports.
  They are selected when `DATABASE_URL` is configured. They are not placeholders.
- Real Qdrant persistence/search and local SentenceTransformer/Ollama embeddings
  exist. Compose explicitly wires PostgreSQL and Qdrant with persistent volumes.
- Cached SEC/IR loading, HTML/PDF handling, reviewed cleaning, sentence-aware
  chunking and document/chunk persistence exist. The combined manual batch
  invokes ingestion, embedding/indexing, scoring and snapshot aggregation;
  prediction assembly/personalization is a separate API call.
- A real OpenAI-compatible Ollama scorer validates scoring JSON and records
  successful response/token metadata. Research mode rejects deterministic
  scoring and mock embeddings.
- FEAT-015's six-company frozen selection, original and corrected cleaned
  corpora, eleven-symbol prices and source/horizon availability bundle are
  published and pinned in `research-data.lock.json`. This is acquisition and
  availability evidence, not a completed prediction-performance experiment.
- Generic offline market loading and evaluation/report calculation/storage
  exist (FEAT-035/036). The API can retrieve an existing evaluation report.

## Remaining feature work

| Feature | Actual remaining work |
|---|---|
| FEAT-022 | Finish the complete frozen-corpus pipeline and integration evidence; require durable dependencies/cached inputs in research startup; coordinate stage/run state and exclusion propagation. Existing manual POC orchestration is partial groundwork. |
| FEAT-030 | Dedicated one-company cached ingest/index endpoint, counts/provenance, and embedding reuse. Raw/cleaned ingestion and database storage already exist. |
| FEAT-031 | Generate/persist document summaries, pass contextual scoring inputs, select standard/contextual variants, and enforce model-tokenizer budgets. |
| FEAT-032 | Enqueue/status API, persisted per-chunk progress, background worker, retry/backoff, bounded concurrency, restart resume and scheduled scoring enqueue. |
| FEAT-023 | Groq/other provider integration and full scoring-contract compliance: actual tokenizer budgets, 300-token completion limit, generation metadata, malformed/failed response provenance. Coordinate contextual work with FEAT-031. |
| FEAT-033 | Connect existing vector search to display-only evidence reranking/deduplication and retain ranking provenance. Current prediction evidence uses importance/recency sorting. |
| FEAT-034 | Separate ingest/score controls, job polling, variant and semantic-ranking display. Current console exposes the combined synchronous batch. |
| FEAT-016 | Wire verified market/scope loading and evaluation execution to frozen-scope predictions, record experiment configuration, run the final research workflow and persist its reports. Availability ledgers are not these reports. |
| FEAT-017 | Real scheduler lifecycle and cron-style ingest/score/batch triggers; stage/run logs, pipeline metrics, Grafana dashboards and dependency readiness. |
| FEAT-021 | Optional licensed providers/entitlements. Not required to use the published research cache. |
| FEAT-037 (new, proposed) | Cyfronet inference API connection, configuration, explicit failures, provider provenance and opt-in live verification. Actual endpoint/auth/model capabilities must be confirmed before readiness. |
| FEAT-038 (new, proposed) | Fix chronological score-history and latest eligible completed snapshot-run selection; random run IDs must not define execution order. |

The registry now records the merged FEAT-015 as complete. FEAT-016 no longer
claims source artifacts are missing; it waits on FEAT-022. Normal readiness
reconciliation applies to queued entries. Proposed entries are not executable
implementation selections until their readiness requirements are satisfied.
FEAT-019 (SQLite) remains intentionally rejected, not missing production work.

After reconciliation: **25 complete, 3 ready, 5 queued, 4 proposed, 1 rejected**.
There are 12 open entries, including optional licensed-provider and Cyfronet
work. FEAT-022 is the next feature selected by the registry; FEAT-030 and
FEAT-033 are also ready. The confirmed FEAT-038 correctness issue should be
resolved before relying on repeated research runs.

See [the two-engineer implementation plan](PARALLEL_IMPLEMENTATION_PLAN.md) for
parallel work pairs, sequential merge gates, shared-file ownership and rough
effort estimates. Proposed entries still require readiness review.

## Specific audit findings

### 1. Scheduling and observability are scaffolding

`adapters/inbound/scheduler.py` and
`adapters/outbound/observability/metrics.py` each contain only a docstring.
`bootstrap/main.py` has no scheduler startup/shutdown lifecycle. `apscheduler`
being installed does not schedule work.

`/metrics` mounts the default Prometheus registry, and Prometheus scraping plus
a Grafana datasource are configured. There are no application metric definitions
or dashboard/dashboard-provider files. `/health` returns process liveness only.
Full thesis-pipeline observability is tracked in FEAT-017; no additional tracing
backend or logging infrastructure was selected by this audit.

### 2. Live provider/source module names overstate implementation

`llm/groq.py`, `sources/sec.py`, `sources/investor_relations.py` and
`market_data/yahoo.py` are docstring-only files. Real acquisition instead lives
in explicit scripts, and runtime source access is cache-only. The Compose data
mount is read-only. Automatic refreshing of live sources is not currently
implemented by the manual batch endpoint.

Cyfronet has no adapter/configuration choice or verified connection. The generic
OpenAI-compatible adapter could be reused if the service supports that protocol,
but that has not been established. Compose hardcodes the LLM base URL to the
host's Ollama server, so a remote backend also needs an overridable URL.

### 3. Research storage can silently be in-memory

`bootstrap/container.py` initializes in-memory repositories/vector storage and a
fixture source, replacing them only when the corresponding environment settings
exist. A construction-only check with `APP_ENV=research`, a real LLM backend,
local embeddings, and unset `DATABASE_URL`, `QDRANT_URL`, `SENTIMENT_DATA_ROOT`
returned:

```text
research_database=None
documents=InMemoryDocumentRepository
vectors=InMemoryVectorStore
source=FixtureDocumentSource
```

No model or network call was made. Compose supplies the real settings; this is
a missing research configuration guard, not an absent PostgreSQL implementation.
The guard is now an explicit FEAT-022 acceptance criterion.

### 4. Current runs are synchronous and not incremental

`RunBatch.execute` creates a new UUID, ingests all eligible cached documents,
embeds every produced chunk, scores them synchronously and aggregates snapshots.
Stable document/chunk/vector IDs avoid some storage duplication, but do not avoid
repeat model work. There is no worker/checkpoint/status workflow. `ScoreChunks`
also writes intermediate state under the parent batch's run ID; stage lifecycle
must be resolved by FEAT-022/032.

### 5. Scoring compliance is partial

The runtime's chunk token counter is `len(value.split())`, not the selected
model's tokenizer. The LLM adapter sets temperature 0 and validates JSON, but
does not enforce the declared input/completion limits. `ScoreChunks` never
supplies its scorer's context parameter. Parse failures raise before a raw
response record is retained, and complete run provenance is saved after all
chunks succeed. These gaps are recorded under FEAT-023/031.

### 6. Confirmed run-order correctness defect

Both score repositories return history sorted by `run_id`, while scoring uses
the final two returned scores for its consecutive-low rule. The audit executed
this history entirely with fakes:

```text
Execution: run-x low, run-y low, run-a high, run-z low
Stored order: run-a, run-x, run-y, run-z
Final excluded: true
Required excluded: false (the high score breaks the consecutive streak)
```

PostgreSQL likewise uses `ORDER BY run_id`. Snapshot repositories order same-date
snapshots by window/run ID, and `GeneratePrediction` reverses the derived run
order without consulting execution timestamps/status. These related chronology
defects are tracked in FEAT-038; this audit does not change historical outputs.

### 7. Complete thesis experiments remain separate from the operational cache

`CachedCsvMarketData`, `load_evaluation_scope` and `EvaluatePredictions` exist,
but `build_container()` wires only `GetEvaluationReport`, not evaluation
execution. There is no evaluation-start route or final research runner. Normal
batch ingestion consumes the broad operational cache, not
`fetch_evaluation_documents()`, and includes publications on the selected as-of
date. The final runner must explicitly enforce the frozen membership and approved
publication/as-of rules; normal demo behavior is not research evidence.

Qdrant search is implemented, but the active scoring/prediction path never uses
it. Indexing initially writes `excluded=false` and does not update it after
scoring changes soft exclusion; integration must address this before depending
on retrieval exclusions.

## Verification and changes

- Required-document, feature-registry and feature-status checks passed before
  the audit. GitHub confirms PR #54 merged to `develop` at the baseline commit.
- Targeted bootstrap/application/provider/market/contract/manual-batch tests:
  **92 passed**. A separate deterministic reproduction confirmed the chronology
  defect, showing that the passing suite does not cover that ordering case.
- Feature-workflow validation tests: **14 passed**. Updated document/feature
  validation and diff checks passed; readiness reconciliation promoted only
  FEAT-022 after recording the actual FEAT-015 merge.
- Full infrastructure execution was not repeated for this documentation/registry
  audit. Prior final-head CI run `39210563422` passed PostgreSQL/Qdrant checks;
  real external artifacts were verified during FEAT-015 delivery.
- Changes are feature definitions/status/notes and this report, not runtime
  implementation. Existing scheduling/ingestion/observability entries were reused
  rather than creating duplicate features. One duplicate YAML
  `implementation_notes` key in historical FEAT-028 was removed while retaining
  both sets of notes.
