"""Validate the machine-readable feature registry."""

from __future__ import annotations

import argparse
import re
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import TypeGuard, cast

import yaml

FEATURE_ID_PATTERN = re.compile(r"FEAT-\d{3,}$")
ACCEPTANCE_CRITERION_ID_PATTERN = re.compile(r"AC-\d+$")
EVIDENCE_REQUIRED_STATUSES = {"implemented", "in_review", "complete"}
VALID_TEST_LEVELS = {"unit", "contract", "integration"}


def load_registry(path: Path) -> dict[str, object]:
    """Load a YAML feature registry as a string-keyed mapping."""
    try:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as error:
        raise ValueError(f"Could not read {path}: {error}") from error
    except yaml.YAMLError as error:
        raise ValueError(f"Could not parse {path}: {error}") from error

    if not isinstance(loaded, dict) or not all(isinstance(key, str) for key in loaded):
        raise ValueError(f"{path} must contain a top-level mapping")
    return cast(dict[str, object], loaded)


def validate_registry(registry: object) -> list[str]:
    """Return human-readable violations for a feature registry."""
    if not isinstance(registry, Mapping):
        return ["Registry must be a mapping"]

    errors: list[str] = []
    if registry.get("schema_version") != 1:
        errors.append("schema_version must be 1")
    if not _is_non_empty_string(registry.get("project")):
        errors.append("project must be a non-empty string")

    lifecycle = _mapping(registry.get("lifecycle"))
    feature_contract = _mapping(registry.get("feature_contract"))
    features = _list(registry.get("features"))

    if lifecycle is None:
        errors.append("lifecycle must be a mapping")
    if feature_contract is None:
        errors.append("feature_contract must be a mapping")
    if features is None:
        errors.append("features must be a list")
    if lifecycle is None or feature_contract is None or features is None:
        return errors

    statuses = _mapping(lifecycle.get("statuses"))
    priority_order = _string_list(lifecycle.get("priority_order"), "lifecycle.priority_order", errors)
    maximum_in_progress = lifecycle.get("maximum_in_progress")
    if not isinstance(maximum_in_progress, int) or isinstance(maximum_in_progress, bool) or maximum_in_progress < 1:
        errors.append("lifecycle.maximum_in_progress must be a positive integer")
    if statuses is None or not statuses:
        errors.append("lifecycle.statuses must be a non-empty mapping")
        statuses = {}
    if lifecycle.get("selection_status") not in statuses:
        errors.append("lifecycle.selection_status must name a defined status")

    required_fields = _string_list(feature_contract.get("required_fields"), "feature_contract.required_fields", errors)
    architecture_fields = _string_list(
        feature_contract.get("architecture_fields"), "feature_contract.architecture_fields", errors
    )
    verification_fields = _string_list(
        feature_contract.get("verification_fields"), "feature_contract.verification_fields", errors
    )

    if not _mapping(registry.get("selection")):
        errors.append("selection must be a mapping")
    if not _mapping(registry.get("automatic_merge")):
        errors.append("automatic_merge must be a mapping")

    parsed_features: list[dict[str, object]] = []
    feature_by_id: dict[str, dict[str, object]] = {}
    for index, raw_feature in enumerate(features):
        feature = _mapping(raw_feature)
        location = f"features[{index}]"
        if feature is None:
            errors.append(f"{location} must be a mapping")
            continue

        parsed_features.append(feature)
        feature_id = feature.get("id")
        label = feature_id if _is_non_empty_string(feature_id) else location
        _validate_feature(
            feature,
            str(label),
            required_fields,
            architecture_fields,
            verification_fields,
            statuses,
            priority_order,
            errors,
        )

        if _is_non_empty_string(feature_id):
            if feature_id in feature_by_id:
                errors.append(f"Feature ID {feature_id} is duplicated")
            else:
                feature_by_id[feature_id] = feature

    _validate_dependencies(parsed_features, feature_by_id, errors)
    _validate_active_feature_count(parsed_features, maximum_in_progress, errors)
    return errors


