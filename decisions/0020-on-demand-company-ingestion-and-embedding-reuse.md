# On-Demand Company Ingestion And Embedding Reuse

**Status:** Accepted (author-approved FEAT-030 choices)

**Date:** 2026-10-21

## HTTP and source selection

- `POST /companies/{company}/ingest` prepares exactly one approved company.
- The JSON request accepts optional `as_of` (default today) and `source_scope`
  (`operational` by default, or explicit `frozen`). Unknown fields are rejected.
- Use the same canonical ticker registry and validation message as `/batch/run`.
- Both scopes use publication strictly before `as_of`, not fiscal reporting dates.
  Frozen scope requires the configured, verified immutable corpus and never falls
  back to the operational cache or development fixtures.
- Approved companies without eligible documents complete successfully with zero
  counts. Unsupported companies return HTTP 422 without creating a run.

## Results and audit identity

- Successful requests return HTTP 200, `status=completed`, `run_id`, canonical
  `company`, `source_scope`, `document_count`, `chunk_count`,
  `indexed_chunk_count`, `embedded_chunk_count`, and `reused_chunk_count`.
- Document/chunk/index counts describe total selected data, including existing
  items. Embedding/reuse counts distinguish new successful indexing from compatible
  existing points; together they equal the indexed count on success.
- Every valid attempt creates a fresh `ingestion` audit run, including empty and
  failed attempts. Idempotency applies to underlying documents/chunks/points.
- Record source lineage/hashes, processing version, source scope and available
  manifest identity, embedding configuration/fingerprint, stage timestamps and
  counts. Failed attempts retain completed ingestion lineage and confirmed prior
  indexing batches, and return HTTP 500 with their run ID. Persist exception types,
  not provider exception messages or connection strings.
- These runs make no scoring/summary calls or snapshots and do not participate in
  scoring chronology, exclusion streaks or latest-prediction selection.

## Compatible embedding reuse

- PostgreSQL remains the source of truth for documents, chunks and completed-score
  exclusion state. Immutable source/cleaning/chunk derivations are unchanged.
- Inspect actual vector points before embedding: an existing document/chunk row
  alone does not establish that its vector exists.
- Reuse requires exact chunk identity/content/configuration, company/publication
  metadata, a nonempty vector, and a matching SHA-256 embedding-configuration
  fingerprint. The runtime fingerprints backend, effective model identifier and
  encoding version; the chunk identity includes processing configuration.
- Legacy points without a fingerprint and incompatible points are re-embedded and
  upserted once using the configured model. Compatible repeated requests avoid all
  embedding calls, including after rebuilding the application container.
- Inspect/index in bounded batches of 128 chunks. Following a failure, another
  explicit request reuses completed points and repairs missing ones. There is no
  background job, automatic retry or per-chunk durable worker checkpoint.
- Preserve/synchronize the latest completed scoring run's exclusion state through
  payload-only updates, including on vector reuse; failed score runs are ignored.
- A model dimension incompatible with the existing collection fails explicitly;
  no collection is deleted or silently rebuilt. Configure a distinct collection
  for a dimension-changing model. Mutable model aliases must not be repointed
  while retaining the same declared embedding identity/encoding version.
- Lookup/provider/vector failures fail the attempt explicitly; they do not mean
  that all points are missing or justify a synthetic embedding fallback.

## Boundaries

The existing combined `/batch/run` retains its response contract and continues to
score/aggregate on each call, while sharing compatible vector reuse. Cleaning,
chunking, model policy, frozen membership and personalization remain unchanged.
The existing tokenizer-compliance follow-up remains with FEAT-023. Browser controls,
contextual summaries and durable scoring jobs remain with FEAT-034/031/032.
