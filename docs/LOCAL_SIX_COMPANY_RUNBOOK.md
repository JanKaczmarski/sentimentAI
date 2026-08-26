# Local Six-Company Workflow

This runbook starts the normal local application path for the six-company
functional snapshot: `AAPL`, `MSFT`, `NVDA`, `JPM`, `XOM`, and `JNJ`. It reads
the external `sentimentAI-data` cache and does not require the AMAT supervisor
manifest.

## Prerequisites

- The application repository and sibling `sentimentAI-data` repository exist.
- Ollama is running on the host at `http://127.0.0.1:11434`.
- The local models are available:

```bash
ollama pull llama3.1:8b
ollama pull nomic-embed-text
```

Create the local environment file if needed:

```bash
cp .env.example .env
```

The Compose file mounts `SENTIMENT_DATA_ROOT` read-only and uses the cached
corpus source by default. `DEMO_MANIFEST_PATH` is intentionally not set by
default; it may be added to `.env` only when reproducing the separate AMAT
supervisor fixture.

## Start The Application

```bash
docker compose up --build -d postgres qdrant app
curl --fail http://localhost:8000/health
```

Confirm that the default runtime does not select the supervisor manifest:

```bash
docker compose exec -T app env | sort | grep -E 'APP_ENV|DEMO_MANIFEST|EMBEDDING_|LLM_|SENTIMENT_DATA_ROOT|QDRANT_COLLECTION'
```

The expected runtime uses `APP_ENV=research`, `LLM_BACKEND=ollama`,
`EMBEDDING_BACKEND=ollama`, and `QDRANT_COLLECTION=research_chunks`.

## Use The Browser

Open `http://localhost:8000/ui/` and:

1. Create an account.
2. Create a thesis for one or more of `AAPL`, `MSFT`, `NVDA`, `JPM`, `XOM`,
   and `JNJ`.
3. Select a research ticker and set the as-of date to `2026-06-30`.
4. Run the batch and inspect the base sentiment, personalized sentiment,
   confidence, and ranked evidence.

Risk tolerance, investment horizon, investment style, and thesis description
remain configurable. They are not fixed by the six-company snapshot.

## API Smoke Check

The UI is the recommended path, but the same workflow can be checked through
the API. Use a unique email and username for each fresh account:

```bash
ACCOUNT_JSON=$(curl --fail --silent --show-error \
  -X POST http://localhost:8000/user/account \
  -H 'content-type: application/json' \
  -d '{"email":"local-six-company@example.com","username":"local-six-company"}')
API_KEY=$(printf '%s' "$ACCOUNT_JSON" | jq -r .api_key)
USER_ID=$(printf '%s' "$ACCOUNT_JSON" | jq -r .user_id)
```

```bash
curl --fail --silent --show-error \
  -X POST 'http://localhost:8000/user/strategy?api_key='"$API_KEY" \
  -H 'content-type: application/json' \
  -d '{"companies":["AAPL","MSFT","NVDA","JPM","XOM","JNJ"],"risk_tolerance":"medium","investment_horizon":"long_term","investment_style":"passive"}' | jq
```

Run one ticker at a time. A batch scores all cached documents for the selected
ticker and does not use a user-specific LLM call:

```bash
BATCH_JSON=$(curl --fail --silent --show-error \
  -X POST http://localhost:8000/batch/run \
  -H 'content-type: application/json' \
  -d '{"company":"AAPL","as_of":"2026-06-30"}')
```

```bash
curl --fail --silent --show-error \
  'http://localhost:8000/companies/AAPL/prediction?api_key='"$API_KEY"'&as_of=2026-06-30&forecast_horizon_days=20' | jq

curl --fail --silent --show-error \
  'http://localhost:8000/user/history/'"$USER_ID"'?api_key='"$API_KEY" | jq
```

Repeat the batch and prediction requests with `MSFT`, `NVDA`, `JPM`, `XOM`,
and `JNJ` to verify the full functional snapshot.

## Boundary

This is a functional local snapshot, not the final five-year thesis corpus,
held-out evaluation manifest, or market-outcome result. The current snapshot
uses one official SEC earnings-release record per research company. Curated
investor-relations records remain supported by the cache adapter and are
expanded separately.

## Stop Services

```bash
docker compose down
```

Do not use `docker compose down -v` unless deleting local experiment data is
intentional.
