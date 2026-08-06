# Agent Guide

## Scope

- Use Python 3.13 through `uv`; `.python-version` pins the project interpreter.
- The thesis implementation lives in `src/sentiment_system/` and follows a modular monolith with a small hexagonal core.
- `poc/` is the legacy implementation and sample-data reference; do not extend it unless explicitly comparing the old POC with the rebuild.
- `ARCHITECTURE.md` is the target system design; `THESIS_DECISIONS.md` contains detailed research decisions and open questions.
- `Inzynierka_arch.docx` is the supervisor-commented architecture reference, not the executable specification.

## Structure

- `domain/` contains pure entities and business rules.
- `application/ports/` contains interfaces for external systems.
- `application/use_cases/` coordinates workflows through ports.
- `adapters/` contains FastAPI, scheduler, LLM, embeddings, data-source, persistence, vector, and metrics integrations.
- `bootstrap/` is the composition root and runtime entrypoint.
- `tests/unit/` covers domain/use-case rules; `tests/contract/` covers adapter contracts; `tests/integration/` covers infrastructure and API behavior.

## Development Rules

- Use `uv sync` to create/update the environment from `pyproject.toml` and `uv.lock`; do not add a separate requirements file.
- Follow TDD: write a failing domain/use-case test, implement the smallest behavior, then add adapter/integration coverage.
- Keep domain and application code independent of FastAPI, PostgreSQL, Qdrant, Docker, and provider SDKs.
- Add ports only for replaceable or external boundaries: LLM, embeddings, document sources, market data, vector store, and repositories.
- Use fake adapters for fast unit tests; reserve real services for contract and integration tests.
- The rebuild uses two stages: investor-independent chunk scoring/aggregation, followed by deterministic Investment Thesis personalization.
- Real local embeddings are required for research results; mock embeddings are test-only.
- Never store API keys or other secrets in source code, fixtures, prompts, or experiment artifacts.

## Verification

- Format with `uv run black src tests` and `uv run isort src tests`.
- Verify with `uv run black --check src tests`, `uv run isort --check-only src tests`, `uv run ruff check src tests`, `uv run mypy`, `uv run pytest`, `uv build`, and `uv run pip-audit`.
- Current scaffold check: `uv run python -m compileall -q src tests`.
- Do not run the legacy demo with `--demo` when preserving its ignored local database matters; it deletes `data/poc.db`.
