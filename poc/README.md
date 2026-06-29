# POC Runbook

Krotki przewodnik jak pokazac demo. Pelniejsze tlo: `poc/GUIDE.md`, `CLAUDE.md`.

## Setup (raz)

```bash
cp .env.example .env       # GROQ_API_KEY juz w przykladzie
.venv/bin/pip install -r requirements.txt   # albo: openai python-dotenv fastapi uvicorn apscheduler qdrant-client pydantic
```

## 1. One-shot demo (offline-friendly, ~30s)

```bash
.venv/bin/python -m poc.main --demo
```

Co widac:
- `Wiped previous demo state` — kasuje `data/poc.db`, demo jest deterministyczne (1 user × 3 tickery = 3 calls do Groqa).
- `POC_FORCE_MOCK_EMBEDDINGS=1` — embeddingi mockowe (HF zablokowany przez Cisco Umbrella).
- `--- Ingesting NVDA/AAPL/MSFT ---` → ladowanie 3 plikow per ticker z `poc/sample_data/raw/<TICKER>/`.
- `Throttling LLM call: sleeping 12.3s` — odstep 13s miedzy callami (Groq free TPM cap).
- `[Groq] NVDA -> POSITIVE (confidence=0.80)` — wynik LLM.
- Sekcja `RESULTS` na koncu: per-ticker sentyment + confidence + reasoning + chunki uzyte.

## 2. Server + Swagger (dla manualnego klikania)

```bash
.venv/bin/python -m poc.main           # http://localhost:8000/docs
.venv/bin/python -m poc.main --no-scheduler   # bez batcha o 02:00
```

Co widac w Swagger UI:
- `POST /users` — stworz usera z watchlist (`["NVDA","AAPL","MSFT"]`).
- `POST /batch/run` — odpal batch on-demand zamiast czekac do 02:00.
- `GET /users/{user_id}/sentiments` — wyniki per ticker.

## Co i gdzie zmienic

| Co | Plik | Zmienna |
|---|---|---|
| Inne tickery w demo | `poc/config.py` | `POC_TICKERS` (musza miec dane w `sample_data/raw/`) |
| Ile plikow per ticker | `poc/main.py:134` | `max_files_per_ticker=3` |
| Backend LLM | `.env` lub `poc/config.py` | `LLM_BACKEND` = `groq` / `mock` / `cyfronet` |
| Throttle Groqa | `poc/config.py` | `LLM_MIN_INTERVAL_SECONDS` (0 = off) |
| Pora batcha | `poc/config.py` | `BATCH_SCHEDULE_HOUR/MINUTE` |
| Zrodlo dokumentow | `poc/config.py` | `RAW_FILINGS_DIR` (domyslnie `poc/sample_data/raw`) |
| Wlaczyc real embeddingi | `.env` | `POC_FORCE_MOCK_EMBEDDINGS=0` (wymaga niezablokowanego HF) |

## Quick sanity checks

```bash
ls poc/sample_data/raw/NVDA/   # 3 pliki .txt
cat poc/sample_data/raw/AAPL/2025-01-30_*_8-K.txt | head -50   # podgladnij na czym Llama analizuje
sqlite3 data/poc.db "SELECT company_ticker, sentiment, confidence FROM sentiment_results;"
```
