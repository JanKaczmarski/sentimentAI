# POC Corpus And Thesis Data Separation

**Status:** Accepted

**Date:** 2026-08-26

## Purpose

Allow vertical application development to proceed without presenting a small
development corpus as the final thesis dataset.

## POC Boundary

- The POC may use one or more approved companies and a small deterministic set
  of fixture or locally cached source documents.
- POC runs validate source-to-prediction orchestration, persistence, evidence,
  and API behavior only.
- POC runs are not thesis evaluation results and must not be used to tune
  scoring, aggregation, personalization, or evaluation parameters.
- The POC uses the existing investor-independent deterministic scorer for local
  and CI verification. Production LLM scoring remains owned by FEAT-023.
- Market data, the five-year corpus, the held-out split, and benchmark
  outcomes are not required for the POC vertical slice.

## Thesis Boundary

- FEAT-015 remains the owner of the complete reproducible SEC and investor-
  relations corpus and its immutable research manifest.
- FEAT-016 remains blocked until the final corpus, market data, chronological
  split, and benchmark inputs are available.
- The POC implementation must preserve the same source lineage, dates, raw and
  cleaned content, run IDs, and secret-free provenance contracts required by
  the thesis system.
