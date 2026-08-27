# Local Cached-Corpus Workflow

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

## Stop Services

    docker compose down

Do not use `docker compose down -v` unless deleting local experiment data is
intentional.
