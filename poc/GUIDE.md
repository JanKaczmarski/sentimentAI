# POC — Sentiment Analysis System

End-to-end proof of concept: SEC filings -> chunking -> embeddings -> Qdrant -> RAG -> LLM -> sentiment per user profile.

## Quick start

```bash
cd /Users/jkaczmarski/private/sentimentAI

# 1. Set up Groq API key (free tier, https://console.groq.com)
cp .env.example .env
# edit .env, paste GROQ_API_KEY=...

# 2. Demo (one-shot, wyniki w konsoli):
.venv/bin/python -m poc.main --demo

# Serwer API (Swagger UI: http://localhost:8000/docs):
.venv/bin/python -m poc.main

# Serwer bez daily schedulera:
.venv/bin/python -m poc.main --no-scheduler
```

### Backend LLM

POC domyslnie uzywa **Groq** (hosted Llama-3.3-70B, free tier). Wymaga `GROQ_API_KEY` w `.env`.

Bez klucza system **rzuci wyjatek przy starcie batcha** — zamiast cichego fallbacku do mocka. To celowe: nie chcemy zeby zepsuty setup wygladal jak dzialajacy POC.

Zmiana backendu w `poc/config.py`:
- `LLM_BACKEND = "groq"` — domyslny, hosted Llama
- `LLM_BACKEND = "mock"` — keyword heuristic, tylko do dev/testow offline (wyniki tagowane `[MOCK]`)
- `LLM_BACKEND = "cyfronet"` — placeholder, jeszcze niezaimplementowane

## Przykladowy flow przez API

```bash
# 1. Utworz usera
curl -X POST http://localhost:8000/users \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Jan",
    "risk_tolerance": "medium",
    "investment_horizon": "long_term",
    "investment_style": "passive",
    "watchlist": ["NVDA", "AAPL", "MSFT"]
  }'
# -> zwraca user_id

# 2. Odpala batch (ingest + chunk + embed + RAG + LLM dla kazdego tickera)
curl -X POST http://localhost:8000/batch/run

# 3. Pobierz wyniki
curl "http://localhost:8000/users/{user_id}/predictions"

# 4. Pojedyncza predykcja
curl "http://localhost:8000/companies/NVDA/prediction?user_id={user_id}"

# 5. Status ostatniego batcha
curl http://localhost:8000/batch/status

# 6. Info o vector store
curl http://localhost:8000/system/info
```

## Struktura modulow

```
poc/
├── main.py           # Entry point — serwer + scheduler albo --demo
├── config.py         # Konfiguracja (sciezki, model, prompt template, scheduler)
├── models.py         # Pydantic modele (UserProfile, Document, SentimentResult, BatchRun)
├── database.py       # SQLite (users, sentiment results, batch runs)
├── ingestion.py      # Laduje SEC filings z ../llm-sentiment-analysis/data/raw/
├── processing.py     # Chunking (sentence-based) + embeddingi (real lub mock fallback)
├── vector_store.py   # Qdrant in-memory (cosine similarity, filtrowanie po ticker)
├── llm_client.py     # Mock LLM (keyword heuristic) + interfejs pod Cyfronet LLAMA
├── batch.py          # Batch processor — orchestruje caly flow
├── api.py            # FastAPI routes
├── TODO.md           # Co zostalo do zrobienia
└── GUIDE.md          # Ten plik
```

## Jak dziala batch processing

```
1. Zaladuj wszystkich userow z SQLite
2. Zbierz unikalne tickery z watchlist-ow
3. Dla kazdego tickera:
   - Wczytaj SEC filings z data/raw/{ticker}/
   - Podziel na chunki (3 zdania / chunk)
   - Wygeneruj embeddingi
   - Zaindeksuj w Qdrant
4. Dla kazdej pary (user, ticker):
   - Zbuduj RAG query na podstawie profilu usera
   - Pobierz top-5 chunki z Qdrant (semantic search)
   - Wywolaj LLM z kontekstem + profilem inwestora
   - Zapisz SentimentResult do SQLite
```

Scheduler (APScheduler) uruchamia ten flow codziennie o 02:00.
Mozna tez odpalic recznie: `POST /batch/run`.

## Co jest zamockowane

**Embeddingi** — `processing.py` probuje zaladowac `BAAI/bge-small-en-v1.5` (SentenceTransformer). **W tej sieci huggingface.co jest blokowany przez Cisco Umbrella** (corporate policy), wiec POC dziala na mock embeddingach (deterministic hash-based). Skutek: vector search zwraca losowe chunki. Do naprawienia jeden z: (a) IT exception na huggingface.co, (b) sciagnac model na innej sieci i committnac lokalnie, (c) hosted embeddings API.

**LLM** — `HostedLLMClient` (Groq, Llama-3.3-70B) to domyslny backend. `MockLLMClient` (keyword heuristic, tylko opt-in via `LLM_BACKEND="mock"`) zostal zachowany do dev/testow offline. `CyfronetLLMClient` to placeholder pod prawdziwy endpoint (vLLM/OpenAI-compatible).

## Dane

POC czyta gotowe SEC filings z repo kolegi:
```
../llm-sentiment-analysis/data/raw/
├── AAPL/   (8-K, 10-K filings)
├── NVDA/
├── MSFT/
└── ... (96 tickerow)
```

Wyniki i profile trzymane w SQLite: `data/poc.db`
Vector store: Qdrant in-memory (resetuje sie przy restarcie serwera).

## Zaleznosci

Zainstalowane w `.venv/`:
- fastapi, uvicorn — API
- qdrant-client — vector store (in-memory mode)
- sentence-transformers — embeddingi (z mock fallback)
- apscheduler — daily batch cron
- torch — wymagany przez sentence-transformers
- openai — OpenAI-compatible client (uzywany dla Groq, w przyszlosci tez Cyfronet vLLM)
- python-dotenv — ladowanie `.env`

Instalacja:
```bash
.venv/bin/pip install --index-url https://pypi.org/simple/ \
  fastapi uvicorn qdrant-client sentence-transformers apscheduler \
  openai python-dotenv
```
