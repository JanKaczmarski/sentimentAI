# Backlog — Sentiment Analysis System

## Setup & Infrastruktura

- [x] Inicjalizacja repo + git
- [x] Python venv + instalacja zaleznosci (fastapi, qdrant-client, sentence-transformers, apscheduler, uvicorn)
- [x] `.gitignore` (venv, db, pycache, data, env, IDE)
- [ ] `pyproject.toml` / `requirements.txt` — pinowane wersje zaleznosci
- [ ] Pre-commit hooks (black, isort, ruff) — kolega ma `.pre-commit-config.yaml` do przeniesienia
- [ ] Docker Compose (FastAPI + Qdrant persistent + PostgreSQL)
- [ ] CI/CD pipeline (linting, testy, build)

## Dokumentacja

- [x] Architektura (arch.pdf) — draft v0.1
- [ ] Aktualizacja arch.pdf o batch processing (1x/dzien zamiast on-demand)
- [x] POC guide (`poc/GUIDE.md`)
- [x] TODO lista (`poc/TODO.md`)
- [x] Backlog (ten plik)

## Data Models & Database

- [x] Pydantic modele (UserProfile, Document, DocumentChunk, SentimentResult, BatchRun)
- [x] Enumy (RiskTolerance, InvestmentHorizon, InvestmentStyle, Sentiment, ComputationType)
- [x] SQLite schema (user_profiles, sentiment_results, batch_runs) + indeksy
- [x] CRUD: create/get user, save/get sentiment results, save/get batch runs
- [ ] Migracja na PostgreSQL (produkcja)
- [ ] Importance score na Document — filtrowanie mniej waznych dokumentow przy retrieval
- [ ] Strategy per company (arch wymaga osobnej strategii passive/aggressive per spolka, nie tylko globalny profil)

## Data Ingestion

- [x] Ladowanie SEC filings z kolegi `data/raw/` (96 tickerow)
- [x] Parsowanie nazw plikow (data, accession number, form type)
- [x] Text normalization (whitespace collapse, null bytes)
- [ ] Live SEC EDGAR API polling — zintegrowac kolegi `sec_api_client.py` do POC
- [ ] Email ingestion (IMAP polling) — nowe zrodlo danych
- [ ] Email webhook endpoint (`POST /companies/{companyId}`) — przyjmowanie maili
- [ ] Public API integration (Yahoo Finance / Alpha Vantage) — market data, kolega ma `stage4_share_prices.py`
- [ ] Historical batch import z oznaczeniem `document_date`

## Processing Pipeline

- [x] Sentence-based chunking (3 zdania/chunk, abbreviation-aware) — z kodu kolegi
- [x] Embedding generation z fallback (real SentenceTransformer -> mock hash-based)
- [ ] Naprawic SSL cert issue i pobrac `BAAI/bge-small-en-v1.5`
- [ ] Rozwazyc lepszy model embeddingowy (np. `bge-m3` dla multilingual)

## Vector Store

- [x] Qdrant in-memory (cosine similarity, filtrowanie po ticker)
- [x] Indexowanie chunkow z payloadem (chunk_id, doc_id, ticker, filing_date, content)
- [x] Semantic search z top-K retrieval
- [ ] Qdrant persistent (Docker, dane przetrwaja restart)
- [ ] Filtrowanie po dacie przy retrieval (potrzebne do backtestingu)

## RAG & LLM

- [x] RAG flow: query -> vector search -> context assembly -> prompt building
- [x] Prompt template z profilem inwestora (risk_tolerance, horizon, style)
- [x] Mock LLM (keyword heuristic — pos/neg signal counting)
- [x] Interfejs `BaseLLMClient` + `CyfronetLLMClient` placeholder
- [ ] Podlaczyc prawdziwa LLAMA na Cyfronet — wariant A: SLURM batch (kolega ma gotowy skrypt) lub wariant B: vLLM server z OpenAI-compatible API
- [ ] 2-step LLM: relevancy assessment (`POST /lama/relevancy`) + sentiment prediction — arch zaklada ze LLM najpierw wybiera relevantne chunki
- [ ] Prompt engineering — iteracja nad promptem z prawdziwym modelem
- [ ] Ewaluacja accuracy na testowych danych

## Batch Processing

- [x] Batch processor (ingest -> chunk -> embed -> index -> RAG -> LLM -> save)
- [x] APScheduler (cron codziennie o 02:00)
- [x] Manual trigger przez API (`POST /batch/run`)
- [x] BatchRun entity (started_at, finished_at, stats, status)
- [ ] Retry logic na failed batch items
- [ ] Batch triggerowany przez nowe dokumenty (nie tylko cron)
- [ ] Monitoring / alerty na batch failure

## API (FastAPI)

- [x] `POST /users` — tworzenie usera
- [x] `GET /users` — lista userow
- [x] `GET /users/{user_id}` — profil usera
- [x] `GET /users/{user_id}/predictions` — predykcje usera (latest lub per date)
- [x] `GET /companies/{ticker}/prediction` — predykcja per spolka
- [x] `POST /batch/run` — manual batch trigger
- [x] `GET /batch/status` — status ostatniego batcha
- [x] `GET /system/info` — stats vector store
- [ ] `POST /user/strategy` — zapis strategii per company
- [ ] `PUT /user/strategy` — update strategii
- [ ] `GET /user/strategy` — lista spolek usera
- [ ] `GET /user/strategy/{companyID}` — strategia per spolka
- [ ] `POST /companies/{companyId}` — email webhook
- [ ] Auth (JWT / API key) + rozdzielenie admin/user
- [ ] Dopasowanie sciezek do arch.pdf (`/user/account`, `/user/strategy`, `/user/history/{userID}`)

## Testy & Jakosc

- [ ] Unit testy (models, database, chunking, ingestion)
- [ ] Integration testy (batch flow end-to-end)
- [ ] API testy (FastAPI TestClient)
- [ ] Ewaluacja LLM accuracy na labeled data
- [ ] Load testing batch (ile tickerow/userow wytrzyma)
- [ ] NFR: "Prompt < X min" — zmierzyc z prawdziwym LLM
- [ ] NFR: "Model accuracy >= X%" — zdefiniowac metryki i benchmark
