# Reviewed Cleaned-Corpus Publication

**Status:** Accepted (author instruction, 2026-10-18)

## Separate selection from materialization

The immutable `thesis-v2-current-cache` materialization contains real
`source-cleaning-v1` output. Updating the application cleaner cannot repair it:
ingestion deliberately preserves manifest-provided cleaned text.

Retain both that directory and the approved selection
`data/research_selection/thesis-v2-current-cache.json` without modification.
Publish the new schema-2 materialization as
**`thesis-v2-current-cache-sec-form-aware-v2`** and make it the explicit active
runtime/evaluation version. Selection and materialization have separate
constants; changing cleaning must not regenerate selection or derive a new split.

The 363 records, raw bytes, source identifiers/types, publication/retrieval dates,
URLs, content groups, canonical flags, and downloaded/reviewed sector evidence
are preserved. The window remains **2021-08-27–2026-08-27**, development ends
**2024-08-27**, and held-out publications start **2024-08-28**.

## Offline publication contract

`scripts.acquire_corpus` defaults to the cleaning-revision workflow:

- Verify the complete predecessor and the frozen selection, including original
  sources and selection input-manifest checksums.
- Re-extract all 243 SEC records with their known forms using the implementation
  pinned by the final `sec-v2-round5` / `sec-v2-edge-round4` development reviews.
  Compare complete output bytes against reviewed artifacts wherever they overlap.
- Copy all 120 transcript cleaned artifacts and their parser provenance unchanged.
- Embed hash-pinned selection, source manifests, predecessor manifest and full
  file inventory, review indexes and separate findings. Preserve the original
  review-status flags and describe their bounded development scope truthfully.
- Record implementation fingerprints and a deterministic `publication.json`.
  Publish atomically into a fresh directory; reruns verify all expected artifact
  bytes. Changed inputs or corruption cannot overwrite a materialization.

The runtime verifies embedded lineage artifacts offline alongside raw/cleaned
records and sector evidence. It loads only the explicitly active materialization
as final evidence; the operational broad-cache union remains available.

## Persisted cleaning lineage

The initial version-prefixed runtime identity below is refined by
[decision 0017](0017-operational-history-and-source-derivations.md): normalized
derivations are keyed by stable source revision, cleaning version and cleaned
hash; manifest memberships are separate. Existing persisted IDs are retained
and reused through aliases rather than rewritten.

Original-byte revision IDs remain stable in manifest records. Runtime document
IDs for the new materialization are prefixed with its version; chunk IDs inherit
that identity. Migration `0010_document_cleaning_versions.sql` includes
`manifest_version` in source-revision uniqueness. Previously stored v1 documents,
chunks, and results remain addressable rather than being overwritten or mixed
with the new cleaned text. Existing v1 results are not retroactively recomputed.

## Publication evidence

External directory: `data/corpora/thesis-v2-current-cache-sec-form-aware-v2/`.

- 243 SEC records re-cleaned; **242 cleaned hashes changed**, one remained equal.
- 120 transcript artifacts preserved byte-for-byte.
- 24 unique reviewed overlapping filings matched exactly.
- All 741 predecessor files verified unchanged, with their inventory embedded.
- Frozen selection SHA-256:
  `ea7af2e5025fcce8ebe8b103e35cceea3c13ab7742dc57d16b38e23d85fd4146`.
- New manifest SHA-256:
  `e79cd741a308bbb5aebea4da845e05a8df0c6acaa26e4a206073644935f6a16b`.
- AT&T `0000732717-22-000038` cleaned SHA-256:
  `8fe4ec4d504f58ee9cc509debb5a00996ff22935b018e1b8efc66bc2da3dd605`.

This publication does not expand the semantic review beyond its documented 78
development filings. Source/image/table-geometry limits remain in
`docs/SEC_EXTRACTION_REVIEW.md`. FEAT-015 remains `in_progress`; market-data
manifest and forward-horizon coverage are separate work.

Verification completed: standard suite **254 passed / 10 optional integrations
skipped**, with **6 real-cache** and **2 research-history** integration tests
passed separately; PostgreSQL/API tests ran against an isolated temporary
database. The real publication rerun verified idempotence. Formatting, imports,
lint, type checking, compilation, package build, dependency audit and document /
feature-registry checks passed. Qdrant integration was not configured.