def _validate_feature(
    feature: dict[str, object],
    label: str,
    required_fields: list[str],
    architecture_fields: list[str],
    verification_fields: list[str],
    statuses: Mapping[str, object],
    priority_order: list[str],
    errors: list[str],
) -> None:
    for field in required_fields:
        if field not in feature:
            errors.append(f"{label} is missing required field {field}")

    feature_id = feature.get("id")
    if not _is_non_empty_string(feature_id) or not FEATURE_ID_PATTERN.fullmatch(feature_id):
        errors.append(f"{label} id must match FEAT-###")
    if not _is_non_empty_string(feature.get("title")):
        errors.append(f"{label} title must be a non-empty string")

    status = feature.get("status")
    if not _is_non_empty_string(status) or status not in statuses:
        errors.append(f"{label} status must name a defined lifecycle status")
    priority = feature.get("priority")
    if not _is_non_empty_string(priority) or priority not in priority_order:
        errors.append(f"{label} priority must be listed in lifecycle.priority_order")

    _validate_non_empty_string_list(feature.get("scope"), f"{label} scope", errors)
    _validate_non_empty_string_list(feature.get("non_goals"), f"{label} non_goals", errors)
    _validate_string_list(feature.get("depends_on"), f"{label} depends_on", errors)
    _validate_string_list(feature.get("research_decisions"), f"{label} research_decisions", errors)
    _validate_acceptance_criteria(feature, label, errors)
    _validate_architecture(feature.get("architecture"), label, architecture_fields, errors)
    _validate_verification(feature.get("verification"), label, verification_fields, errors)
    _validate_blocked_reason(feature, label, status, errors)
    _validate_completion_evidence(feature, label, status, errors)


def _validate_acceptance_criteria(feature: Mapping[str, object], label: str, errors: list[str]) -> None:
    criteria = _list(feature.get("acceptance_criteria"))
    if not criteria:
        errors.append(f"{label} acceptance_criteria must be a non-empty list")
        return

    criterion_ids: set[str] = set()
    for index, criterion in enumerate(criteria):
        mapped_criterion = _mapping(criterion)
        if mapped_criterion is None:
            errors.append(f"{label} acceptance_criteria[{index}] must be a mapping")
            continue
        criterion_id = mapped_criterion.get("id")
        if not _is_non_empty_string(criterion_id) or not ACCEPTANCE_CRITERION_ID_PATTERN.fullmatch(criterion_id):
            errors.append(f"{label} acceptance_criteria[{index}].id must match AC-#")
        elif criterion_id in criterion_ids:
            errors.append(f"{label} acceptance criterion {criterion_id} is duplicated")
        else:
            criterion_ids.add(criterion_id)
        if not _is_non_empty_string(mapped_criterion.get("description")):
            errors.append(f"{label} acceptance_criteria[{index}].description must be a non-empty string")


def _validate_architecture(architecture: object, label: str, architecture_fields: list[str], errors: list[str]) -> None:
    mapped_architecture = _mapping(architecture)
    if mapped_architecture is None:
        errors.append(f"{label} architecture must be a mapping")
        return
    for field in architecture_fields:
        if field not in mapped_architecture:
            errors.append(f"{label} architecture is missing required field {field}")
    _validate_non_empty_string_list(mapped_architecture.get("layers"), f"{label} architecture.layers", errors)
    _validate_string_list(mapped_architecture.get("ports"), f"{label} architecture.ports", errors)


def _validate_verification(verification: object, label: str, verification_fields: list[str], errors: list[str]) -> None:
    mapped_verification = _mapping(verification)
    if mapped_verification is None:
        errors.append(f"{label} verification must be a mapping")
        return
    for field in verification_fields:
        if field not in mapped_verification:
            errors.append(f"{label} verification is missing required field {field}")

    test_levels = _validate_string_list(
        mapped_verification.get("required_test_levels"), f"{label} verification.required_test_levels", errors
    )
    if test_levels is not None:
        for test_level in test_levels:
            if test_level not in VALID_TEST_LEVELS:
                errors.append(f"{label} has unsupported test level {test_level}")
    _validate_non_empty_string_list(
        mapped_verification.get("required_checks"), f"{label} verification.required_checks", errors
    )


def _validate_blocked_reason(feature: Mapping[str, object], label: str, status: object, errors: list[str]) -> None:
    blocked_reason = feature.get("blocked_reason")
    if status == "blocked" and not _is_non_empty_string(blocked_reason):
        errors.append(f"{label} is blocked but has no blocked_reason")
    if status != "blocked" and blocked_reason is not None:
        errors.append(f"{label} blocked_reason must be null unless status is blocked")


