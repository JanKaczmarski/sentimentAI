# Local Cache Acquisition Contract

**Status:** Accepted
**Date:** 2026-08-26

## Purpose

Define the initial local acquisition boundary so corpus work does not block the
core scoring, aggregation, personalization, and evaluation pipeline.

## Sources

- SEC data is acquired from the official public SEC EDGAR endpoints, including
  `data.sec.gov` and SEC Archives. Automated requests use a descriptive
  `SEC_USER_AGENT` containing a contact email. No SEC API key is required.
- Investor-relations material is acquired from official public company IR pages
  and manually curated into the local cache. No IR API key is required for the
  initial implementation.
- Cached market data remains the author-provided local snapshot described by the
  approved market-data decision.
- `sec-api.io` and other licensed providers are optional future product work,
  not dependencies of the thesis runtime.

## Cache And Reproducibility

- `SENTIMENT_DATA_ROOT` points to the separate research-data repository.
- Raw downloads remain unchanged. Curated copies are separate and do not replace
  raw material.
- Acquisition manifests record source, source identifier, publication date,
  retrieval URL, retrieval timestamp, raw and cleaned SHA-256 hashes, parser
  version, and manifest version. Secrets are never stored.
- The application consumes cached records through the `DocumentSource` port and
  does not require network access during scoring or evaluation.
- Repeated acquisition is idempotent by stable source identifier and content
  hash; a changed source creates a new auditable record rather than overwriting
  historical evidence.

## Scope Boundary

This decision fixes the technical acquisition mechanism and cache contract. The
final company universe, corpus cutoff, source inclusion list, and evaluation
manifest remain research curation decisions and must be recorded separately.
