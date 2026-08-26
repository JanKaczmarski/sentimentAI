# Bounded Supervisor Demonstration

This runbook executes the FEAT-028 functional demonstration. It uses two
externally cached Applied Materials records listed in `demo/manifest.json`: one
SEC `8-K` earnings release and one official investor-relations prepared-remarks
PDF, both published on 2026-05-14.

The manifest is versioned with the application, but the raw source files remain
in the separate `sentimentAI-data` repository. The application verifies every
raw SHA-256 before ingestion. Cleaning uses `processing-v2`; raw content is
preserved and cleaned content, chunks, scores, provenance, snapshots, and
predictions are persisted by the normal pipeline.

## Prerequisites

- Docker Compose is installed and the repository root is the current directory.
- The sibling data repository exists at `../sentimentAI-data`, or
  `SENTIMENT_DATA_ROOT` points to it.
- Ollama is installed on the host and is serving `http://127.0.0.1:11434`.
- The local model is available:

```bash
ollama serve
ollama pull llama3.1:8b
```

The application uses `BAAI/bge-small-en-v1.5` for real local embeddings. The
first run may download that model into the host cache; it is not stored in this
repository.

## Start Compose

Create a local environment file and keep it untracked:

```bash
cp .env.example .env
```

The Compose configuration overrides the provider URL inside the application
container to `http://host.docker.internal:11434/v1`. It mounts the external
data repository read-only at `/data` and selects the bounded manifest.

```bash
docker compose build app
docker compose up -d postgres qdrant app
curl --fail http://localhost:8000/health
```

Check that the configured provider and manifest are active:

```bash
docker compose exec -T app env | sort | grep -E 'APP_ENV|DEMO_MANIFEST|EMBEDDING_|LLM_|SENTIMENT_DATA_ROOT'
docker compose logs app
```

The application must use `APP_ENV=research`, `LLM_BACKEND=ollama`,
`LLM_MODEL=llama3.1:8b`, `EMBEDDING_BACKEND=local`, and
`DEMO_MANIFEST_PATH=/app/demo/manifest.json`. Research mode rejects the
deterministic LLM and mock embeddings.

## Run Through The API

Create an account and retain the returned key only in the current shell:

```bash
ACCOUNT_JSON=$(curl --fail --silent --show-error \
  -X POST http://localhost:8000/user/account \
  -H 'content-type: application/json' \
  -d '{"email":"supervisor-demo@example.com","username":"supervisor-demo"}')
API_KEY=$(printf '%s' "$ACCOUNT_JSON" | jq -r .api_key)
USER_ID=$(printf '%s' "$ACCOUNT_JSON" | jq -r .user_id)
```

Create the AMAT Investment Thesis:

```bash
curl --fail --silent --show-error \
  -X POST 'http://localhost:8000/user/strategy?api_key='"$API_KEY" \
  -H 'content-type: application/json' \
  -d '{"companies":["AMAT"],"risk_tolerance":"medium","investment_horizon":"long_term","investment_style":"passive","description":"Supervisor functional demonstration."}' | jq
```

Run the bounded batch at the manifest cutoff:

```bash
BATCH_JSON=$(curl --fail --silent --show-error \
  -X POST http://localhost:8000/batch/run \
  -H 'content-type: application/json' \
  -d '{"company":"AMAT","as_of":"2026-05-14"}')
printf '%s\n' "$BATCH_JSON" | jq
```

The response should report two documents, non-zero chunks, three snapshots,
and a completed run. Inspect the personalized prediction and history:

```bash
curl --fail --silent --show-error \
  'http://localhost:8000/companies/AMAT/prediction?api_key='"$API_KEY"'&as_of=2026-05-14&forecast_horizon_days=20' | jq

curl --fail --silent --show-error \
  'http://localhost:8000/user/history/'"$USER_ID"'?api_key='"$API_KEY" | jq
```

The same workflow is available in the browser at
`http://localhost:8000/ui/`: create the account, create the AMAT thesis, run
the batch, and inspect the ranked sentiment-aware evidence and history.

## Verify Provenance

The run must record the Ollama provider, model, prompt, raw response, parsed
output, token usage, source manifest, and processing configuration. Inspect the
latest records without printing raw secrets:

```bash
docker compose exec -T postgres psql -U sentiment -d sentiment -c \
  "SELECT run_id, run_type, status, configuration->>'provider' AS provider, configuration->>'model' AS model FROM experiment_runs ORDER BY started_at DESC LIMIT 3;"

docker compose exec -T postgres psql -U sentiment -d sentiment -c \
  "SELECT run_id, input_source, input_version, model_provider, model_name, length(raw_response) AS raw_response_chars FROM experiment_provenance ORDER BY created_at DESC LIMIT 3;"
```

## Interpretation And Limits

- This is a two-document, one-company functional demonstration, not the
  five-year corpus or the six-company evaluation universe.
- The output proves source-to-prediction wiring, real embeddings, real local
  LLM scoring, persistence, provenance, API behavior, and UI behavior.
- It is not final thesis evaluation evidence and must not be used to tune
  prompts, thresholds, aggregation, personalization, or market conclusions.
- Market-outcome evaluation, complete corpus acquisition, contextual RAG,
  scheduling, and production provider hardening remain separate features.

## Stop Services

```bash
docker compose down
```

Do not use `docker compose down -v` unless deleting local experiment data is
intentional.
