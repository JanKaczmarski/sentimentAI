# Ingestion And Evaluation Universe

**Status:** Accepted
**Date:** 2026-08-26

## Purpose

Separate the operational ingestion universe from the smaller thesis evaluation
sample so the application can accept the approved registry without silently
changing the research population.

## Universe Policy

- The FEAT-018 registry is the operational ingestion universe. Source adapters
  and market-data routing may load records for any active symbol in that
  registry.
- The v1 thesis evaluation universe remains the six-company sample from
  `decisions/0006-reproducible-research-and-runtime-contract.md`: `AAPL`,
  `MSFT`, `NVDA`, `JPM`, `XOM`, and `JNJ`.
- The final v1 research manifest must explicitly identify the six evaluation
  companies. Records for other FEAT-018 companies may remain in the cache but
  are excluded from v1 evaluation reports.
- Benchmark mapping, chronological splitting, and leakage controls apply to
  the v1 evaluation universe and must not be inferred from the broader cache.
- Expanding the v1 evaluation universe requires a new recorded decision and a
  new manifest; it is not an incidental consequence of ingestion.

## Consequences

- FEAT-018 owns the canonical operational registry and must not be duplicated in
  source or market adapters.
- FEAT-015 owns cache acquisition and manifest validation; its final manifest
  must carry the selected evaluation-universe membership.
- FEAT-016 evaluates only the explicit v1 manifest and never treats all cached
  records as thesis evidence.
