# Personalized Financial Sentiment System

Bachelor thesis implementation of a modular monolith using RAG, LLM-based
chunk scoring, and deterministic Investment Thesis personalization.

## Project Status

- Target implementation: `src/sentiment_system/`
- Legacy reference POC: `poc/`
- Architecture: `ARCHITECTURE.md`
- Research decisions: `THESIS_DECISIONS.md`
- Supervisor reference: `Inzynierka_arch.docx`

The new package is scaffolded and the first domain tests are implemented. The
legacy POC is preserved for comparison and sample data during the rebuild.

## Development Setup

```bash
uv sync
cp .env.example .env
```

This project uses Python 3.13, pinned by `.python-version`. If the local `uv`
configuration points to an unavailable private package index, use
`uv sync --no-config` or configure valid index credentials.

## Local Services

Start the local integration environment with:

```bash
docker compose up --build
```

The scaffold exposes the API at `http://localhost:8000/health`, Prometheus at
`http://localhost:9090`, and Grafana at `http://localhost:3000`.

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
