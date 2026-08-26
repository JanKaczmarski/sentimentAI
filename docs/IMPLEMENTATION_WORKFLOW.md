# Implementation Workflow

## Purpose

This is the required delivery workflow for autonomous and AI-assisted feature
implementation. It operationalizes `DEVELOPMENT_RULES.md` and uses
`FEATURES.yaml` as the authoritative feature registry.

An implementation cycle delivers at most one feature. It must either produce
a verified, reviewable feature change or stop with a clear blocker. It must not
silently change project scope or select a different feature to avoid a blocker.

## Required Inputs

Before selecting or implementing a feature, read:

1. `AGENTS.md`
2. `DEVELOPMENT_RULES.md`
3. `ARCHITECTURE.md`
4. `THESIS_DECISIONS.md`
5. `FEATURES.yaml`
6. `templates/feature.md`
7. Relevant records in `decisions/`, when that directory exists

Inspect the current worktree and recent changes before editing. Preserve
unrelated local work and do not revert it.

## Feature Selection

An agent works on no more than one feature at a time. If exactly one feature is
`in_progress`, resume it on the next invocation rather than selecting another
feature. Do not switch away from it unless the user explicitly directs that it
be blocked or rejected. If a feature is `implemented`, create or update its
pull request and transition it to `in_review` rather than selecting another
feature. If a feature is `in_review`, wait for its CI or merge outcome rather
than selecting another feature.

When no feature is active, run:

```bash
uv run python -m scripts.reconcile_feature_readiness --apply
uv run python -m scripts.validate_features
uv run python -m scripts.check_feature_status
```

The reconciler may promote only `queued` features whose dependencies are all
`complete`. It must not infer an architectural or research decision, unblock a
feature, or bypass an incomplete dependency.

Select the next feature using this deterministic order:

1. Consider only features whose `status` is `ready`.
2. Exclude features with an unresolved research decision, missing required
   field, placeholder, or invalid lifecycle state.
3. Select by the `priority_order` in `FEATURES.yaml`, then by ascending feature
   ID.

When a user explicitly requests a feature ID and no other feature is active,
validate it with the same rules. Do not implement a `proposed`, `blocked`, or
`queued` feature merely because it was named.

If no eligible feature exists, report why and stop. Do not infer or create a
new feature as a substitute.

## Readiness Gate

Before changing a selected feature to `in_progress`, verify all of the
following:

- Every field required by `FEATURES.yaml` is present and concrete.
- Scope and non-goals define an atomic change.
- Acceptance criteria are objective and each has a unique `AC-*` ID.
- Architecture layers and affected ports are explicit and conform to
  `ARCHITECTURE.md`.
- The selected feature does not require an undecided research-methodology,
  data, evaluation, or security choice.
- Required test levels and checks are appropriate for the change.
- All dependencies are `complete`.

If any condition fails, change the status to `blocked` only when the failure is
known and can be described accurately in `blocked_reason`. Otherwise leave the
registry unchanged, report the gap, and stop.

## Design Gate

Before production code changes, prepare a concise implementation design that
states:

- Expected files to add or change.
- Domain, application, port, adapter, and bootstrap responsibilities.
- New or changed contracts and the owner of each translation boundary.
- Test sequence: unit tests first, then contract and integration coverage where
  applicable.
- Data, provenance, migration, configuration, and observability implications.
- Risks, assumptions, and any decision that would require escalation.

The design must preserve the modular-monolith dependency direction and make no
new architectural or research decision. Record material deviations or follow-up
work in the feature's `implementation_notes`.

## Implementation Gate

1. Change the selected feature status from `ready` to `in_progress` before
   editing implementation code.
2. Write a focused failing test for the required behavior and observe the
   failure.
3. Implement the smallest correct behavior that makes the test pass.
4. Refactor only while tests remain green.
5. Add contract coverage for a changed concrete adapter.
6. Add integration coverage for infrastructure, API composition, or
   cross-boundary behavior.
