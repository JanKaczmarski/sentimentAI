# Functional Six-Company Local Snapshot

**Status:** Accepted
**Date:** 2026-08-26

## Purpose

Provide a normal local application path for the six-company thesis sample and
other companies available in the external cache.

## Functional Scope

- The initial functional snapshot covers `AAPL`, `MSFT`, `NVDA`, `JPM`, `XOM`,
  and `JNJ`.
- These six symbols are active entries in the canonical operational registry;
  source adapters do not maintain a separate ticker allowlist.
- The snapshot cutoff is `2026-06-30`, matching the existing previous-calendar-
  quarter cache window.
- Each company must have at least one official SEC earnings-release record in
  the external research-data repository.
- SEC source identifiers, publication dates, retrieval URLs, and raw-content
  hashes remain in the external cache manifest. Raw source files remain outside
  the application repository.
- Official investor-relations records remain supported by the cache adapter but
  are not required to make a company runnable in this functional slice.

## Boundary

- This snapshot validates the local source-to-prediction application flow; it is
  not the final five-year thesis corpus or a market-outcome evaluation set.
- The canonical approved-company registry remains the source of truth for
  ticker validation. The six-company list identifies the functional thesis
  sample and must not be copied into source adapters.
- AMAT records in the external cache are consumed through the same cached-corpus
  path as the functional six-company snapshot.
