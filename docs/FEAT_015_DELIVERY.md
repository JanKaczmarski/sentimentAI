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

**Published:** [the pinned data commit](https://github.com/JanKaczmarski/sentimentAI-data/commit/dcfab90df2178f551ab0f7824a4804f179094927)
was pushed to `main` on 2026-10-19. `git ls-remote --heads origin main`
confirmed the exact pinned revision. The initial permission denial was resolved
after the author granted write access; the data publication blocker is closed.

To reproduce in a separate workspace:

```bash
git clone https://github.com/JanKaczmarski/sentimentAI-data.git
git -C sentimentAI-data checkout dcfab90df2178f551ab0f7824a4804f179094927
```

Set `SENTIMENT_DATA_ROOT` to that checkout and run the verifier/tests documented
in `FINAL_CORPUS_ACQUISITION.md`.

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

Pull request: <https://github.com/JanKaczmarski/sentimentAI/pull/54>, targeting
`develop`. [Infrastructure CI run 39207624266](https://github.com/JanKaczmarski/sentimentAI/actions/runs/39207624266)
passed for candidate `d0024f0910f9726b0e00116f456d767ca0c20d07`: **307 passed,
14 skipped**. All eight PostgreSQL cases (including five populated-upgrade/PDF
transition cases) and the Qdrant case executed successfully. The 14 skips are
external-cache cases because CI does not configure `SENTIMENT_DATA_ROOT`; those
cases passed locally, including the separately added revision-closure test.
Formatting, typing, compilation, build, dependency audit, Compose validation,
governance, lockfile and diff checks also passed remotely. Later documentation
commits must retain a successful check on their own exact PR head.

FEAT-015 is `in_review` and is not complete until reviewed integration.
Neither a successful local test suite nor a local data commit proves publication
or integration.

The additional pinned-revision integration test passed separately after the
full local suite. It confirms the exact Git commit contains the manifest and
all 1,925 referenced input/output artifacts; the manifest itself is also checked.

[CI run 39208004415](https://github.com/JanKaczmarski/sentimentAI/actions/runs/39208004415)
also passed on documentation candidate `2242c352c50a3ac9f5c4427136446945b876022a`.
The PR's current check rollup is the authority for the final head; integration
into `develop` still requires human approval.
