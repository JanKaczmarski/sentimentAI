# Processing And Scoring Configuration Decision

**Status:** Accepted

**Date:** 2026-08-25

## Purpose

This record fixes the initial processing and scoring configuration before
held-out evaluation. It satisfies `FEAT-004` and applies to the rebuilt thesis
pipeline, not the legacy `poc/` implementation.

## Cleaning Configuration

- Raw source content is immutable and is always retained.
- Cleaned content uses Unicode NFKC normalization, converts CRLF and CR line
  endings to LF, removes non-printing control characters except tab and line
  breaks, collapses repeated horizontal whitespace, and trims each line.
- Empty lines are retained as paragraph boundaries after normalization.
- The baseline configuration removes only deterministic boilerplate patterns:
  standalone page markers matching `page N` or `N of M`, and an exact
  normalized paragraph repeated at least three times in one document. All
  other content remains in the cleaned representation.
- Cleaning never modifies source identifiers, publication dates, document type,
  raw content, or document lineage.

## Chunking Configuration

- Chunking is sentence-aware and uses three sentences per chunk.
- A trailing single sentence is merged into the preceding chunk when possible;
  otherwise it remains a one-sentence chunk so no content is discarded.
- A chunk may not exceed 2,000 tokens. Token counts use the selected scoring
  model tokenizer, and the tokenizer identifier is recorded in provenance.
- Chunks have no overlap and receive stable zero-based ordinals within their
  source document.
- Chunk boundaries and remainder handling are deterministic for identical input
  and configuration.

## RAG Variants

Two variants are declared before evaluation and are run independently:

1. `standard`: scoring receives the cleaned chunk without a generated summary.
2. `contextual`: one document-level summary is generated without investor
   information, its prompt and raw/parsed output are retained, and the summary
   is prepended to each cleaned chunk before scoring.

The Investment Thesis is not included in either scoring variant. Personalization
occurs only in the later deterministic thesis stage.

## Scoring Contract

- The scoring prompt is investor-independent and requests JSON with exactly
  `score`, `confidence`, and `importance_score` fields.
- `score`, `confidence`, and `importance_score` are numeric values in `[0, 1]`.
- Invalid, incomplete, or non-JSON responses are rejected and remain available
  as raw provider output for diagnosis; they are not silently converted into a
  research result.
- The initial generation temperature is `0`.
- The completion budget is `300` tokens for chunk scoring and `500` tokens for
  contextual document summaries.
- Each run records provider, model identifier, tokenizer identifier, prompt
  version, generation parameters, token usage, raw response, parsed output,
  and any parse or truncation outcome.

## Input Budget And Truncation

- The hard input budget is 15,000 tokens for the complete model input, excluding
  the completion budget.
- When context selection is required, chunks are ordered by importance score,
  then retrieval score, then stable chunk ID, all descending except the final
  identifier tie-breaker which is ascending.
- Chunks that do not fit are omitted, and the run records the selected chunk
  identifiers, omitted identifiers, tokenizer, measured input size, and a
  truncation flag.
- No request may exceed the budget or silently estimate token usage.

## Embedding Policy

- Research-mode retrieval uses real local semantic embeddings. The initial
  model is `BAAI/bge-small-en-v1.5`.
- Deterministic mock or hash embeddings are permitted only for unit tests and
  offline development support.
- Research mode fails closed if a mock embedding backend is selected.

## Evaluation Safeguard

These settings, prompt versions, and the two RAG variants are pre-evaluation
configuration. They must not be tuned against the held-out evaluation period.
Any later change requires a new versioned decision and a separately identified
experiment variant.
