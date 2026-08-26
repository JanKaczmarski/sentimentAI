# Development Rules

## Purpose

This document governs autonomous and AI-assisted development of the thesis
implementation. Its purpose is to keep incremental work aligned with the
research scope, target architecture, and reproducibility requirements.

These rules apply to all work in `src/sentiment_system/`, tests,
infrastructure, documentation, and automation. The legacy `poc/` remains a
read-only reference unless an explicitly approved comparison requires a
change.

## Sources Of Truth

Agents must read the following before implementing a feature:

1. `AGENTS.md` for repository constraints and verification commands.
2. `ARCHITECTURE.md` for the target system design and boundaries.
3. `THESIS_DECISIONS.md` for research methodology and open decisions.
4. `FEATURES.yaml` for the approved feature backlog, dependencies, and
   acceptance criteria.
5. `IMPLEMENTATION_WORKFLOW.md` for the required delivery process.
6. Relevant records in `decisions/` for decisions that affect the feature.

`FEATURES.yaml` is the authoritative backlog. An agent must not implement a
new product or research feature inferred only from prose, code comments, or
the legacy POC.

## Feature Authority And Scope

- An autonomous implementation may work on only one feature at a time. If one
  feature is `in_progress`, resume it before selecting any `ready` feature.
- A `queued` feature is fully specified and approved but waits only for its
  dependencies. Promote it through `scripts.reconcile_feature_readiness`, never
  by inferring that an incomplete dependency is safe to bypass.
- The selected feature must be unblocked, have all dependencies complete, and
  include explicit acceptance criteria, scope, non-goals, architecture
  placement, and required verification.
- Agents must not broaden feature scope, add speculative abstractions, or
  bundle unrelated cleanup into a feature change.
- If a requirement, dependency, ownership boundary, or acceptance criterion
  is ambiguous, the agent must mark the feature blocked and ask for a decision
  rather than making an assumption.
- A feature may be marked complete only when every acceptance criterion has
  evidence from implementation and verification.
- Until `FEATURES.yaml` exists, autonomous application-feature selection is
  disabled. Explicitly requested repository-governance setup work is allowed.

## Architecture Rules

- Preserve the modular-monolith dependency direction:
  `domain -> application -> ports -> adapters -> bootstrap`.
- Domain entities and application use cases must not import FastAPI, database
  drivers, Qdrant clients, Docker APIs, provider SDKs, or framework-specific
  types.
- Add a port only for an external or replaceable boundary. Do not create ports
  merely to wrap local implementation details.
- Keep HTTP request/response schemas in inbound adapters; keep persistence and
  provider representations in outbound adapters; translate them at boundaries.
- Compose dependencies in `bootstrap/`; do not construct concrete adapters in
  domain entities or use cases.
- Reuse the two-stage research model: investor-independent chunk scoring and
  aggregation first, deterministic Investment Thesis personalization second.
- Keep the smallest correct design. A new abstraction requires a concrete
  current use, not only anticipated future reuse.

## Test-Driven Delivery

- For behavior changes, write a failing domain or application-level test
  before production implementation and observe its failure.
- Implement the smallest behavior that makes the test pass, then refactor only
  while the test suite remains green.
- Add contract tests when a port gains a concrete adapter.
- Add integration tests for real infrastructure, API composition, or a
  cross-boundary workflow.
- Use fakes for unit tests. Real LLMs, embeddings, PostgreSQL, Qdrant, and
  external data services belong in contract or integration coverage only.
- Documentation-only and configuration-only changes must include an
  appropriate validation step even when a failing unit test is not relevant.

## Research Integrity And Reproducibility

- Do not change the stated research question, corpus scope, evaluation split,
  benchmark methodology, target definitions, or personalization methodology
  without an explicit recorded decision.
- Do not tune coefficients, thresholds, prompts, or selection rules against
  the held-out evaluation period.
- Preserve source identifiers and publication dates so that evaluation can
  prevent look-ahead bias.
- Persist required experiment provenance: input source/version, processing
  configuration, model/provider configuration, prompts, raw responses, parsed
  outputs, thesis parameters, run ID, and timestamps. Never persist secrets.
- Use real local embeddings for thesis results; mock embeddings are limited to
  tests and local development support.
- Treat data cleanup as an experiment variable when it can affect research
  outcomes. Preserve raw source material separately from cleaned text.

## Security And Data Handling

- Never commit API keys, tokens, passwords, personally identifiable data, or
  non-public source material.
- Keep credentials in environment variables or ignored local files only.
- Do not log secrets, include them in prompts, or save them in experiment
  artifacts, fixtures, screenshots, or test output.
- Do not use destructive commands or mutate persistent local data unless the
  feature explicitly requires it and the operation is safe and documented.
- Preserve unrelated user changes in a dirty worktree. Never revert or modify
  them unless explicitly instructed.

## Required Verification

Before a code feature can be completed, run the checks required by `AGENTS.md`:

```bash
uv run black --check src tests scripts
uv run isort --check-only src tests scripts
uv run ruff check src tests scripts
uv run mypy
uv run pytest
uv build
uv run pip-audit
docker compose config --quiet
uv run python -m scripts.check_required_docs
uv run python -m scripts.validate_features
```

Run relevant additional checks for the feature, such as integration tests,
contract tests, Compose startup checks, API checks, or migration checks.

If a required check cannot run because an external dependency is unavailable,
the feature is not eligible for automatic merge. Record the missing evidence
and request direction instead of claiming completion.

## Change Review And Merge

Human approval is required for every pull-request merge. Automatic merging is
disabled for this repository, even when all of the following are true:

1. The feature was selected from `FEATURES.yaml` and satisfies its acceptance
   criteria.
2. All required checks pass locally and required remote CI checks pass.
3. The diff contains only feature-related changes and necessary generated lock
   files or documentation updates.
4. No unresolved decision, research-methodology change, security concern, or
   failed verification remains.
5. The repository branch-protection and hosting-provider policies permit the
   merge without a human review.

An agent must not bypass branch protection, force-push, amend published history,
disable CI, or merge a pull request with failing or missing required checks. The
agent must request human review and wait for explicit approval for the specific
pull request before merging.

Changes to project scope, research methodology, architectural boundaries, or
these governance rules require explicit user approval and a decision record
before they may be merged.

## Reporting And Stop Conditions

- Report the selected feature, acceptance criteria, files changed, verification
  results, and any deviations at the end of each delivery cycle.
- Stop after one feature unless explicitly asked to continue.
- Stop and ask for direction when a decision is needed, a dependency is
  incomplete, a required check fails, or external access is unavailable.
- Never represent a placeholder, skipped validation, or unverified assumption
  as completed work.
