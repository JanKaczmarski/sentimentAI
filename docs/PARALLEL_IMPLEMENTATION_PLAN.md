# Two-engineer implementation plan

Estimate based on the 2026-10-19 system audit, not a delivery commitment.
Merge this backlog/audit change into `develop` before branching for the work.
Each row starts after the previous row's relevant changes are merged and both
engineers have updated their branches. A faster lane can finish early; the rows
are integration checkpoints, not a requirement to keep both engineers busy.

## Recommended sequence

| Phase | Engineer A | Engineer B | Rough effort per feature | Reason |
|---|---|---|---|---|
| 0 | FEAT-038: chronological history/latest-run correctness | Confirm Cyfronet access, protocol and model capabilities | 038: 1–2 engineer-days | Merge the chronology contract before more changes to scoring, predictions and repositories. Cyfronet discovery is preparation, not a completed implementation. |
| 1 | FEAT-022: complete pipeline wiring and research configuration guard | Review run/stage contracts and prepare test cases | 022: 2–4 days | Keep this foundation sequential with 038. They can both touch run state, repository contracts, prediction wiring and `container.py`. |
| 2 | FEAT-030: dedicated ingest/index workflow and embedding reuse | FEAT-037: Cyfronet API adapter/configuration, if ready | 030: 2–3 days; 037: 1–3 days plus access delays | Ingestion/indexing and provider/configuration are largely separate. Keep the existing LLM port stable; merge any shared bootstrap wiring in order. |
| 3 | FEAT-023: provider/scoring contract, token budgets and failure provenance | FEAT-033: display-only evidence ranking/deduplication | 023: 3–5 days; 033: 2–3 days | LLM request/audit behavior is separate from prediction evidence presentation. Agree on provenance storage and reserve migrations before starting. |
| 4 | FEAT-031: document summaries and contextual scoring | Review the evaluation test matrix and worker design | 031: 3–5 days | Start after 030 and 023 are merged. It overlaps heavily with 023's scorer/tokenizer/provenance code; do not build competing implementations. |
| 5 | FEAT-032: durable scoring jobs, progress and restart resume | FEAT-016: frozen-scope evaluation runner and reports | 032: 4–6 days; 016: 3–5 days | Job execution and market-outcome calculation are different areas once run and scoring contracts are stable. Final research execution waits for stable model/run settings and the necessary scored predictions. |
| 6 | FEAT-017: schedules, pipeline metrics/logs, readiness and Grafana | FEAT-034: ingest/score/poll/ranking console UI | 017: 3–5 days; 034: 2–4 days | Backend operations versus static UI is a clean division after 016/032/033 are complete and endpoints are stable. |

Allow roughly **4–6 working weeks** for the core sequence with two experienced
engineers, including integration/review contingency. The per-feature estimates
are active engineering effort, not time to obtain external access or run the
full corpus through an LLM. Long scoring jobs can add elapsed time without
adding equivalent engineering effort. This is deliberately less than full
two-person utilization because several shared contracts should be changed once.

FEAT-021 (licensed financial providers) stays outside the core sequence. Its
effort cannot be estimated responsibly until the provider, entitlement and
budget are known.

## Readiness and dependency gates

- FEAT-022, FEAT-030 and FEAT-033 are currently `ready`.
- FEAT-023, FEAT-037 and FEAT-038 are `proposed`: complete their readiness review
  before implementation. A planning row does not promote their registry status.
  In particular, agree on explicit treatment of unknown legacy chronology for
  038 and confirm endpoint/auth/model/structured-output capabilities for 037.
- The normal autonomous selector still chooses FEAT-022. Starting 038 first is
  a recommended human-coordinated correctness-first sequence, not a silent
  change to registry priorities or an instruction to bypass readiness.
- FEAT-031 waits for 030; this plan additionally serializes it after 023 to avoid
  scorer/tokenizer conflicts. FEAT-032 waits for 031.
- FEAT-016 formally waits for 022. Running it later in this plan avoids building
  final experiments on unstable scoring semantics. Keep its runner/tests separate
  from the final, explicitly configured research execution.
- FEAT-017 waits for 016, 022 and 032; FEAT-034 waits for 030–033. Do not start
  either as an end-to-end feature before those contracts exist.
- If Cyfronet access is unavailable, defer 037. Continue the core work using the
  existing approved provider; do not make optional access a new pipeline blocker.
  If 037 moves later, serialize it with 023's shared provider/configuration work.

## File ownership to reduce merge conflicts

| Area | Owner at a given checkpoint |
|---|---|
| `application/ports/repositories.py`, `domain/scoring.py`, run-order/state contracts | 038 first, then pipeline/worker owner. Agree on signatures before the other lane consumes them. |
| `persistence/postgres.py`, `persistence/in_memory.py`, SQL migrations | One named persistence integrator. The other engineer contributes focused methods/tests; reserve unique migration numbers after inspecting the current latest migration. |
| `bootstrap/container.py`, `bootstrap/main.py` | One named runtime integrator per phase. Adapter/helper work can proceed in parallel; final constructor/lifespan wiring merges in order. |
| API `routes.py` / `schemas.py` | The active backend feature owner. Freeze endpoint shapes before UI work; introduce focused route modules when the implementation warrants them. |
| `ingest_documents.py`, `index_chunks.py`, new ingestion workflow | 030 owner. The provider lane should not rework chunking at the same time. |
| LLM adapters, provider configuration, token budgeting, `score_chunks.py` | Provider/scoring owner: 037 → 023 → 031 in sequence where they overlap. |
| Prediction evidence ranking, vector search helpers, ranking tests | 033 owner; keep sentiment/aggregation values unchanged. Coordinate shared prediction wiring with the runtime integrator. |
| Evaluation runner, market coverage, evaluation report tests | 016 owner; use the frozen data lock, existing outcome resolver and approved benchmark rules. |
| Scheduler, metrics, monitoring configuration | 032 owns durable worker lifecycle first; 017 extends that lifecycle rather than creating another worker. |
| `web/` and UI tests | 034 owner after backend endpoint contracts stabilize. |
| `FEATURES.yaml` and shared delivery evidence | One integration coordinator resolves status/evidence updates against latest `develop`. Preserve both features' changes; do not overwrite the file with a branch's older copy. |

Each engineer uses a separate named feature branch/worktree from `develop`,
with one active feature in that branch. Keep the existing one-active-feature
validation; this estimate does not change project governance. Finish each
feature with its own tests, scoped PR and required human merge approval.

Before each phase, agree on the small shared contracts: repository signatures,
run identity/states, tokenizer/budget ownership, error/provenance representation,
and API response shapes. Avoid simultaneous cleanup/renames of shared files.
After the first lane merges, bring latest `develop` into the second branch and
run the combined checks before merging it.

## Pairs to keep sequential

- **038 with 022/032:** execution chronology, run state and persistence overlap.
- **023 with 031:** scorer interfaces, tokenizer budgets and failure provenance overlap.
- **031 with 032:** the durable job must execute a settled scoring operation.
- **032 with 017:** worker/scheduler startup, shutdown and job ownership overlap.
- **030/032 with 034:** implement and settle the endpoint first, then wire the UI.
- **037 with 023 when both edit the common LLM client/configuration:** finish one
  before integrating the other, rather than developing two provider frameworks.

These are conservative integration choices, not additional registry dependencies
unless the feature specification explicitly declares them.
