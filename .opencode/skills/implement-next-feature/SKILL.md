---
name: implement-next-feature
description: Use when the user asks to implement the next feature, resume an in-progress feature, or autonomously deliver one eligible item from FEATURES.yaml with TDD and all project gates.
---

# Implement Next Feature

Use this skill only for end-to-end delivery of one approved project feature.
Do not use it to brainstorm, create a feature specification, implement a
`proposed` feature, or bypass an unresolved decision.

## Required Context

Read these files before selecting or changing a feature:

1. `AGENTS.md`
2. `docs/DEVELOPMENT_RULES.md`
3. `docs/IMPLEMENTATION_WORKFLOW.md`
4. `docs/ARCHITECTURE.md`
5. `docs/THESIS_DECISIONS.md`
6. `FEATURES.yaml`
7. `templates/feature.md`
8. Relevant records under `decisions/`, when present

Inspect `git status` and recent changes before editing. Preserve unrelated local
changes. Do not reset, revert, stage, or modify another person's work.

## Branch And Commit Convention

- `develop` is the ongoing integration branch. Start feature work from the
  latest `develop` and target feature pull requests at `develop`, not `main`.
- Keep `main` for intentional release or milestone integration. Do not merge
  every feature directly to `main`.
- Use a focused `feature/*` or `feat/*` branch when a change needs review or
  parallel work; direct commits to `develop` are reserved for explicitly
  requested, coordinated integration work.
- Keep commits atomic and use Conventional Commit prefixes such as `feat:`,
  `fix:`, `test:`, `docs:`, `chore:`, `refactor:`, and `ci:`.
- Do not mix unrelated features, generated artifacts, or data-repository
  changes in one commit. Stage only files belonging to the active feature.
- Never force-push, reset, or rewrite shared `develop` or `main` history.
- Release `develop` to `main` with a regular merge commit, subject to human
  approval. Do not squash long-lived `develop` release merges, because squash
  commits break branch ancestry and make later comparison pull requests appear
  unnecessarily large.
- After a release merge, continue from `develop`; do not recreate or reset it.
  If a historical squash has already caused divergence, reconcile the current
  `main` into `develop` with a normal merge, verify the tree and checks, and use
  regular release merges thereafter.

## Initial Gate

Run these commands from the repository root, in order:

```bash
uv run python -m scripts.check_required_docs
uv run python -m scripts.validate_features
uv run python -m scripts.check_feature_status
```

Stop and report the failure if either of the first two commands fails. Treat
the third command as the selection authority, then verify its result against
the registry and the project documents.

If no feature is `in_progress`, `implemented`, or `in_review`, inspect queued
work before selecting any `ready` feature:

```bash
uv run python -m scripts.reconcile_feature_readiness
```

If that command reports promotable features, apply only those deterministic
promotions, then validate and select again:

```bash
uv run python -m scripts.reconcile_feature_readiness --apply
uv run python -m scripts.validate_features
uv run python -m scripts.check_feature_status
```

Do not run the reconciler while a feature is `in_progress`, `implemented`, or
`in_review`. Its `--apply` mode may promote only fully specified `queued`
features whose dependencies are `complete`; report every resulting status
change.

## Select Or Resume

1. If exactly one feature is `in_progress`, resume that feature. Do not select
   a new feature or change its scope.
2. If a feature is `implemented`, create or update its pull request, change its
   status to `in_review`, and continue through the remote CI and merge gates.
   Do not start another feature.
3. If a feature is `in_review`, wait for its remote CI or merge result. Do not
   start another feature.
4. Otherwise, select the `ready` feature reported by
   `scripts.check_feature_status`: highest registry priority first, then lowest
   feature ID.
5. If no feature is eligible, report the reason and stop. Do not infer a new
   feature from source code, comments, the legacy POC, or thesis prose.
6. A user-named feature still requires a valid `ready` status, complete
   dependencies, concrete acceptance criteria, and no open decision affecting
   its scope.

Before starting a `ready` feature, verify its scope, non-goals, acceptance
criteria, architecture layers, ports, research-decision references, required
test levels, and required checks. If any item is incomplete or ambiguous, set
the feature to `blocked` with an accurate `blocked_reason`, validate the
registry, report the blocker, and stop.

Change a valid selected feature from `ready` to `in_progress` before editing
production code. Keep an already active feature as `in_progress` while
resuming it.

## Design And TDD

Before implementation, state a concise design that identifies:

- Files expected to change.
- Domain, application, port, adapter, and bootstrap responsibilities.
- New or changed contracts and translation boundaries.
- Unit, contract, and integration test sequence.
- Data provenance, migrations, configuration, and observability effects.
- Assumptions, risks, and decisions that need escalation.