7. Update documentation, configuration, migrations, and metrics only when the
   feature requires them.

For documentation-only or configuration-only changes, replace the failing-test
step with a relevant deterministic validation command. State that exception in
the final evidence.

## Research And Data Gate

For any feature that processes research data, scores documents, retrieves
evidence, generates predictions, or evaluates outcomes, verify that it:

- Preserves source identifiers, publication dates, and raw source material.
- Separates raw and cleaned content when cleaning can affect results.
- Records applicable run, model, prompt, parameter, and output provenance.
- Does not introduce look-ahead bias.
- Does not use mocked embeddings for thesis-result generation.
- Does not expose, persist, or log secrets.

Stop for an explicit decision if the feature would change corpus scope,
evaluation methodology, benchmark selection, held-out split, model policy, or
Investment Thesis algorithm.

## Verification Gate

Run every command declared in the feature's `verification.required_checks`,
then run any relevant feature-specific checks. A standard code feature normally
requires:

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

Also inspect the diff and worktree state. Confirm that the diff is scoped to
the feature, generated files are intentional, and no secret or unrelated user
change is included.

Fix failures while they remain within approved scope. If a required check cannot
run or cannot be fixed without an unapproved decision, do not mark the feature
implemented or complete. Report the evidence gap and stop.

## Evidence And Lifecycle Gate

After local verification succeeds:

1. Add `completion_evidence` for every acceptance criterion. Each entry names
   the relevant `AC-*` identifier and the test, command, or reviewable artifact
   that proves it.
2. Record material deviations, tradeoffs, and intentionally deferred work in
   `implementation_notes`.
3. Change the feature status to `implemented`.
4. Create or update the feature pull request without staging unrelated local
   changes. If the hosting provider cannot confirm a pull request, leave the
   feature `implemented` and report the blocker.
5. After the pull request exists, change the feature status to `in_review` in
   that pull request and rerun registry validation.

For an automatic merge, move the status to `complete` in the final
pull-request commit only after its preceding candidate commit has passed remote
CI. The final commit must pass CI before merging. A `complete` value on an
unmerged feature branch is not authoritative: do not run reconciliation or
feature selection from that branch. After merge, verify that the default branch
contains the `complete` status. A status of `complete` means the feature is
present on the default branch, not merely that its local code passes tests.

## Automatic Merge Gate

Automatic merge is allowed only when all of these conditions are true:

- Before the final status commit, the feature status is `in_review` and every
  acceptance criterion has evidence.
- All local checks and feature-specific verification succeeded.
- Required remote CI checks passed for the pull request head commit.
- The pull request diff contains only approved feature work.
- Repository branch protection allows automatic merging without human review.
- No unresolved blocker, security issue, research-methodology change, or
  governance change exists.

Remote CI must be attached to the pull request or exact candidate commit. A
manual workflow run on a different ref is not sufficient merge evidence.

Never bypass branch protection, disable CI, force-push, or merge around a failed
or missing required check. If the host policy requires review, request it and
leave the feature in `in_review`.

## Stop Conditions

Stop and report the exact reason when any of the following occurs:

- No feature satisfies the selection rules.
- A feature specification is incomplete or ambiguous.
- A required architecture or research decision is unresolved.
- A dependency is incomplete.
- A required check fails or cannot run.
- Required external access or infrastructure is unavailable.
- Existing local changes conflict with the feature.
- The feature would require scope expansion beyond its approved non-goals.

Do not start another feature after stopping. Await explicit direction or a new
invocation of the workflow.

## Final Delivery Report

At the end of every implementation cycle, report:

- Selected feature ID and title.
- Acceptance criteria and the evidence for each.
- Files added or changed.
- Test-first evidence and the verification commands run.
- Lifecycle status reached.
- Any deviations, blockers, or follow-up work.
- Pull request, CI, and merge status when applicable.
