# Getting Started

## Cel Dokumentu

Ten dokument jest krótkim handoffem dla osoby, która rozwija projekt przez
najbliższe tygodnie. Opisuje sposób pracy, źródła prawdy, kolejność realizacji
feature'ów i obowiązkowe zasady jakości.

Szczegółowe acceptance criteria i statusy znajdują się zawsze w
`FEATURES.yaml`. Ten plik tłumaczy, jak z tego rejestru korzystać.

## Cel Projektu

Projekt buduje thesis-focused system do analizy sentymentu informacji o spółkach.
System ma:

- pobierać i normalizować dokumenty historyczne;
- dzielić dokumenty na audytowalne chunki;
- obliczać niezależny od inwestora sentyment i importance;
- agregować sygnały do snapshotów 30, 90 i 365 dni;
- stosować deterministyczną Investment Thesis;
- zwracać wynik razem z evidence i pełną proweniencją eksperymentu;
- oceniać sygnały względem przyszłych danych rynkowych;
- zachowywać możliwość odtworzenia każdego wyniku.

Najważniejsza zasada badawcza: najpierw powstaje wspólny, niezależny od
inwestora sentiment, a dopiero później deterministyczna personalizacja przez
Investment Thesis. Nie wykonujemy osobnego calla LLM dla każdego inwestora.

## Szybki Start

Wymagane narzędzia:

- Python 3.13 zgodny z `.python-version`;
- `uv`;
- Docker i Docker Compose;
- `make`.

Podstawowe komendy:

```bash
uv sync --locked
make test
make check
```

Opcjonalny lokalny stack infrastruktury:

```bash
cp .env.example .env
make deploy
make status
make logs
make down
```

`make deploy` uruchamia lokalny Docker Compose w tle. Nie jest to deployment
produkcyjny.

Najważniejsze endpointy lokalne:

- API health: `http://localhost:8000/health`;
- local testing UI: `http://localhost:8000/ui/`;
- Prometheus: `http://localhost:9090`;
- Grafana: `http://localhost:3000`.

## Architektura

Projekt jest modularnym monolitem z kierunkiem zależności:

```text
domain -> application use cases -> ports -> adapters -> bootstrap
```

Odpowiedzialności katalogów:

- `src/sentiment_system/domain/`: czyste encje i reguły domenowe;
- `src/sentiment_system/application/ports/`: interfejsy granic wymiennych;
- `src/sentiment_system/application/use_cases/`: orkiestracja procesów;
- `src/sentiment_system/adapters/`: FastAPI, persistence, LLM, embeddings,
  sources, vector store, market data i observability;
- `src/sentiment_system/bootstrap/`: composition root i konfiguracja runtime;
- `tests/unit/`: testy domeny i use case'ów;
- `tests/contract/`: testy kontraktów adapterów;
- `tests/integration/`: testy infrastruktury, API i cross-boundary workflows;
- `poc/`: stara implementacja tylko do porównań i referencji.

Kod domenowy i application nie może importować FastAPI, PostgreSQL, Qdrant,
Docker API ani SDK providerów.

## Źródła Prawdy

| Plik | Rola |
|---|---|
| `FEATURES.yaml` | Jedyny autorytatywny backlog, statusy, zależności i AC |
| `DEVELOPMENT_RULES.md` | Reguły architektoniczne, badawcze i jakościowe |
| `IMPLEMENTATION_WORKFLOW.md` | Szczegółowy lifecycle feature'a i merge gates |
| `.opencode/skills/implement-next-feature/SKILL.md` | Instrukcja dla AI wykonującego feature end-to-end |
| `ARCHITECTURE.md` | Docelowa architektura systemu |
| `THESIS_DECISIONS.md` | Ustalenia metodologiczne i otwarte decyzje badawcze |
| `AGENTS.md` | Reguły repozytorium i komendy developerskie |
| `Makefile` | Skróty do testów, quality gates i lokalnego Compose |

Przed rozpoczęciem feature'a należy przeczytać `AGENTS.md`,
`DEVELOPMENT_RULES.md`, `IMPLEMENTATION_WORKFLOW.md`, `ARCHITECTURE.md`,
`THESIS_DECISIONS.md`, `FEATURES.yaml` oraz wskazane decyzje dodatkowe.

## Jak Używać Skilla

Głównym skillem implementacyjnym jest:

```text
implement-next-feature
```

W OpenCode można go wywołać jako `/implement-next-feature`. Skill wybiera
feature wyłącznie z `FEATURES.yaml`; nie wolno wymyślać nowego zakresu na
podstawie POC-a, komentarzy albo luźnych pomysłów.

Przed wyborem feature'a uruchom dokładnie w tej kolejności:

