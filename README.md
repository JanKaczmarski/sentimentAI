# Personalized Financial Sentiment System

Bachelor thesis implementation of a modular monolith using RAG, LLM-based
chunk scoring, and deterministic Investment Thesis personalization.

## Project Status

- Target implementation: `src/sentiment_system/`
- Legacy reference POC: `poc/`
- Architecture: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)
- Research decisions: [`docs/THESIS_DECISIONS.md`](docs/THESIS_DECISIONS.md)
- Supervisor reference: [`docs/Inżynierka_arch.docx`](docs/Inżynierka_arch.docx)

The new package is scaffolded and the first domain tests are implemented. The
legacy POC is preserved for comparison and sample data during the rebuild.

## Development Setup

```bash
uv sync
cp .env.example .env
```

This project uses Python 3.13, pinned by `.python-version`. If the local `uv`
configuration points to an unavailable private package index, the project
configuration uses public PyPI and an alternate-index strategy so normal
`uv sync`, `uv build`, and `uv run` commands can continue without private-index
credentials.

## Research Data Repository

Research inputs live in the separate `sentimentAI-data` repository rather than
in the application repository. `SENTIMENT_DATA_ROOT` is required before running
the SEC acquisition tools:

```bash
export SENTIMENT_DATA_ROOT=/path/to/sentimentAI-data
```

The acquisition tools fail fast when this variable is not set, preventing
research data from being written into the application repository by accident.

### Final Corpus Acquisition

The current research sample is **META, CRM, V, DIS, WHR, T**. Full historical
SEC acquisition and IR transcript curation use the reproducible workflow in
[`docs/RESEARCH_HISTORY_ACQUISITION.md`](docs/RESEARCH_HISTORY_ACQUISITION.md).
The external data repository's `data/research_history/README.md` and
`inventory.json` report actual files, date ranges, form counts, and gaps.
The historical cache is the acquisition superset for final corpus selection.
The frozen source selection is `thesis-v2-current-cache`: 363 eligible records from
2021-08-27 through 2026-08-27, with held-out publications starting 2024-08-28.
See decision [0015](decisions/0015-corpus-contract-corrections.md) for the derived
split, downloaded/reviewed sector evidence and operational/evaluation separation.
The active cleaned materialization is **`thesis-v2-current-cache-sec-form-aware-v2`**;
[decision 0016](decisions/0016-reviewed-cleaned-corpus-publication.md) retains the
original materialization, re-cleans all 243 SEC filings with the reviewed
implementation, and preserves all 120 transcript artifacts unchanged.
Operational ingestion also reads the full SEC history manifests. Stable original
byte revisions and immutable cleaned/chunk derivations are separated under
[decision 0017](decisions/0017-operational-history-and-source-derivations.md),
including PDF hash preservation and populated-database migration 0011.
The completed market/evaluation bundle is
**`thesis-v2-current-cache-sec-form-aware-v2-market-v1`**, linking the unchanged
corpus to eleven Nasdaq stock/ETF series through 2026-10-16, saved raw responses,
hash-pinned provenance and all five horizons' complete/unavailable coverage.
See [decision 0018](decisions/0018-frozen-market-snapshot-and-evaluation-coverage.md).

Publish the cleaning revision from the existing frozen selection, predecessor
corpus and saved extraction reviews (entirely offline):

```bash
export SENTIMENT_DATA_ROOT=/path/to/sentimentAI-data
uv run python -m scripts.acquire_corpus
uv run python -m scripts.freeze_evaluation_manifest --verify
```

See [`docs/FINAL_CORPUS_ACQUISITION.md`](docs/FINAL_CORPUS_ACQUISITION.md) for
the sector download/review workflow and immutable corpus layout. Never commit `.env`, its
`SEC_USER_AGENT` value, or acquired source material.

The exact data Git revision is pinned in `research-data.lock.json`. See
[`docs/FEAT_015_DELIVERY.md`](docs/FEAT_015_DELIVERY.md) for artifact identities,
verification results, infrastructure checks, and publication status.

The data repository contains raw source snapshots, market-price inputs, CIK
metadata, and acquisition manifests. Do not commit credentials or private
documents there.

## Development And Test Contract

The normal implementation loop is intentionally Docker-free. Run formatting,
linting, typing, tests, builds, and dependency audits directly through `uv`:

```bash
make test
make check
```

These commands must not start containers, build Docker images, or require a
running Docker daemon. Unit tests, local API tests, in-memory batch tests, and
cached-data tests use local or fake adapters. PostgreSQL, Qdrant, and full
Compose checks are separate infrastructure/e2e checks run in CI or explicitly
when validating a deployment.

## Local Services

Start the local integration environment with:

```bash
docker compose up --build
```

The scaffold exposes the API at `http://localhost:8000/health`, Prometheus at
`http://localhost:9090`, and Grafana at `http://localhost:3000`. The local API
testing UI is available at `http://localhost:8000/ui/`.

Open the UI after `make deploy` to create a local account, manage an Investment
Thesis, run a cached-corpus batch for the available research companies, and
inspect a prediction without composing curl requests. The API key is retained
only in the current browser session. See
[`docs/LOCAL_CACHED_CORPUS_RUNBOOK.md`](docs/LOCAL_CACHED_CORPUS_RUNBOOK.md) for
the browser workflow.

## Make Commands

Common development commands are available through the `Makefile`:

```bash
make sync
make test
make check
make compose-config
make deploy
make status
make logs
make down
```

`make deploy` starts the local Docker Compose integration stack in the
background. It is not a production deployment command.

`make compose-config` is an explicit Compose validation command and is not part
of the fast local `make check` loop. Use `make deploy` for the long-lived human
demo or local server.

## Checks

```bash
uv run black src tests
uv run isort src tests
uv run black --check src tests
uv run isort --check-only src tests
uv run ruff check src tests
uv run mypy
uv run pytest
uv build
uv run pip-audit
```

GitHub Actions additionally starts PostgreSQL and Qdrant and performs the
containerized integration checks and Compose validation. Those Docker steps are
CI/e2e checks, not part of the normal local implementation loop.

## Architecture Direction

The rebuild uses a small hexagonal core:

```text
domain -> application use cases -> ports -> adapters
```

The research pipeline is:

```text
ingest -> normalize -> chunk -> embed -> score -> aggregate
       -> apply Investment Thesis -> evaluate
```

Docker Compose services will provide the application, PostgreSQL, Qdrant,
Prometheus, and Grafana as the infrastructure is implemented.