def _validate_completion_evidence(feature: Mapping[str, object], label: str, status: object, errors: list[str]) -> None:
    evidence_items = _list(feature.get("completion_evidence"))
    if evidence_items is None:
        errors.append(f"{label} completion_evidence must be a list")
        return

    criterion_ids = _criterion_ids(feature.get("acceptance_criteria"))
    evidence_by_criterion: set[str] = set()
    for index, evidence_item in enumerate(evidence_items):
        mapped_evidence = _mapping(evidence_item)
        if mapped_evidence is None:
            errors.append(f"{label} completion_evidence[{index}] must be a mapping")
            continue
        criterion_id = mapped_evidence.get("acceptance_criterion")
        if not _is_non_empty_string(criterion_id) or criterion_id not in criterion_ids:
            errors.append(f"{label} completion_evidence[{index}] has an unknown acceptance criterion")
            continue
        evidence = _validate_non_empty_string_list(
            mapped_evidence.get("evidence"), f"{label} completion_evidence[{index}].evidence", errors
        )
        if evidence is not None:
            evidence_by_criterion.add(criterion_id)

    if status in EVIDENCE_REQUIRED_STATUSES:
        for criterion_id in criterion_ids:
            if criterion_id not in evidence_by_criterion:
                errors.append(f"{label} is {status} but has no completion evidence for {criterion_id}")


def _validate_dependencies(
    features: list[dict[str, object]], feature_by_id: Mapping[str, dict[str, object]], errors: list[str]
) -> None:
    statuses_requiring_complete_dependencies = {"ready", "in_progress", "implemented", "in_review", "complete"}
    for feature in features:
        feature_id = feature.get("id")
        if not _is_non_empty_string(feature_id):
            continue
        dependencies = _list(feature.get("depends_on")) or []
        if feature_id in dependencies:
            errors.append(f"{feature_id} cannot depend on itself")
        for dependency_id in dependencies:
            if not _is_non_empty_string(dependency_id):
                continue
            dependency = feature_by_id.get(dependency_id)
            if dependency is None:
                errors.append(f"{feature_id} depends on unknown feature {dependency_id}")
                continue
            if (
                feature.get("status") in statuses_requiring_complete_dependencies
                and dependency.get("status") != "complete"
            ):
                errors.append(f"{feature_id} depends on {dependency_id}, which is not complete")


def _validate_active_feature_count(
    features: list[dict[str, object]], maximum_in_progress: object, errors: list[str]
) -> None:
    if not isinstance(maximum_in_progress, int) or isinstance(maximum_in_progress, bool):
        return
    active_feature_count = sum(feature.get("status") == "in_progress" for feature in features)
    if active_feature_count > maximum_in_progress:
        errors.append(
            f"{active_feature_count} features are in_progress, exceeding lifecycle.maximum_in_progress "
            f"of {maximum_in_progress}"
        )


def _criterion_ids(criteria: object) -> set[str]:
    criterion_ids: set[str] = set()
    for criterion in _list(criteria) or []:
        mapped_criterion = _mapping(criterion)
        criterion_id = mapped_criterion.get("id") if mapped_criterion is not None else None
        if _is_non_empty_string(criterion_id):
            criterion_ids.add(criterion_id)
    return criterion_ids


def _mapping(value: object) -> dict[str, object] | None:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        return None
    return value


def _list(value: object) -> list[object] | None:
    return value if isinstance(value, list) else None


def _string_list(value: object, label: str, errors: list[str]) -> list[str]:
    result = _validate_string_list(value, label, errors)
    return result or []


def _validate_string_list(value: object, label: str, errors: list[str]) -> list[str] | None:
    values = _list(value)
    if values is None:
        errors.append(f"{label} must be a list of non-empty strings")
        return None
    if not all(_is_non_empty_string(item) for item in values):
        errors.append(f"{label} must be a list of non-empty strings")
        return None
    return [str(item) for item in values]


def _validate_non_empty_string_list(value: object, label: str, errors: list[str]) -> list[str] | None:
    values = _validate_string_list(value, label, errors)
    if values == []:
        errors.append(f"{label} must not be empty")
        return None
    return values


def _is_non_empty_string(value: object) -> TypeGuard[str]:
    return isinstance(value, str) and bool(value.strip())


def main() -> int:
    """Run registry validation from the command line."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file", type=Path, default=Path("FEATURES.yaml"), help="Feature registry path")
    arguments = parser.parse_args()

    try:
        registry = load_registry(arguments.file)
    except ValueError as error:
        print(error, file=sys.stderr)
        return 1

    errors = validate_registry(registry)
    if errors:
        print(f"{arguments.file} is invalid:", file=sys.stderr)
        for validation_error in errors:
            print(f"- {validation_error}", file=sys.stderr)
        return 1

    print(f"{arguments.file} is valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
