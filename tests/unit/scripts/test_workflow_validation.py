"""Tests for the repository-governance validation scripts."""

from pathlib import Path

from scripts.check_feature_status import select_feature
from scripts.check_required_docs import REQUIRED_DOCUMENTS, find_missing_required_docs
from scripts.reconcile_feature_readiness import promote_queued_features, queued_features_ready_for_promotion
from scripts.validate_features import validate_registry


def _feature(
    feature_id: str = "FEAT-001",
    *,
    status: str = "ready",
    depends_on: list[str] | None = None,
    completion_evidence: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    return {
        "id": feature_id,
        "title": "Example feature",
        "status": status,
        "priority": "high",
        "depends_on": depends_on or [],
        "scope": ["Provide one testable behavior."],
        "non_goals": ["Do not expand the feature scope."],
        "acceptance_criteria": [
            {
                "id": "AC-1",
                "description": "The behavior is observable and testable.",
            }
        ],
        "architecture": {"layers": ["application"], "ports": []},
        "research_decisions": [],
        "verification": {
            "required_test_levels": ["unit"],
            "required_checks": ["uv run pytest"],
        },
        "blocked_reason": None,
        "completion_evidence": completion_evidence or [],
        "implementation_notes": [],
    }


def _registry(features: list[dict[str, object]] | None = None) -> dict[str, object]:
    return {
        "schema_version": 1,
        "project": "test-project",
        "lifecycle": {
            "maximum_in_progress": 1,
            "selection_status": "ready",
            "priority_order": ["critical", "high", "medium", "low"],
            "statuses": {
                status: {"selectable": status == "ready", "terminal": status in {"complete", "rejected"}}
                for status in (
                    "proposed",
                    "blocked",
                    "queued",
                    "ready",
                    "in_progress",
                    "implemented",
                    "in_review",
                    "complete",
                    "rejected",
                )
            },
        },
        "feature_contract": {
            "required_fields": [
                "id",
                "title",
                "status",
                "priority",
                "depends_on",
                "scope",
                "non_goals",
                "acceptance_criteria",
                "architecture",
                "research_decisions",
                "verification",
            ],
            "completion_evidence_required_for": ["complete"],
            "blocked_reason_required_for": ["blocked"],
            "architecture_fields": ["layers", "ports"],
            "verification_fields": ["required_test_levels", "required_checks"],
        },
        "selection": {
            "order": ["priority", "id"],
            "require_completed_dependencies": True,
            "require_all_acceptance_criteria": True,
            "require_no_open_research_decisions": True,
        },
        "automatic_merge": {
            "enabled": True,
            "require_local_verification": True,
            "require_remote_ci": True,
            "require_clean_feature_scope": True,
            "require_hosting_policy_compliance": True,
        },
        "features": features or [],
    }


def test_validate_registry_accepts_an_empty_registry() -> None:
    assert validate_registry(_registry()) == []


def test_validate_registry_rejects_a_ready_feature_with_an_incomplete_dependency() -> None:
    dependency = _feature("FEAT-001", status="proposed")
    dependent = _feature("FEAT-002", depends_on=["FEAT-001"])

    errors = validate_registry(_registry([dependency, dependent]))

    assert "FEAT-002 depends on FEAT-001, which is not complete" in errors


def test_validate_registry_allows_a_queued_feature_to_wait_for_a_dependency() -> None:
    dependency = _feature("FEAT-001", status="proposed")
    queued = _feature("FEAT-002", status="queued", depends_on=["FEAT-001"])

    assert validate_registry(_registry([dependency, queued])) == []


def test_validate_registry_requires_evidence_for_each_complete_feature_criterion() -> None:
    complete_feature = _feature("FEAT-001", status="complete")

    errors = validate_registry(_registry([complete_feature]))

    assert "FEAT-001 is complete but has no completion evidence for AC-1" in errors


def test_validate_registry_rejects_multiple_active_features() -> None:
    first_active = _feature("FEAT-001", status="in_progress")
    second_active = _feature("FEAT-002", status="in_progress")

    errors = validate_registry(_registry([first_active, second_active]))

    assert "2 features are in_progress, exceeding lifecycle.maximum_in_progress of 1" in errors


def test_select_feature_resumes_the_active_feature() -> None:
    active = _feature("FEAT-001", status="in_progress")
    ready = _feature("FEAT-002", status="ready")

    selection_type, feature = select_feature(_registry([active, ready]))

    assert selection_type == "resume"
    assert feature is active


def test_select_feature_uses_priority_then_feature_id() -> None:
    lower_priority = _feature("FEAT-001", status="ready")
    higher_priority = _feature("FEAT-002", status="ready")
    higher_priority["priority"] = "critical"

    selection_type, feature = select_feature(_registry([lower_priority, higher_priority]))

    assert selection_type == "next"
    assert feature is higher_priority


def test_select_feature_waits_for_a_feature_in_review() -> None:
    reviewing = _feature(
        "FEAT-001",
        status="in_review",
        completion_evidence=[{"acceptance_criterion": "AC-1", "evidence": ["uv run pytest"]}],
    )
    ready = _feature("FEAT-002", status="ready")

    selection_type, feature = select_feature(_registry([reviewing, ready]))

    assert selection_type == "awaiting_review"
    assert feature is reviewing


def test_select_feature_requests_review_for_an_implemented_feature() -> None:
    implemented = _feature(
        "FEAT-001",
        status="implemented",
        completion_evidence=[{"acceptance_criterion": "AC-1", "evidence": ["uv run pytest"]}],
    )
    ready = _feature("FEAT-002", status="ready")

    selection_type, feature = select_feature(_registry([implemented, ready]))

    assert selection_type == "needs_review"
    assert feature is implemented


def test_reconciler_finds_queued_features_with_complete_dependencies() -> None:
    completed = _feature(
        "FEAT-001",
        status="complete",
        completion_evidence=[{"acceptance_criterion": "AC-1", "evidence": ["uv run pytest"]}],
    )
    queued = _feature("FEAT-002", status="queued", depends_on=["FEAT-001"])
    waiting = _feature("FEAT-003", status="queued", depends_on=["FEAT-002"])

    promotable = queued_features_ready_for_promotion(_registry([completed, queued, waiting]))

    assert [feature["id"] for feature in promotable] == ["FEAT-002"]


def test_reconciler_preserves_comments_while_promoting_feature_status(tmp_path: Path) -> None:
    registry_path = tmp_path / "FEATURES.yaml"
    registry_path.write_text(
        "# Keep this comment.\nfeatures:\n  - id: FEAT-001\n    status: queued\n",
        encoding="utf-8",
    )

    promote_queued_features(registry_path, ["FEAT-001"])

    assert registry_path.read_text(encoding="utf-8") == (
        "# Keep this comment.\nfeatures:\n  - id: FEAT-001\n    status: ready\n"
    )


def test_find_missing_required_docs_reports_only_absent_files(tmp_path: Path) -> None:
    first_document = REQUIRED_DOCUMENTS[0]
    document_path = tmp_path / first_document
    document_path.parent.mkdir(parents=True, exist_ok=True)
    document_path.write_text("present\n")

    missing = find_missing_required_docs(tmp_path)

    assert first_document not in missing
    assert set(missing) == set(REQUIRED_DOCUMENTS[1:])


def test_required_docs_include_the_implement_next_feature_skill() -> None:
    assert Path(".opencode/skills/implement-next-feature/SKILL.md") in REQUIRED_DOCUMENTS


def test_implement_next_feature_skill_reconciles_before_ready_selection() -> None:
    skill_path = Path(__file__).parents[3] / ".opencode/skills/implement-next-feature/SKILL.md"
    skill = skill_path.read_text(encoding="utf-8")

    assert "If no feature is `in_progress`, `implemented`, or `in_review`, inspect queued" in skill
    assert "work before selecting any `ready` feature:" in skill
    assert "If no feature is active or eligible" not in skill
