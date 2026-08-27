# Normal Cached-Corpus Company Workflow

**Status:** Accepted
**Date:** 2026-08-27

## Purpose

Make every company with valid external cached records available through the
normal application source path. A user should be able to create an Investment
Thesis and run a company batch in the browser without selecting a demonstration
manifest or enabling demonstration-specific runtime code.

## Decision

- `CachedCorpusDocumentSource` is the only external document source selected
  when `SENTIMENT_DATA_ROOT` is configured.
- The bounded AMAT manifest adapter and its `DEMO_MANIFEST_PATH` configuration
  are retired.
- AMAT is processed from all normal SEC and curated investor-relations records
  available before the requested as-of date.
- The raw and curated AMAT files remain in `sentimentAI-data` as ordinary
  research inputs.
- Batches remain one company at a time and retain the existing scoring,
  aggregation, personalization, and provenance behavior.

## Consequences

The normal AMAT workflow no longer reproduces the former two-document count or
its exact bounded output. It provides the same user experience and processing
path as the other cached companies. The current data remains a functional local
snapshot rather than the final thesis corpus or evaluation set.
