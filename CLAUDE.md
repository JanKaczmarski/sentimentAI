# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Sentiment Analysis POC: an end-to-end RAG pipeline that ingests SEC filings, chunks/embeds them, retrieves relevant passages from a vector store, and asks an LLM to classify per-ticker sentiment for a given investor profile. The POC lives entirely in `poc/`. The architectural draft for the full target system is in `arch.pdf`; outstanding work to reach that target is tracked in `BACKLOG.md` and `poc/TODO.md`.

## Common Commands

All commands assume the repo root `/Users/jkaczmarski/private/sentimentAI` and use the bundled venv at `.venv/`.

```bash
# Set up the LLM key first (Groq free tier — required by default LLM_BACKEND='groq')
cp .env.example .env  # then paste GROQ_API_KEY=...

# One-shot demo (creates demo user, runs batch, prints results — no server)
.venv/bin/python -m poc.main --demo

# API server with daily scheduler — Swagger UI at http://localhost:8000/docs
.venv/bin/python -m poc.main

# API server without scheduler
.venv/bin/python -m poc.main --no-scheduler

# Manual batch trigger over the API
curl -X POST http://localhost:8000/batch/run

# Install dependencies (no requirements.txt yet — see BACKLOG.md)
.venv/bin/pip install --index-url https://pypi.org/simple/ \
  fastapi uvicorn qdrant-client sentence-transformers apscheduler \
  openai python-dotenv
```

There is no test suite, linter, or build configured yet (these are listed as TODO in `BACKLOG.md`).

## Architecture

The system is a single FastAPI application that doubles as a batch worker. Everything is wired together in `poc/main.py:create_app`, which constructs shared `Database` and `VectorStore` instances and injects them into the API module via `init_api()` and into the APScheduler job via a closure.

### Data flow (batch is the heart of the system)

`run_batch` in `poc/batch.py:34` orchestrates the full pipeline:

1. Load all users from SQLite (`poc/database.py`).
2. Union all watchlist tickers across users.
3. For each ticker: `ingestion.load_filings_for_ticker` reads pre-downloaded SEC `.txt` files from the **sibling repo** at `../llm-sentiment-analysis/data/raw/{ticker}/` (path defined in `poc/config.py:14`, `RAW_FILINGS_DIR`). `processing.chunk_document` does sentence-based chunking (3 sentences/chunk, abbreviation-aware regex). `vector_store.index_chunks` embeds and upserts into Qdrant.
4. For each `(user, ticker)` pair: build a RAG query, retrieve top-K chunks with a `company_ticker` filter, then call the LLM client with `(ticker, chunks, user_profile)`. Save a `SentimentResult` to SQLite.

The same flow is invoked both by the APScheduler cron (daily at 02:00, see `poc/main.py:start_scheduler`) and by the `POST /batch/run` endpoint.

### Key abstractions and pluggability

- **LLM backend** — `poc/llm_client.py` defines `BaseLLMClient` with three implementations: `HostedLLMClient` (default, OpenAI-compatible client pointed at Groq Llama-3.3-70B), `MockLLMClient` (keyword heuristic, **must be opted into** via `LLM_BACKEND="mock"` — never a silent fallback), and `CyfronetLLMClient` (placeholder, raises on construction). Selection driven by `LLM_BACKEND` in `poc/config.py`. The factory `get_llm_client()` raises loudly if `groq` is selected but `GROQ_API_KEY` is missing — this is intentional. Prompt comes from `SENTIMENT_PROMPT_TEMPLATE` in config. JSON parsing is defensive (handles raw, fenced, prose-wrapped). Retry-with-backoff (2 attempts) for transient errors; permanent failures return a NEUTRAL result with the error in `reasoning` so a single bad ticker doesn't abort the batch.
- **Embeddings** — `poc/processing.py:_init_embedder` tries `BAAI/bge-small-en-v1.5` via `sentence-transformers` and **silently** falls back to a deterministic SHA-256-seeded mock embedding (`_mock_embed`) when the model can't be loaded. **Currently always falling back**: `huggingface.co` is blocked by Cisco Umbrella corporate proxy on this network. The mock vectors are unit-norm 384-dim but semantically random — RAG retrieval is therefore essentially random until this is fixed. See `BACKLOG.md` for options.
- **Vector store** — `poc/vector_store.py` wraps `QdrantClient(":memory:")`. State is lost on every server restart — the batch must repopulate it. The collection is created lazily in `_ensure_collection` with cosine distance.
- **Persistence** — `poc/database.py` is a thin SQLite layer (file at `data/poc.db`). Schema is created idempotently from `_CREATE_TABLES_SQL` on `Database.__init__`. Three tables: `user_profiles`, `sentiment_results`, `batch_runs`. The `get_sentiments_for_user` query without a date returns the latest result per ticker via a self-join on `MAX(batch_date)`.

### Module boundaries

- `models.py` — Pydantic models + enums; the source of truth for shapes used across DB, API, and LLM.
- `config.py` — all tunables (paths, embedding model, chunking sizes, schedule, LLM backend, prompt template).
- `api.py` — FastAPI router. Dependencies are module-level globals (`_db`, `_vs`) populated by `init_api()`; the router itself doesn't construct anything.
- `ingestion.py`, `processing.py`, `vector_store.py`, `llm_client.py` — stateless or singleton helpers consumed by `batch.py`.
- `batch.py` — the only place that ties ingestion + processing + retrieval + LLM + persistence together.

### External dependency on a sibling repo

The POC does **not** ship any raw filings. It reads from `../llm-sentiment-analysis/data/raw/`, which is a separate repo (a colleague's project). If that path is missing, `get_available_tickers()` returns `[]` and the demo exits early. A lot of the chunking and prompt logic was adapted from that repo as well — keep this in mind when changing chunking or prompt code.

## Conventions and Constraints

- Python 3 with `from __future__`-style typing (`str | None`, `list[str]`); requires Python 3.10+.
- Mixed Polish/English in comments and docstrings — preserve the existing language when editing a file.
- IDs are UUID4 strings generated via Pydantic `default_factory`.
- No auth, no migrations, no Docker. These are explicitly out of scope for the POC and tracked as TODO.
- The Qdrant collection is in-memory: any code that assumes existing vectors across restarts is wrong; always think batch-first.
