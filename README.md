# Personalized Financial Sentiment System

Bachelor thesis implementation of a modular monolith using RAG, LLM-based
chunk scoring, and deterministic Investment Thesis personalization.

## Project Status

- Target implementation: `src/sentiment_system/`
- Legacy reference POC: `poc/`
- Architecture: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)
- Research decisions: [`docs/THESIS_DECISIONS.md`](docs/THESIS_DECISIONS.md)
- Supervisor reference: [`docs/Inżynierka_arch.docx`](docs/Inżynierka_arch.docx)
- Contributor handoff: [`docs/GETTING_STARTED.md`](docs/GETTING_STARTED.md)

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

The data repository contains raw source snapshots, market-price inputs, CIK
metadata, and acquisition manifests. Do not commit credentials or private
documents there.

## Local Services

Start the local integration environment with:

```bash
docker compose up --build
```

The scaffold exposes the API at `http://localhost:8000/health`, Prometheus at
`http://localhost:9090`, and Grafana at `http://localhost:3000`.

## Make Commands

Common development commands are available through the `Makefile`:

```bash
make sync
make test
make check
make deploy
make status
make logs
make down
```

`make deploy` starts the local Docker Compose integration stack in the
background. It is not a production deployment command.

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

GitHub Actions runs the same checks on pushes to `main` and pull requests.

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