For behavior changes:

1. Write a focused failing domain or application test.
2. Run it and observe the expected failure.
3. Implement the smallest correct behavior.
4. Rerun the focused test until it passes.
5. Add contract tests for changed concrete adapters.
6. Add integration tests for infrastructure, API composition, or cross-boundary
   behavior.

For documentation-only or configuration-only work, run a deterministic
validation command instead of a failing unit test and record that exception in
the feature evidence.

Respect the dependency direction:

```text
domain -> application -> ports -> adapters -> bootstrap
```

Do not put framework, database, vector-store, scheduler, or provider-SDK types
in domain or application code. Do not add speculative abstractions or unrelated
refactoring.

## Research Safeguards

For data, scoring, retrieval, prediction, or evaluation work:

- Preserve source IDs, publication dates, raw content, and required provenance.
- Avoid look-ahead bias and held-out-period tuning.
- Use real local embeddings for thesis results, not mock embeddings.
- Do not change corpus scope, splits, benchmarks, model policy, prompt policy,
  or Investment Thesis methodology without a recorded decision and explicit
  user approval.
- Never expose, commit, log, prompt with, or persist secrets.

Stop and ask for direction if the feature requires an unresolved architecture,
research, security, data, or evaluation decision.

## Verification And Evidence

Run every command listed in the selected feature's
`verification.required_checks`, then run the standard project gate:

```bash
uv run black --check src tests scripts
uv run isort --check-only src tests scripts
uv run ruff check src tests scripts
uv run mypy
uv run pytest
uv run python -m compileall -q src tests scripts
uv build
uv run pip-audit
docker compose config --quiet
uv run python -m scripts.check_required_docs
uv run python -m scripts.validate_features
uv lock --check
git diff --check
```

Run relevant feature-specific checks, including real adapter, migration, API,
or Compose startup checks where applicable. Inspect `git diff` and `git status`
before completion. The diff must be limited to the selected feature and its
necessary test, documentation, configuration, migration, or lockfile changes.

After all local gates pass:

1. Add evidence for every `AC-*` item in `completion_evidence`.
2. Add material deviations and follow-up work to `implementation_notes`.
3. Change the feature status to `implemented`.
4. Run `uv run python -m scripts.validate_features` again.

Do not claim completion if any required check is skipped, fails, or cannot run.
Fix it within approved scope, or report the evidence gap and stop.

## Pull Request And Human Approval

Human approval is mandatory for every pull-request merge. Never enable automatic
merge and never merge a pull request manually on the agent's own authority,
even when all local and remote checks pass.

For every feature:

1. Create or update a focused feature branch and pull request targeting
   `develop`, without staging unrelated local changes. If provider access or
   pull-request creation fails, leave the feature `implemented` and report the
   exact blocker.
2. After the provider confirms the pull request exists, change the registry
   status to `in_review` in that pull request and validate it locally.
3. Confirm required remote CI passed for the exact pull-request head commit.
4. Confirm the diff is scoped and every acceptance criterion has evidence.
5. Report the pull request, checks, acceptance evidence, and proposed merge,
   then stop and wait for explicit human approval for that specific PR.
6. Do not interpret `proceed`, `continue`, `go on`, or a general request for
   more work as merge approval. Approval must clearly authorize merging the
   identified pull request, for example: `approve merge PR #123`.
7. Only after that explicit approval may the agent change the registry status
   to `complete`, validate it, push the final status commit, wait for remote CI
   on that exact commit, and merge the approved pull request.
8. Verify the `complete` status is present on the default branch after merge.

Do not treat a `complete` value on an unmerged feature branch as authoritative.
Do not reconcile or select another feature from that branch after writing the
final status commit; perform those actions from the default branch after merge.

Never bypass branch protection, force-push, disable CI, merge without explicit
human approval, merge with failed or missing checks, or merge unrelated local
changes. If provider authentication, repository policy, required CI, or human
approval is unavailable, leave the feature in `in_review` and report the exact
blocker.

For an intentional release or milestone, open a separate `develop` to `main`
pull request. Review the complete release diff and exact-head CI, then use a
regular merge commit after explicit human approval. Do not use the feature
workflow to automatically start another feature after the release.

## Final Report And Stop

Report:

- Feature ID, title, and lifecycle status.
- Acceptance criteria and evidence for each.
- Files changed.
- Failing-test evidence and verification results.
- Pull request, CI, and merge status when applicable.
- Deviations, blockers, and follow-up work.

Stop after this one feature. Resume the same `in_progress` feature on a later
invocation; do not automatically start another feature.
