# Operational History And Source Derivations

**Status:** Accepted (author instruction, 2026-10-18)

This closes the acquisition/operational-ingestion/persistence gaps identified
while resuming FEAT-015. It refines decisions 0008, 0015 and 0016 without changing
the frozen selection, dates, sectors, or either immutable corpus.

## Verify acquisition inputs on every rerun

An existing directory is not sufficient evidence of successful acquisition.
Validate the requested selection bytes, pinned source manifests and sources,
explicit/default sector review and its download bundle, review indexes/findings,
and the complete published artifact set. Identical intact inputs succeed; changed
inputs, missing files, symlinks, corruption and unrecorded additions fail.

Verification of an existing publication uses its pinned historical evidence.
It does not re-clean the documents or require today's runtime-module hash to
equal the creation fingerprint. Creation of a fresh cleaning publication still
requires matching reviewed implementation fingerprints. Legacy `--ir-plan`
reruns validate the requested source selection, representations, sectors and
existing artifacts offline before any provider request.

## Operational SEC history

Normal `CachedCorpusDocumentSource.fetch_documents()` includes downloaded/existing
original 10-K, 10-Q and all 8-K records from
`data/sec/history/<TICKER>/manifest.json` for approved operational companies.
Pending/failed records and unsupported forms/amendments are not documents.
Downloaded/existing records with missing or corrupt artifacts fail loudly.

Use filing/publication dates, never fiscal `report_date`, for publication filters.
Verify original bytes and retain form/Item metadata. Item 2.02 earnings packages
use the reviewed form-aware extraction; non-earnings 8-Ks use their unique main
disclosure, with cleaning identity `sec-main-disclosure-v1`. They do not become
research evaluation members.

Deduplicate by `(company, source, source_id, original_byte_sha256)`. Explicit
precedence is frozen corpus, history, then legacy snapshot/curated cache.
Changed original-byte revisions remain distinct. Hashes and deterministic
tie-breakers make output independent of manifest ordering; conflicting history
metadata for one revision is an error. Evaluation access continues to use only
the active immutable manifest and its 363 approved records.

## Source identity and immutable derivations

`SourceArtifact` carries a verified original SHA-256, local path, and available
URL/retrieval/form metadata independently of evaluation provenance. This survives
normalization and persistence for broad-cache PDFs as well as SEC text. Extracted
text has its own hash and is never substituted for the original PDF hash.

A source revision is identified by company, source, source identifier and
original-byte hash. A cleaned derivation adds the cleaning/parser version and
actual cleaned-content hash. Membership in a different manifest does not create
a second identical derivation. Chunk IDs additionally include the processing
configuration; identical writes reuse stored evidence and conflicts fail.

Repository saves return canonical stored documents/chunks. Ingestion uses these
returned identities through indexing and scoring, so a reused historical ID
cannot leave new chunks pointing at an unpersisted alias. Manifest memberships
are recorded separately without replacing the original document's provenance.
Historical scores, snapshot evidence and prediction evidence remain unchanged.

## Populated database upgrade

Forward migration `0011_source_revisions_and_derivations.sql` adds source-revision,
derivation-alias and manifest-membership tables, preserves all document/chunk IDs,
and permits multiple chunk configurations per document/ordinal. Identical known
legacy derivations and chunks are reused instead of duplicated.

Migration 0009 previously copied extracted-text hashes into the original-byte
column. Migration 0011 preserves that previous value in
`legacy_source_raw_sha256` and restores original hashes from existing manifest
provenance where available. When original bytes cannot be established, the
original-byte hash and revision identity remain NULL and the cleaning version is
`legacy-unverified`. Text hashes, contents, IDs, timestamps and evidence remain.
The migration does not guess PDF identity from matching extracted text.

A subsequent verified cache replay creates an idempotent verified derivation for
such an unknown legacy record; it does not relabel the old PDF's unknown bytes.
Only current ingestion chunks are scored in the new run; aggregation selects
scores by run ID, so historical rows are not added as duplicate current evidence.
No local application database is deleted or rebuilt as part of this workflow.

## Regression evidence

- `tests/unit/application/test_source_derivations.py`
- `tests/unit/adapters/outbound/test_sec_history_source.py`
- `tests/contract/ports/test_cached_corpus.py`
- `tests/unit/scripts/test_publish_cleaned_corpus.py`
- `tests/integration/test_populated_corpus_upgrade.py`: schemas populated through
  migrations 0007, 0008 and 0010; legacy PDF hash correction, unknown originals,
  immutable scores/snapshot/prediction evidence, canonical replay, changed
  cleaning, and actual CSV PDF byte-hash round trip.
- `tests/integration/test_cached_sources.py`: real history membership and dates,
  original-byte deduplication, non-earnings ingestion, frozen scope and inventory.

FEAT-015 remains `in_progress` for the separately documented market-data/evaluation
manifest and forward-horizon work. No research population or split is expanded.

Verification: **273 tests passed** with PostgreSQL enabled; **11 optional
integration cases skipped** in that fast-suite invocation. The **9 real-cache /
research-history cases passed separately**. Populated migration checks used
isolated schemas in a temporary local PostgreSQL instance, including duplicate
legacy materializations and unknown original PDF identities. Formatting, imports,
lint, mypy, compilation, package build, dependency audit, lock consistency and
document/registry/diff checks passed. Qdrant integration was not configured.
