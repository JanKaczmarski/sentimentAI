"""Promote dependency-satisfied queued features to ready."""

from __future__ import annotations

import argparse
import re
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

if __package__ is None:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.validate_features import load_registry, validate_registry

FEATURE_ID_LINE = re.compile(
    r"^(?P<indent>\s*)-\s+id:\s+[\"']?(?P<id>FEAT-\d{3,})[\"']?\s*(?:#.*)?(?P<newline>\r?\n?)$"
)


def queued_features_ready_for_promotion(registry: Mapping[str, object]) -> list[dict[str, object]]:
    """Return queued features whose dependencies are all complete."""
    features = registry.get("features")
    lifecycle = registry.get("lifecycle")
    if not isinstance(features, list) or not isinstance(lifecycle, dict):
        return []

    priority_order = lifecycle.get("priority_order")
    if not isinstance(priority_order, list):
        return []
    priorities = {priority: index for index, priority in enumerate(priority_order) if isinstance(priority, str)}
    mapped_features = [feature for feature in features if isinstance(feature, dict)]
    features_by_id = {
        feature_id: feature for feature in mapped_features if isinstance((feature_id := feature.get("id")), str)
    }
    promotable = [
        feature
        for feature in mapped_features
        if feature.get("status") == "queued" and _dependencies_are_complete(feature, features_by_id)
    ]
    promotable.sort(
        key=lambda feature: (
            _priority_index(feature.get("priority"), priorities),
            str(feature.get("id")),
        )
    )
    return promotable


def promote_queued_features(path: Path, feature_ids: Sequence[str]) -> None:
    """Surgically replace queued statuses while preserving registry comments."""
    target_ids = set(feature_ids)
    if not target_ids:
        return

    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    promoted_ids: set[str] = set()
    current_feature_id: str | None = None
    current_feature_indent: str | None = None

    for index, line in enumerate(lines):
        feature_match = FEATURE_ID_LINE.fullmatch(line)
        if feature_match is not None:
            current_feature_id = feature_match["id"]
            current_feature_indent = feature_match["indent"]
            continue
        if current_feature_id not in target_ids or current_feature_indent is None:
            continue

        status_pattern = re.compile(
            rf"^(?P<prefix>{re.escape(current_feature_indent)}  status:\s*)queued"
            rf"(?P<suffix>\s*(?:#.*)?)(?P<newline>\r?\n?)$"
        )
        status_match = status_pattern.fullmatch(line)
        if status_match is not None:
            lines[index] = f"{status_match['prefix']}ready{status_match['suffix']}{status_match['newline']}"
            promoted_ids.add(current_feature_id)

    missing_ids = target_ids - promoted_ids
    if missing_ids:
        missing = ", ".join(sorted(missing_ids))
        raise ValueError(f"Could not locate a canonical queued status for: {missing}")

    path.write_text("".join(lines), encoding="utf-8")


def _dependencies_are_complete(feature: Mapping[str, object], features_by_id: Mapping[str, dict[str, object]]) -> bool:
    dependencies = feature.get("depends_on")
    if not isinstance(dependencies, list):
        return False
    return all(
        isinstance(dependency_id, str) and features_by_id.get(dependency_id, {}).get("status") == "complete"
        for dependency_id in dependencies
    )


def _priority_index(priority: object, priorities: Mapping[str, int]) -> int:
    return priorities.get(priority, len(priorities)) if isinstance(priority, str) else len(priorities)


def main() -> int:
    """Report or apply queued-to-ready feature promotions."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file", type=Path, default=Path("FEATURES.yaml"), help="Feature registry path")
    parser.add_argument("--apply", action="store_true", help="Apply eligible queued-to-ready promotions")
    arguments = parser.parse_args()

    try:
        registry = load_registry(arguments.file)
    except ValueError as error:
        print(error, file=sys.stderr)
        return 1

    errors = validate_registry(registry)
    if errors:
        print(f"{arguments.file} is invalid; run scripts.validate_features for details", file=sys.stderr)
        return 1

    features = queued_features_ready_for_promotion(registry)
    feature_ids = [str(feature["id"]) for feature in features]
    if not feature_ids:
        print("No queued features are ready for promotion")
        return 0
    if not arguments.apply:
        print(f"Queued features ready for promotion: {', '.join(feature_ids)}")
        return 0

    try:
        promote_queued_features(arguments.file, feature_ids)
        updated_registry = load_registry(arguments.file)
    except ValueError as error:
        print(error, file=sys.stderr)
        return 1

    updated_errors = validate_registry(updated_registry)
    if updated_errors:
        print(f"Promotion left {arguments.file} invalid:", file=sys.stderr)
        for validation_error in updated_errors:
            print(f"- {validation_error}", file=sys.stderr)
        return 1

    print(f"Promoted queued features: {', '.join(feature_ids)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
