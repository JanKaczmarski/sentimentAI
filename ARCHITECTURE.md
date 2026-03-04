# Architecture Overview — AI Sentiment Analysis System
> Engineering Thesis | 2-person team | v0.1 draft

---

## 1. Cel systemu

System analizuje sentyment dokumentów finansowych (raporty wynikowe, transkrypty konferencji) względem profilu inwestora i odpowiada na pytania w stylu:

> "Czy wyniki Nvidii z Q3 2024 są pozytywne dla długoterminowego, pasywnego inwestora?"

Odpowiedź zawiera: ocenę sentymentu (pozytywny / neutralny / negatywny) + cytaty z dokumentów źródłowych uzasadniające ocenę.

---

## 2. Źródła danych

| Źródło | Format | Sposób ingestion | Priorytet |
|--------|--------|-----------------|-----------|
| Emaile od firm (earnings, guidance) | HTML/plain text | IMAP polling / webhook | MVP |
| Transkrypty konferencji wynikowych | PDF / TXT | Upload lub email attachment | MVP |
| Publiczne API rynkowe (Yahoo Finance / Alpha Vantage) | JSON | REST polling | podstawowa funkcjonalność |
| Dane historyczne (backtesting) | PDF / CSV | Batch import, oznaczone datą | testowanie |

**Uwaga dot. danych historycznych:** dokumenty historyczne są oznaczane oryginalną datą (`document_date`), dzięki czemu system może być odpytywany "z perspektywy" dowolnego momentu w przeszłości (filtrowanie po dacie przy RAG retrieval).

---

## 3. Architektura wysokiego poziomu