```bash
uv run python -m scripts.check_required_docs
uv run python -m scripts.validate_features
uv run python -m scripts.check_feature_status
```

Jeżeli nie ma feature'a w `in_progress`, `implemented` ani `in_review`, sprawdź
możliwe promocje:

```bash
uv run python -m scripts.reconcile_feature_readiness
uv run python -m scripts.reconcile_feature_readiness --apply
uv run python -m scripts.validate_features
uv run python -m scripts.check_feature_status
```

Nie uruchamiaj reconciliatora, kiedy inny feature jest aktywny albo czeka na
review. Wtedy należy najpierw wznowić lub domknąć istniejący feature.

## Lifecycle Feature'a

Dozwolony przepływ:

```text
queued -> ready -> in_progress -> implemented -> in_review -> complete
```

Znaczenie statusów:

- `queued`: feature zatwierdzony, ale czeka na zależności;
- `ready`: można go wybrać do implementacji;
- `in_progress`: jedyny aktualnie implementowany feature;
- `implemented`: kod i lokalna weryfikacja są gotowe, PR nie jest jeszcze
  domknięty;
- `in_review`: istnieje PR albo trwa wymagane remote CI;
- `complete`: feature jest zintegrowany z `main` i ma evidence dla każdego AC.

Reguły:

- w danym momencie pracujemy nad jednym feature'em;
- `in_progress` zawsze wznawiamy, zamiast wybierać coś nowego;
- nie omijamy zależności;
- nie oznaczamy feature'a jako `complete` na niezmergowanym branchu;
- po merge sprawdzamy, czy `complete` jest faktycznie na `main`;
- dopiero wtedy uruchamiamy reconcile i wybieramy następny feature.

## TDD I Implementacja

Dla feature'a zmieniającego zachowanie:

1. Zmień status `ready` na `in_progress` przed kodem produkcyjnym.
2. Napisz mały, skupiony test opisujący wymagane zachowanie.
3. Uruchom test i zachowaj dowód, że początkowo nie przechodzi.
4. Zaimplementuj najmniejszą poprawną zmianę.
5. Dodaj testy kontraktowe dla nowych adapterów.
6. Dodaj testy integracyjne, jeśli zmiana dotyczy infrastruktury, API albo
   kilku granic systemu.
7. Dodaj evidence do każdego `AC-*` w `FEATURES.yaml`.

Nie dodajemy abstrakcji "na przyszłość". Port powstaje tylko dla realnej,
wymiennej granicy, takiej jak persistence, LLM, embeddings, document source,
vector store albo market data.

## Quality Gates

Szybkie komendy:

```bash
make test
make check
```

Pełny standard obejmuje:

```bash
uv run black --check src tests scripts
uv run isort --check-only src tests scripts
uv run ruff check src tests scripts
uv run mypy
uv run pytest
uv run python -m compileall -q src tests scripts
uv build
uv run pip-audit
docker compose config --quiet
uv run python -m scripts.check_required_docs
uv run python -m scripts.validate_features
uv lock --check
git diff --check
```

Jeżeli check jest niedostępny albo nie przechodzi, feature nie może być
przedstawiony jako ukończony.

## PR I Merge

Po lokalnej weryfikacji:

1. Zmień feature na `implemented` i dodaj evidence.
2. Utwórz focused PR bez obcych zmian.
3. Po potwierdzeniu istnienia PR zmień status na `in_review` w tym PR.
4. Poczekaj na CI dla dokładnego commita PR-a.
5. W finalnym commicie PR-a ustaw status `complete`.
6. Uruchom CI ponownie dla finalnego commita.
7. Merge wykonaj dopiero po przejściu finalnego CI.
8. Na zaktualizowanym `main` potwierdź status `complete`.

Nie wolno omijać branch protection, robić force-push, wyłączać CI ani merge'ować
przy brakujących lub nieudanych checkach.

## Backlog Produktu

Poniższa mapa pokazuje pełny zakres thesisowego produktu. Szczegółowe AC,
zależności i aktualny status są w `FEATURES.yaml`.

| Etap | Feature'y | Zakres |
|---|---|---|
| Fundament domeny | `FEAT-001` do `FEAT-003` | Encje, provenance, porty i fake'i |
| Decyzje badawcze | `FEAT-004` do `FEAT-006` | Konfiguracja eksperymentu, reguły, corpus, API i storage contract |
| Ingest | `FEAT-007`, `FEAT-015` | Fixture'y, SEC i investor relations |
| Persistence | `FEAT-008` | PostgreSQL i audytowalne rekordy |
| API strategii | `FEAT-009`, `FEAT-014` | Konta, Investment Thesis, predykcje, historia i ingestion endpoint |
| RAG | `FEAT-010`, `FEAT-011` | Lokalne embeddings, Qdrant i investor-independent scoring |
| Sentiment | `FEAT-012`, `FEAT-013` | Agregacja snapshotów i deterministyczna personalizacja |
| Ewaluacja | `FEAT-016` | Leakage-safe market outcomes i baselines |
| Runtime | `FEAT-017` | Batch, scheduler, run state, Prometheus i Grafana |

