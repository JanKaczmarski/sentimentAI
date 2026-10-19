# Frozen Market Snapshot And Evaluation Coverage

**Status:** Accepted (author-approved implementation plan, 2026-10-18)

## Reuse the verified source publication

The existing `thesis-v2-current-cache-sec-form-aware-v2` publication passes its
complete offline verifier and reconciles exactly to the frozen selection. It is
reused, not republished. All **363** source references, original-byte hashes,
metadata, membership, and chronological boundaries remain unchanged. Both corpus
versions and the frozen selection remain intact.

## Market acquisition contract

Reuse the Nasdaq historical JSON provider and existing provider-neutral CSV v1
reader. The snapshot is **`nasdaq_2026_10_18_research_v2`**, requested from
**2021-08-27 through 2026-10-16**, the last completed trading session before this
Sunday acquisition. This boundary is independent of the frozen source cutoff
**2026-08-27**. No missing future price can move the source cutoff or split.

- Stocks: **META, CRM, V, DIS, WHR, T**.
- Sector ETFs: **XLC, XLK, XLF, XLY**.
- Fallback and S&P 500 sensitivity: **SPY**.
- Return basis: the provider-reported **`Close`**, as consumed by the existing
  reader and decision 0006's formula. No dividend-adjusted total-return claim or
  silent adjustment/substitution is made.
- Retain the actual response bytes as `raw/<SYMBOL>.json`; record their SHA-256,
  exact request URL, requested dates, UTC retrieval timestamp, asset class,
  actual coverage, CSV SHA-256, and row count in `market_prices.json`.
- Validate returned identity when supplied, row count/truncation, dates, prices,
  and duplicates. Replay saved responses to reproduce every CSV and the manifest.
- Publish atomically into a fresh directory. Identical reruns verify offline;
  changed requests, corruption, symlinks, and unrecorded files fail.

All eleven acquired series contain **1,290 rows**, covering **2021-08-27 through
2026-10-16**. Their observed date sets agree; no independent exchange-calendar
certification is implied. Existing development snapshots remain unchanged.

## Versioned evaluation artifact contract

Publish **`thesis-v2-current-cache-sec-form-aware-v2-market-v1`** under
`data/evaluation/` in `sentimentAI-data`:

- `manifest.json`: exact source/selection/market references, hashes, split,
  benchmark routing, price coverage, and pre-registered alignment/exclusion rules.
- `reconciliation.json`: every selected source revision and old/new cleaned
  hashes, membership and predecessor-preservation evidence.
- `coverage.json`: all source/horizon outcomes and per-company summaries,
  development/held-out counts, calendar differences and daily boundary intervals.
- `implementation/*.py`: hash-pinned creation implementations. Historical
  fingerprints remain verifiable after runtime code evolves.

The manifest pins **1,917 input files** and **8 output artifacts**, including
complete corrected/predecessor/market inventories, original selected sources,
source manifests, sector downloads/review, extraction review indexes/findings,
and creation implementations. The manifest's own digest is recorded below,
rather than introducing a self-referential hash.

`load_evaluation_scope()` verifies all pinned files/inventories offline before
returning the existing `EvaluationScope`. The freeze command additionally
reconciles the publication, replays raw price responses and recomputes the saved
coverage. It refuses changed inputs or changed derivations instead of overwriting.

Benchmark routing comes from the hash-pinned corpus sector evidence: META/DIS/T
→ XLC; CRM → XLK; V → XLF; WHR → XLY. Sector endpoints must match the exact subject
entry/exit dates. Missing sector endpoints trigger SPY fallback; missing SPY
endpoints exclude the observation because SPY sensitivity is required.

## Coverage and complete boundaries

The shared provider-neutral outcome resolver implements decision 0006:
entry = first subject trading day **strictly after** publication/as-of;
exit = entry index **plus h**; return = `Close[t+h] / Close[t] - 1`.
Prediction evaluation and acquisition coverage use this same implementation.

Retain **1,815 source/horizon entries**, including **735 held-out entries**.
This is source-publication availability, not prediction generation, an evaluation
sampling schedule, deduplicated signal counts, or a thesis performance result.
Each unavailable entry retains its source ID, publication date, horizon, known
entry date, unavailable exit/return fields, and explicit reason. No future
endpoint or price is invented. Daily boundary intervals preserve interior gaps
as well as the unavailable tail.

| Horizon | Complete / 363 | Unavailable | Complete held-out / 147 | Latest price-supported as-of | Latest entry |
|---|---:|---:|---:|---|---|
| 1 | 363 | 0 | 147 | 2026-10-14 | 2026-10-15 |
| 5 | 363 | 0 | 147 | 2026-10-08 | 2026-10-09 |
| 20 | 363 | 0 | 147 | 2026-09-17 | 2026-09-18 |
| 60 | 348 | 15 | 132 | 2026-07-22 | 2026-07-23 |
| 252 | 291 | 72 | 75 | 2025-10-14 | 2025-10-15 |

These latest price-supported boundaries agree across the six companies and use
the final observed exit **2026-10-16**. They do not expand the text scope; some
short-horizon boundaries are later than its cutoff. For each company/horizon,
the last complete **included publication** is recorded separately in the summary.
All **87** incomplete entries are held-out `subject_horizon_unavailable` cases;
there are no SPY exclusions or observed sector fallbacks in this snapshot.

## Artifact identities

- Corrected corpus manifest:
  `e79cd741a308bbb5aebea4da845e05a8df0c6acaa26e4a206073644935f6a16b`
- Frozen selection:
  `ea7af2e5025fcce8ebe8b103e35cceea3c13ab7742dc57d16b38e23d85fd4146`
- Market manifest:
  `188658a7cfeb9f98afb959b04a3f8402f24051effb2ac8e9ab06d514d92f4f60`
- Evaluation manifest:
  `20b1b7ace03ad6b3e3102436fc6378f0d89f99ebffa229c956edf84994aab32c`
- Coverage:
  `fc34cbcf69961ed15553d1d9c219ac2b665256636656094e1e5be58f144b4c69`
- Reconciliation:
  `80f40c49211f0617397bf5ac006eafa52ee28eea0c91cae03b59174907a4ce3f`

## Evidence and lifecycle

TDD observed failing imports for the new replay verifier, application coverage
use case, and manifest freezer before implementation. Focused unit/contract tests
then passed. Real-cache integration independently checks every outcome against
saved price endpoints, all 363 memberships, all five horizons, exclusions and
strict-after boundaries with provider requests forbidden.

The standard suite with an isolated temporary local PostgreSQL instance passed
**296 tests**; **13 real-cache tests passed separately**. Qdrant remains the only
unconfigured optional infrastructure check. The temporary PostgreSQL server was
stopped after verification; application databases were not changed.

Formatting, import ordering, lint, mypy, compilation, package build, dependency
audit, required-document/feature validation, lock consistency and diff checks
all passed. The first combined cached-data invocation timed out after 120
seconds; the broader cache/history checks passed with a 600-second timeout.

FEAT-015 is locally `implemented`. Integration/review is separate; FEAT-016
still owns actual prediction-evaluation execution and waits for its dependency
to be integrated. No commit, push, pull request or merge was requested.
