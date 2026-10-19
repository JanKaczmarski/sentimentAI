# FEAT-015 delivery evidence

## Reproducible data revision

`research-data.lock.json` pins `JanKaczmarski/sentimentAI-data` commit
`dcfab90df2178f551ab0f7824a4804f179094927`:
**data: freeze reviewed six-company corpus and market coverage**.

This commit retains the historical SEC/IR inputs, both immutable corpus versions,
the frozen selection, downloaded/reviewed sectors, bounded extraction reviews,
the eleven-symbol market snapshot, and the evaluation input/coverage bundle.
Original source bytes and immutable publication directories were not rewritten.
Older top-level Kaggle CSV removal is the existing, documented replacement with
versioned price snapshots. Unrelated ADBE/AMD/AMZN raw downloads remain local.

The pinned evaluation manifest is
`data/evaluation/thesis-v2-current-cache-sec-form-aware-v2-market-v1/manifest.json`,
SHA-256 `20b1b7ace03ad6b3e3102436fc6378f0d89f99ebffa229c956edf84994aab32c`.
It pins all 1,917 inputs and eight output artifacts. The revision-closure
integration test verifies that every referenced file exists in the Git commit,
not only in an untracked local cache.

**Publication blocker:** the commit currently exists locally; pushing to the
data remote is denied to the authenticated `Jakub-Woszczek` account. The remote
must receive this exact revision before another checkout can reproduce it.
This is not recorded as a successful data push.

## Acceptance evidence

| Criterion | Evidence |
|---|---|
| AC-1: auditable source/cleaned records | Real-cache source reconciliation and reviewed AT&T regression in `tests/integration/test_cached_sources.py`; immutable publication tests |
| AC-2: supported source contracts | `tests/contract/ports/test_cached_corpus.py` covers 10-K, 10-Q, Item 2.02 8-K, IR releases, full transcripts, exclusive publication filters, revision deduplication, and operational/evaluation scope |
| AC-3: idempotence and history | CLI intact/missing/tampered/changed-input regressions; publication/price reruns; immutable derivation tests and populated PostgreSQL upgrade/transition tests |
| AC-4: offline validation and deterministic access | Offline contract tests, original-byte SEC/IR integrity checks, broad-history ordering/scope tests, and real external-cache integration |
| AC-5: eleven-symbol market snapshot | Raw-response replay, CSV/provider provenance, snapshot corruption checks, and real cached-market integration |
| AC-6: frozen evaluation inputs and coverage | Exact source reconciliation, independently checked endpoints, benchmark-gap/fallback and strict horizon-boundary tests, and committed artifact closure |

## Local verification

Run from the application repository with the external cache configured:

```bash
SENTIMENT_DATA_ROOT=/absolute/path/to/sentimentAI-data uv run pytest -q -ra
```

Result on 2026-10-19 before adding the revision-closure test: **311 passed,
9 skipped**. All 13 real-cache cases executed. The skipped cases are eight
PostgreSQL cases and one Qdrant case; they are not local infrastructure evidence.
The infrastructure CI workflow supplies both services and runs those cases.

Additional regressions cover a broad-cache PDF imported before frozen manifest
membership, replay without duplicate derivations, original-byte identity,
independent chunk configurations, and immutable prior cleaned/chunk evidence.
They run against an isolated PostgreSQL schema through the existing CI workflow.

Formatting, import ordering, Ruff, mypy, compilation, package build, lockfile,
document/registry validation and application diff checks passed. `pip-audit`
found no known dependency vulnerabilities; the local unpublished application
package itself is not an auditable PyPI dependency.

This delivery increment adds verification coverage rather than new production
behavior, so the new tests validate existing contracts; no artificial failing
implementation test is claimed. Earlier implementation TDD remains recorded in
decisions 0016–0018. The bounded 78-filing extraction review is retained without
expanding its semantic or visual-fidelity claims.

## Remote verification and lifecycle

Application CI and pull-request results are recorded after publication. Until
remote checks pass, infrastructure verification is pending. FEAT-015 is locally
implemented and is not complete until reviewed integration into `develop`.
Neither a successful local test suite nor a local data commit proves publication
or integration.
