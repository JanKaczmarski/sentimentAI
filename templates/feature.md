# Feature Specification Template

Copy the YAML entry below into the `features` list in `FEATURES.yaml`. Replace
every quoted placeholder before marking a feature `ready`. Do not create a
feature from an inferred idea alone; its scope and acceptance criteria must be
explicitly approved or derived from an existing approved project decision.

```yaml
- id: FEAT-XXX
  title: "Short, outcome-oriented feature title"
  status: proposed
  priority: medium
  depends_on: []
  scope:
    - "Concrete behavior included in this feature."
  non_goals:
    - "Explicitly excluded behavior or follow-up work."
  acceptance_criteria:
    - id: AC-1
      description: "Observable, testable outcome the implementation must provide."
  architecture:
    layers:
      - application
    ports: []
  research_decisions:
    - "docs/THESIS_DECISIONS.md#relevant-section"
  verification:
    required_test_levels:
      - unit
    required_checks:
      - "uv run black --check src tests scripts"
      - "uv run isort --check-only src tests scripts"
      - "uv run ruff check src tests scripts"
       - "uv run mypy"
       - "uv run pytest"
       - "uv build"
       - "uv run pip-audit"
       - "uv run python -m scripts.check_required_docs"
      - "uv run python -m scripts.validate_features"
  blocked_reason: null
  completion_evidence: []
  implementation_notes: []
```

## Field Rules

- `id` is a unique, permanent identifier in the form `FEAT-XXX`.
- `title` describes the outcome, not an implementation task such as "add a
  class".
- `depends_on` contains only feature IDs. Use `queued` for a fully specified
  feature that waits only for incomplete dependencies; the reconciler promotes
  it to `ready` after they are `complete`.
- `scope` and `non_goals` are concise, concrete lists. They define the allowed
  diff and prevent opportunistic scope expansion.
- Each acceptance criterion has a stable `AC-*` ID and describes an outcome
  that can be verified by a test, command, or reviewable artifact.
- `architecture.layers` identifies the affected system layers. `ports` lists
  the external-boundary interfaces added or changed; use `[]` when none apply.
- `research_decisions` contains document paths and section anchors that govern
  the feature. Use `[]` only when the feature cannot affect research behavior.
- `required_test_levels` uses the applicable values from `unit`, `contract`,
  and `integration`. Configuration-only work may use `[]` only when its
  validation is fully represented in `required_checks`.
- `blocked_reason` must be a non-empty explanation when `status` is `blocked`;
  otherwise it must be `null`.
- `completion_evidence` is empty until work is verified. Each entry must name
  an acceptance criterion and its evidence.
- `implementation_notes` records material deviations, tradeoffs, or follow-up
  work. It is not a substitute for an acceptance criterion or decision record.

## Status Transitions

- Use `proposed` for a fully described candidate that has not passed the
  readiness gate.
- Use `blocked` when a decision, dependency, or external access prevents safe
  implementation.
- Use `queued` for fully specified approved work waiting only for dependencies;
  `scripts.reconcile_feature_readiness --apply` promotes it when eligible.
- Use `ready` only when all required fields are concrete, dependencies are
  complete, and no open research decision affects the work.
- An implementation agent changes `ready` to `in_progress` before editing code.
- Use `implemented` after local verification completes, then `in_review` while
  required remote checks run.
- Use `complete` only after the feature is integrated into the default branch
  and each acceptance criterion has recorded evidence.

## Completion Evidence Template

Replace the empty `completion_evidence` list only after verification:

```yaml
completion_evidence:
  - acceptance_criterion: AC-1
    evidence:
      - "tests/unit/application/test_example.py::test_expected_behavior"
      - "uv run pytest"
```
