"""Offline integrity gate for the immutable research/evaluation artifact bundle."""

import hashlib
import json
import re
from pathlib import Path, PurePosixPath
from typing import Any

from sentiment_system.adapters.outbound.market_data.cached_files import CachedCsvMarketData
from sentiment_system.application.use_cases.evaluate_predictions import EvaluationScope
from sentiment_system.application.use_cases.market_coverage import evaluation_protocol
from sentiment_system.domain.research import (
    EVALUATION_MANIFEST_VERSION,
    FINAL_CORPUS_VERSION,
    RESEARCH_SELECTION_VERSION,
    RESEARCH_TICKERS,
)


def safe_component(value: str) -> str:
    """Only a single named artifact version may select a directory."""
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", value):
        raise ValueError("unsafe artifact version")
    return value


def safe_file(root: Path, relative: str) -> Path:
    """Require regular contained files, rejecting symlinks in every component."""
    parts = PurePosixPath(relative)
    if not relative or parts.is_absolute() or ".." in parts.parts or parts.as_posix() != relative:
        raise ValueError("artifact path must be a normalized relative path")
    current = root
    if root.is_symlink():
        raise ValueError("artifact root must not be a symlink")
    for part in parts.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError("artifact path must not contain symlinks")
    if not current.is_file() or not current.resolve().is_relative_to(root.resolve()):
        raise ValueError(f"missing or unsafe artifact: {relative}")
    return current


def checksum(path: Path) -> str:
    """Hash original bytes, including large source artifacts without loading them."""
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def file_inventory(folder: Path) -> dict[str, str]:
    """Fingerprint every file in an immutable tree, including unrecorded additions."""
    if folder.is_symlink() or not folder.is_dir():
        raise ValueError(f"missing or linked artifact directory: {folder}")
    paths = tuple(sorted(folder.rglob("*")))
    if any(path.is_symlink() for path in paths):
        raise ValueError("artifact inventory must not contain symlinks")
    return {path.relative_to(folder).as_posix(): checksum(path) for path in paths if path.is_file()}


def read_json(path: Path) -> dict[str, Any]:
    """Read only a JSON object; executable deserialization is never used."""
    value = json.loads(path.read_bytes())
    if not isinstance(value, dict):
        raise ValueError(f"artifact must be a JSON object: {path}")
    return value


def load_evaluation_scope(root: Path, version: str = EVALUATION_MANIFEST_VERSION) -> EvaluationScope:
    """Validate linked source/price evidence before returning usable scope metadata."""
    try:
        return _load_scope(root, version)
    except (KeyError, TypeError, OSError) as error:
        raise ValueError(f"invalid evaluation bundle: {error}") from error


def _load_scope(root: Path, version: str) -> EvaluationScope:
    prefix = f"data/evaluation/{safe_component(version)}"
    manifest = read_json(safe_file(root, f"{prefix}/manifest.json"))
    if manifest["schema_version"] != 1 or manifest["manifest_version"] != version:
        raise ValueError("evaluation manifest schema/version mismatch")
    if manifest["evaluation_universe"] != list(RESEARCH_TICKERS) or manifest["protocol"] != evaluation_protocol():
        raise ValueError("evaluation universe/protocol differs from approved rules")
    market_tree = f"data/market_prices/{safe_component(manifest['market']['version'])}"
    if manifest["input_trees"] != [
        f"data/corpora/{FINAL_CORPUS_VERSION}",
        f"data/corpora/{RESEARCH_SELECTION_VERSION}",
        market_tree,
    ]:
        raise ValueError("evaluation bundle must pin complete source and market trees")
    for relative, expected in manifest["input_artifacts"].items():
        if checksum(safe_file(root, relative)) != expected:
            raise ValueError(f"evaluation input checksum mismatch: {relative}")
    for tree in manifest["input_trees"]:
        # Resolve through its manifest first to reject linked ancestors.
        folder = safe_file(
            root, f"{tree}/manifest.json" if "/corpora/" in tree else f"{tree}/market_prices.json"
        ).parent
        actual = {f"{tree}/{name}": digest for name, digest in file_inventory(folder).items()}
        expected_files = {
            name: digest for name, digest in manifest["input_artifacts"].items() if name.startswith(tree + "/")
        }
        if actual != expected_files:
            raise ValueError(f"evaluation input artifact set changed: {tree}")
    output = safe_file(root, f"{prefix}/manifest.json").parent
    actual_output = file_inventory(output)
    if set(actual_output) != {"manifest.json", *manifest["artifacts"]}:
        raise ValueError("evaluation bundle artifact set changed")
    for relative, expected in manifest["artifacts"].items():
        if checksum(safe_file(output, relative)) != expected:
            raise ValueError(f"evaluation output checksum mismatch: {relative}")
    for name, version_name, relative in (
        ("corpus", FINAL_CORPUS_VERSION, f"data/corpora/{FINAL_CORPUS_VERSION}/manifest.json"),
        ("selection", RESEARCH_SELECTION_VERSION, f"data/research_selection/{RESEARCH_SELECTION_VERSION}.json"),
        (
            "market",
            manifest["market"]["version"],
            f"data/market_prices/{safe_component(manifest['market']['version'])}/market_prices.json",
        ),
    ):
        link = manifest[name]
        if (
            link["version"] != version_name
            or link["path"] != relative
            or link["sha256"] != manifest["input_artifacts"].get(relative)
        ):
            raise ValueError(f"evaluation {name} reference is not pinned to verified input")
    corpus = read_json(safe_file(root, manifest["corpus"]["path"]))
    for field in ("corpus_window", "development_ends", "held_out_starts"):
        if manifest[field] != corpus[field]:
            raise ValueError("evaluation source boundaries changed")
    routes = {company["ticker"]: company["benchmark"] for company in corpus["companies"]}
    if manifest["company_benchmarks"] != routes:
        raise ValueError("evaluation benchmark routing differs from frozen sector evidence")
    market_path = safe_file(root, manifest["market"]["path"])
    market = read_json(market_path)
    if manifest["price_coverage"] != market["series"]:
        raise ValueError("evaluation price coverage differs from frozen snapshot")
    CachedCsvMarketData(market_path.parent)
    return EvaluationScope(FINAL_CORPUS_VERSION, manifest["market"]["version"], routes)
