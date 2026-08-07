"""Verify that the project-governance documents required by agents exist."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REQUIRED_DOCUMENTS = (
    Path("AGENTS.md"),
    Path("ARCHITECTURE.md"),
    Path("THESIS_DECISIONS.md"),
    Path("DEVELOPMENT_RULES.md"),
    Path("IMPLEMENTATION_WORKFLOW.md"),
    Path("FEATURES.yaml"),
    Path("templates/feature.md"),
    Path("scripts/reconcile_feature_readiness.py"),
    Path(".opencode/skills/implement-next-feature/SKILL.md"),
)


def find_missing_required_docs(root: Path) -> list[Path]:
    """Return required documentation paths missing beneath ``root``."""
    return [document for document in REQUIRED_DOCUMENTS if not (root / document).is_file()]


def main() -> int:
    """Run required-document checks from the command line."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("."), help="Repository root")
    arguments = parser.parse_args()

    missing_documents = find_missing_required_docs(arguments.root)
    if missing_documents:
        print("Missing required project documents:", file=sys.stderr)
        for document in missing_documents:
            print(f"- {document}", file=sys.stderr)
        return 1

    print("All required project documents are present")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
