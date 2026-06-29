# TODO — remaining work to match arch.pdf

## Must-have (system niekompletny bez tego)

- [x] **Real LLM integration** — Groq (hosted Llama-3.3-70B) podlaczone via `HostedLLMClient` w `poc/llm_client.py`. OpenAI-compatible interfejs, czyli swap na Cyfronet vLLM bedzie tylko zmiana base_url + api_key. **Wymaga `GROQ_API_KEY` w `.env`** (free tier https://console.groq.com).
- [ ] **Real Cyfronet integration** — `CyfronetLLMClient` to nadal placeholder. Gdy AGH postawi vLLM server, mozemy podpiac `HostedLLMClient(base_url=cyfronet_url, ...)` bez zmian w batch logic. Kolega ma alternatywnie SLURM batch job (`running_sentiment_analysis_on_remote/predict_sentiment_with_llama.py`) — drugi wariant jakby vLLM byl problem.
- [ ] **Real embeddings** — **BLOCKED**: huggingface.co zablokowane przez Cisco Umbrella (corporate proxy) na tej sieci. Mock embeddings sa nadal aktywne. Do naprawienia: IT exception, lokalny model, lub hosted embeddings API. Zobacz `BACKLOG.md` po szczegoly.
- [ ] **Email ingestion / webhook** — `POST /companies/{companyId}` endpoint + IMAP polling lub webhook receiver do przyjmowania maili od firm. Arch wymaga tego jako zrodlo danych obok SEC API.
- [ ] **Strategy CRUD per company** — endpointy `POST/PUT/GET /user/strategy` z granularnoscia per spolka. Teraz user ma jeden globalny profil + watchlist. Arch wymaga osobnej strategii (passive/aggressive) per company lub grupa companies.
- [ ] **Relevancy assessment (2-step LLM)** — arch zaklada `POST /lama/relevancy` gdzie LLM ocenia ktore chunki sa relevantne ZANIM generuje sentiment. POC robi to przez vector similarity (moze wystarczyc — do dyskusji czy potrzebny osobny LLM step).

## Should-have (wazne ale system dziala bez tego)

- [ ] **Admin vs User roles** — rozdzielenie uprawnien. Arch ma `?Admin?` header na niektorych endpointach (`GET /user/history/{userID}`, `POST /companies/{companyId}`). Potrzebny prosty auth (JWT/API key).
- [ ] **Public API integration (market data)** — Yahoo Finance / Alpha Vantage. Kolega ma `data_preparation/stage4_share_prices.py` (Stooq API). Do zintegrowania z POC ingestion pipeline.
- [ ] **Importance score** — pole `importance_score` na Document, uzywane do filtrowania przy retrieval. Arch wspomina ale nie definiuje jak obliczac (reczne reguły? LLM? heurystyka?).
- [ ] **Prediction time horizon** — logika "predykcja na X miesiecy" (NF4: "Model provides predictions up to two years period"). Teraz predykcja nie uwzglednia horyzontu czasowego.
- [ ] **Endpoint paths alignment** — dopasowac sciezki API do arch.pdf (`/user/strategy` zamiast `/users`, `/user/account` zamiast `POST /users`, itp.).

## Nice-to-have / do dyskusji

- [ ] **Batch processing w arch doc** — arch.pdf NIE opisuje batch flow. Dodac sekcje o batch processing do dokumentu architekturalnego (scheduler, batch_run entity, flow diagram).
- [ ] **Persistent Qdrant** — POC uzywa in-memory. Dla produkcji: Docker container z persistent storage.
- [ ] **Historical backtesting** — arch wspomina "won't do > 3 years" ale sam backtesting interface nie jest zdefiniowany.
- [ ] **CI/CD + pre-commit hooks** — kolega ma `.pre-commit-config.yaml` (black, isort, ruff). Do przeniesienia do tego repo.
- [ ] **Docker Compose** — arch wspomina FastAPI + Qdrant + PostgreSQL. POC uzywa SQLite + Qdrant in-memory. Do zrobienia: `docker-compose.yml`.
- [ ] **Monitoring / logging** — POC loguje do stdout. Produkcja potrzebuje structured logging, metryki batch runów, alerty na failure.

## Co juz jest gotowe (reference)

- [x] User profile CRUD (basic)
- [x] Sentiment prediction (mock LLM)
- [x] Batch processing pipeline (ingest -> chunk -> embed -> RAG -> LLM -> save)
- [x] APScheduler (daily cron)
- [x] SQLite persistence (users, results, batch runs)
- [x] Qdrant vector store (in-memory, cosine search, ticker filtering)
- [x] SEC filings ingestion (from colleague's data/raw/)
- [x] Chunking (sentence-based, abbreviation-aware — from colleague's code)
- [x] FastAPI REST API z Swagger UI
- [x] Source chunks tracking (reasoning + chunk_ids in response)
