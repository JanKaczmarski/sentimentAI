# Run Chronology And Prediction Availability

**Status:** Accepted

**Date:** 2026-10-21

## Decision

The author approved these FEAT-038 rules before implementation:

- A run is one scoring execution over a set of chunks, either standalone or
  within a batch. Executions do not overlap in the current workflow.
- Execution order is ascending `started_at`. `run_id` breaks equal-timestamp
  ties deterministically; it never substitutes for chronology.
- The soft-exclusion rule uses the chunk's last two eligible prior scores and
  its current score. Only completed scoring/batch runs preceding the current
  run count. Three consecutive importance scores strictly below `0.05` exclude
  the chunk; a later score at or above `0.05` restores eligibility when rescored.
- The batch owns its run's start time and status through aggregation. Scoring
  must not overwrite the parent batch or prematurely mark it completed.
- Prediction generation selects the latest relevant scoring/batch execution
  by start time for the requested company and exact `as_of` date. A batch's
  configured company/date identifies it even when failure produced no snapshots;
  an unrestricted batch applies to all companies. Existing snapshot membership
  also links standalone scoring runs to their company/date.
- That latest run must be completed and contain both thesis-required windows
  for that exact date. Otherwise return `prediction snapshots unavailable`
  (the existing HTTP 404 contract), without selecting an older run or combining
  snapshots across runs/dates.

## Boundaries

No legacy-data migration is needed for the starting dataset. Missing run
metadata cannot establish an execution order or supply an automatic prediction;
raw historical records remain addressable. No historical scores, evidence,
snapshots or predictions are rewritten.

The importance threshold, streak length, aggregation, personalization, frozen
inputs and publication rules are unchanged. There is no automatic retry or
fallback in FEAT-038. FEAT-032 retains the scoring-retry policy decision;
FEAT-039 is a proposed task to decide what should happen when predictions are
unavailable. Its behavior remains TBD and requires author approval before
readiness.