Kolejność nie jest ustalana ręcznie. Po każdym merge uruchom:

```bash
uv run python -m scripts.reconcile_feature_readiness --apply
uv run python -m scripts.validate_features
uv run python -m scripts.check_feature_status
```

## Stan Na Moment Przekazania

- `FEAT-001`: `complete` na `main`;
- `FEAT-002`: `complete` na `main`;
- `FEAT-003`: implementacja znajduje się w branchu `feat/typed-ports-fakes`,
  commit `e3bb822`, status `implemented` do czasu PR-a i merge'a;
- `FEAT-004`, `FEAT-005`, `FEAT-006`: `blocked`, ponieważ wymagają jawnych
  decyzji autora/promotora;
- `FEAT-007` do `FEAT-017`: zatwierdzone feature'y oczekujące na zależności.

Po merge'u `FEAT-003` nie należy automatycznie implementować `FEAT-007+`, jeśli
`FEAT-004`, `FEAT-005` albo `FEAT-006` nadal są zablokowane. Najpierw trzeba
uzyskać decyzję i zapisać ją w odpowiednim dokumencie.

## Otwarte Decyzje

Najważniejsze otwarte decyzje są w `THESIS_DECISIONS.md`:

- dokładny chronological development/test split;
- recency decay i początkowe współczynniki agregacji;
- włączenie albo wyłączenie horyzontu 252 dni;
- mechanizm cache'owania SEC, IR i Yahoo Finance;
- wybór opcjonalnego lokalnego backendu Llama;
- finalne API i schemat bazy danych.

Nie wolno zamieniać tych otwartych punktów w niejawne założenia w kodzie.
Jeśli feature wymaga takiej decyzji, pozostaw go zablokowanego i przygotuj
propozycję do akceptacji.

## Zasady Badawcze I Bezpieczeństwa

- Zachowuj source ID, daty publikacji, raw content i cleaned content osobno.
- Nie dopuszczaj look-ahead biasu w ewaluacji.
- Używaj realnych lokalnych embeddings do wyników thesisowych; mocki są tylko
  do testów.
- Przechowuj provenance wejścia, konfiguracji, modelu, promptu, odpowiedzi,
  outputu, parametrów thesis i run ID.
- Nie zapisuj API keys, tokenów, haseł ani danych wrażliwych.
- Nie loguj promptów, raw dokumentów ani raw odpowiedzi LLM.
- `poc/` traktuj jako read-only reference.

## Logs I Metrics

Kod domenowy nie powinien logować ani importować Prometheusa. Logowanie i
metryki powinny być dodawane na granicach application, adapterów i bootstrapu.

Docelowo `FEAT-017` powinien obejmować:

- structured logs z `run_id`, request ID, komponentem, statusem i czasem;
- metryki batch duration, documents/chunks processed i exclusions;
- metryki LLM calls, latency, errors i token usage;
- metryki retrieval, API i evaluation;
- provisioned dashboards w Grafanie z Prometheusem jako datasource.

Nie używaj `run_id`, user ID ani pełnej treści dokumentu jako labeli Prometheus,
ponieważ powodowałoby to wysoką cardinality albo wyciek danych.

## Checklist Przed Przekazaniem Feature'a

- Czy feature był wybrany z `FEATURES.yaml`?
- Czy zależności są `complete`?
- Czy status został zmieniony przed rozpoczęciem implementacji?
- Czy istnieje failing-test evidence?
- Czy każde `AC-*` ma completion evidence?
- Czy `make check` przechodzi?
- Czy diff jest ograniczony do zakresu feature'a?
- Czy nie ma sekretów ani niepublicznych danych?
- Czy status i PR odpowiadają rzeczywistemu stanowi remote?

## Gdzie Szukać Pomocy

Kiedy wymaganie nie jest jasne:

1. Sprawdź `FEATURES.yaml` i jego acceptance criteria.
2. Sprawdź `ARCHITECTURE.md` i `THESIS_DECISIONS.md`.
3. Sprawdź `IMPLEMENTATION_WORKFLOW.md`.
4. Uruchom `uv run python -m scripts.check_feature_status`.
5. Jeśli nadal brakuje decyzji, nie zgaduj. Oznacz blocker i zapytaj autora.
