"""Report the feature that an implementation agent should resume or select."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Mapping
from pathlib import Path

if __package__ is None:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.validate_features import load_registry, validate_registry


def select_feature(registry: Mapping[str, object]) -> tuple[str | None, dict[str, object] | None]:
    """Return the active feature, or the highest-priority eligible ready feature."""
    features = registry.get("features")
    if not isinstance(features, list):
        return None, None

    mapped_features = [feature for feature in features if isinstance(feature, dict)]
    active_features = [feature for feature in mapped_features if feature.get("status") == "in_progress"]
    if len(active_features) == 1:
        return "resume", active_features[0]
    if active_features:
        return None, None

    implemented_features = [feature for feature in mapped_features if feature.get("status") == "implemented"]
    if implemented_features:
        return "needs_review", implemented_features[0]

    awaiting_review = [feature for feature in mapped_features if feature.get("status") == "in_review"]
    if awaiting_review:
        return "awaiting_review", awaiting_review[0]

    lifecycle = registry.get("lifecycle")
    if not isinstance(lifecycle, dict):
        return None, None
    selection_status = lifecycle.get("selection_status")
    priority_order = lifecycle.get("priority_order")
    if not isinstance(selection_status, str) or not isinstance(priority_order, list):
        return None, None

    priorities = {priority: index for index, priority in enumerate(priority_order) if isinstance(priority, str)}
    features_by_id = {
        feature_id: feature for feature in mapped_features if isinstance((feature_id := feature.get("id")), str)
    }
    eligible_features = [
        feature
        for feature in mapped_features
        if feature.get("status") == selection_status and _dependencies_are_complete(feature, features_by_id)
    ]
    if not eligible_features:
        return None, None

    eligible_features.sort(
        key=lambda feature: (
            _priority_index(feature.get("priority"), priorities),
            str(feature.get("id")),
        )
    )
    return "next", eligible_features[0]


def _dependencies_are_complete(feature: Mapping[str, object], features_by_id: Mapping[str, dict[str, object]]) -> bool:
    dependencies = feature.get("depends_on")
    if not isinstance(dependencies, list):
        return False
    return all(
        isinstance(dependency_id, str) and features_by_id.get(dependency_id, {}).get("status") == "complete"
        for dependency_id in dependencies
    )


def _priority_index(priority: object, priorities: Mapping[str, int]) -> int:
    """Return a sortable priority rank for a validated feature."""
    return priorities.get(priority, len(priorities)) if isinstance(priority, str) else len(priorities)


def main() -> int:
    """Run feature-status selection from the command line."""
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
        print(f"{arguments.file} is invalid; run scripts/validate_features.py for details", file=sys.stderr)
        return 1

    selection_type, feature = select_feature(registry)
    if feature is None:
        print("No feature is currently resumable or eligible for selection")
        return 0

    if selection_type == "needs_review":
        print(f"Create or update pull request for feature: {feature['id']} - {feature['title']}")
        return 0

    if selection_type == "awaiting_review":
        print(f"Wait for feature review or merge: {feature['id']} - {feature['title']}")
        return 0

    feature_id = feature["id"]
    title = feature["title"]
    action = "Resume" if selection_type == "resume" else "Next"
    print(f"{action} feature: {feature_id} - {title}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