```
┌─────────────────────────────────────────────────────────────────────┐
│                        DATA INGESTION LAYER                         │
│                                                                     │
│  [Email (IMAP)]  [PDF Upload]  [Public API]  [Historical Batch]     │
└───────────────────────────┬─────────────────────────────────────────┘
                            │ raw documents + metadata
                            ▼
┌─────────────────────────────────────────────────────────────────────┐
│                       PROCESSING PIPELINE                           │
│                                                                     │
│  Parser (email/PDF) → Chunker → Embedder → Metadata tagger         │
│                                   │                                 │
│                         (company, date, doc_type, importance)       │
└───────────────────────────┬─────────────────────────────────────────┘
                            │ chunks + embeddings
                            ▼
┌─────────────────────────────────────────────────────────────────────┐
│                         VECTOR STORE                                │
│                  (rekomendacja: Qdrant — self-hosted)               │
│                                                                     │
│  Kolekcje: documents (chunks), market_data (time-series snapshots)  │
└───────────────────────────┬─────────────────────────────────────────┘
                            │ similarity search
                            ▼
┌─────────────────────────────────────────────────────────────────────┐
│                          RAG ENGINE                                 │
│                                                                     │
│  Query Builder  →  Retriever  →  Context Assembler  →  Prompt      │
│        ▲                                                            │
│  [User Profile]  (risk_profile, investment_horizon, companies)      │
└───────────────────────────┬─────────────────────────────────────────┘
                            │ prompt + context
                            ▼
┌─────────────────────────────────────────────────────────────────────┐
│                     LLM (Llama — Cyfronet AGH)                      │
│                                                                     │
│  Input: profil usera + retrieved chunks + pytanie                   │
│  Output: sentiment (pos/neg/neu) + uzasadnienie + cytaty źródłowe   │
└───────────────────────────┬─────────────────────────────────────────┘
                            │ structured response
                            ▼
┌─────────────────────────────────────────────────────────────────────┐
│                     APPLICATION LAYER (FastAPI)                     │
│                                                                     │
│  CLI tool  /  minimal web UI (Bootstrap + AI-generated)             │
│  Stateful: User profile przechowywany między sesjami                │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 4. Kluczowe encje / modele danych

### `UserProfile`
```
user_id          : UUID
name             : str
risk_tolerance   : enum(low, medium, high)
investment_horizon: enum(short_term, long_term)
investment_style : enum(passive, active)
watchlist        : list[ticker]  # np. ["NVDA", "MSFT"]
created_at       : datetime
```

### `Document`
```
doc_id           : UUID
source           : enum(email, pdf, api, historical)
company_ticker   : str
doc_type         : enum(earnings_report, conference_transcript, macro_data)
document_date    : date           # oryginalna data dokumentu (ważne dla backtestingu)
ingested_at      : datetime
raw_content      : text
importance_score : float (0-1)    # używany do filtrowania przy retrieval
```

### `DocumentChunk`
```
chunk_id         : UUID
doc_id           : UUID (FK -> Document)
content          : text
embedding        : vector[1536]   # lub inny wymiar zależny od modelu
metadata         : JSON           # company, date, doc_type, chunk_index
```

### `SentimentResult`
```
result_id        : UUID
user_id          : UUID (FK -> UserProfile)
query            : text
sentiment        : enum(positive, negative, neutral)
confidence       : float
reasoning        : text           # wyjaśnienie LLM
source_chunks    : list[chunk_id] # cytaty źródłowe
created_at       : datetime
```

---

## 5. Podział odpowiedzialności

| Obszar | Lead (Ty) | Kolega |
|--------|-----------|--------|
| DevOps: Docker, CI/CD, pre-commit hooks | ✓ | |
| Email ingestion (IMAP + parsowanie) | ✓ | |
| RAG pipeline (chunking, embedding, retrieval) | ✓ | |
| Vector store setup (Qdrant) | ✓ | |
| Llama integration (Cyfronet API) | ✓ | |
| FastAPI endpoints | | ✓ |
| User profile CRUD | | ✓ |
| Public API integration (Yahoo Finance) | | ✓ |
| PDF processing (upload + parsing) | | ✓ |
| CLI / basic UI | | ✓ |
| Historical data batch import | TBD | TBD |

---

## 6. Rekomendacje technologiczne

| Komponent | Rekomendacja | Uzasadnienie |
|-----------|-------------|--------------|
| Vector DB | **Qdrant** | Self-hosted, Docker-friendly, prosta konfiguracja, dobry Python SDK |
| Embedding model | `nomic-embed-text` lub `bge-m3` | Lekkie, można self-host razem z Llamą |
| Email parsing | `imaplib` + `email` stdlib | Zero deps, wystarczy |
| PDF parsing | `pdfplumber` lub `pymupdf` | Lepsza ekstrakcja tabel i layoutu niż `pypdf2` |
| RAG framework | **LangChain** lub **LlamaIndex** | LangChain bardziej elastyczny; LlamaIndex lepiej integruje się z pipeline'ami dokumentowymi |
| LLM API | OpenAI-compatible endpoint (vLLM na Cyfronet) | Cyfronet typowo wystawia vLLM z OpenAI-compatible API |
| DB (relacyjna) | **SQLite** (dev) / PostgreSQL (prod) | User profiles, SentimentResults — nie potrzeba dużego setup |

---

## 7. Otwarte decyzje do podjęcia

- [ ] **Stateful vs Stateless UI**: czy user profile żyje w bazie (stateful) czy jest przekazywany jako config przy każdym zapytaniu (stateless)? Rekomendacja: stateful z SQLite — prostsze UX
- [ ] **RAG framework**: LangChain vs LlamaIndex vs własny pipeline — warto zrobić spike (kilka dni)
- [ ] **Importance score**: jak obliczać wagę dokumentu? Ręcznie (np. "earnings > news"), model klasyfikacyjny, czy LLM?
- [ ] **Backtesting interface**: jak user definiuje "okno czasowe" przy historycznym testowaniu?
- [ ] **Llama endpoint na Cyfronet**: potwierdzić format API (OpenAI-compatible?)

---

## 8. Następne kroki (sugestia)

1. Potwierdzić dostęp do Cyfronet + format API Llamy
2. Spike: prosta RAG pipeline (Qdrant + LangChain + Llama) na jednym dokumencie PDF
3. Setup środowiska (Docker Compose: FastAPI + Qdrant + PostgreSQL)
4. Implementacja email ingestion
5. Iteracja nad prompt engineeringiem (jak przekazywać profil usera do LLM)


## 9. Materialy do przeczytania 

---
Data Processing / ML Pipelines (ingestion, chunking, tagging)

Artykuły:
- https://www.pinecone.io/learn/chunking-strategies/ — Pinecone blog, bardzo praktyczny przegląd metod chunkowania (fixed-size, semantic, recursive)
- https://unstructured.io/blog/document-parsing-for-rag — Unstructured.io, skupia się na PDF/HTML/email
- https://docs.llamaindex.ai/en/stable/optimizing/production_rag/ — LlamaIndex docs, omawia cały pipeline od ingestion do retrieval

YouTube:
- https://www.youtube.com/watch?v=2o2oD_kWZus — oficjalny kanał LlamaIndex
- https://www.youtube.com/watch?v=zduSFxRajkE — nie bezpośrednio o pipelinie, ale daje fundamenty pod rozumienie tokenizacji / embeddingów

---
RAG

Artykuły:
- https://arxiv.org/abs/2005.11401 — oryginalny paper, warto przejrzeć przynajmniej intro i sekcję metody
- https://towardsdatascience.com/advanced-rag-techniques-an-illustrated-overview-04d193d8fec6 — Towards Data Science, ilustrowany przegląd: HyDE, re-ranking, parent-child chunking itd.
- https://github.com/langchain-ai/rag-from-scratch — repozytorium z notebookami, każdy notebook to inny aspekt RAG

YouTube:
- https://www.youtube.com/playlist?list=PLfaIDFEXuae2LXbO1_PKyVJiQ23ZztA0x — seria ~15 krótkich filmów (10-15 min każdy), bardzo konkretna
- https://www.youtube.com/watch?v=sVcwVQRHIc8 — konferencja, praktyczne case studies

---
Graph Databases

Artykuły:
- https://neo4j.com/developer/graph-database/ — oficjalny intro, dobrze wyjaśnia model property graph
- https://microsoft.github.io/graphrag/ — Microsoft GraphRAG, relevantne jeśli planujesz relacje między spółkami/dokumentami
- https://neo4j.com/developer/graph-db-vs-rdbms/ — porównanie z relacyjnymi, pomaga zdecydować czy w ogóle warto

YouTube:
- https://www.youtube.com/watch?v=GekQqFZm7mA — świetne intro koncepcyjne, 45 min
- https://www.youtube.com/watch?v=r09tJfON6kE — bezpośrednio łączy grafy z RAG

---
ML Workflows / Orchestration

Artykuły:
- https://dagster.io/blog/dagster-airflow — porównanie narzędzi do orquestracji (pod kątem ML pipelines)
- https://landing.ai/data-centric-ai/ — Andrew Ng, krótki manifesto, zmienia perspektywę

YouTube:
- https://www.youtube.com/watch?v=pH5M3Q0xoEM — UC Berkeley kurs, wykłady z systemów ML
- https://www.youtube.com/watch?v=c_AUuTuPA5k — na podstawie jej książki, polecam samą książkę jeśli chcesz więcej

---
Priorytet dla Twojego projektu: zacznij od RAG from scratch playlist (LangChain) + chunking strategies (Pinecone) — to bezpośrednio pod Twój stack (Qdrant + LangChain/LlamaIndex). Grafy na razie możesz pominąć — Twoja architektura ich nie używa.