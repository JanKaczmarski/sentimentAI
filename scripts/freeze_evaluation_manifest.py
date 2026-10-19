"""Freeze/verify source reconciliation and market coverage in sentimentAI-data."""

from __future__ import annotations

import argparse
import hashlib
import inspect
import json
import os
import shutil
import tempfile
from datetime import date
from pathlib import Path
from typing import Any

from scripts import acquire_corpus, download_nasdaq_historical
from sentiment_system.adapters.outbound.market_data import cached_files, evaluation_bundle
from sentiment_system.adapters.outbound.market_data.cached_files import CachedCsvMarketData
from sentiment_system.adapters.outbound.market_data.evaluation_bundle import (
    checksum,
    file_inventory,
    load_evaluation_scope,
    read_json,
    safe_component,
    safe_file,
)
from sentiment_system.adapters.outbound.sources.sector_metadata import load_sector_review
from sentiment_system.application.use_cases import market_coverage
from sentiment_system.application.use_cases.market_coverage import (
    CoverageSource,
    build_market_coverage,
    evaluation_protocol,
)
from sentiment_system.domain.research import (
    EVALUATION_MANIFEST_VERSION,
    FINAL_CORPUS_VERSION,
    RESEARCH_SELECTION_VERSION,
    RESEARCH_TICKERS,
)


def _encode(value: object) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()


def _source_reconciliation(root: Path) -> tuple[dict[str, Any], dict[str, Any], dict[str, str]]:
    corpus = root / f"data/corpora/{FINAL_CORPUS_VERSION}"
    manifest = read_json(safe_file(root, f"data/corpora/{FINAL_CORPUS_VERSION}/manifest.json"))
    lineage = manifest["cleaning_provenance"]
    selection_path = safe_file(root, f"data/research_selection/{RESEARCH_SELECTION_VERSION}.json")
    acquire_corpus.verify_published_corpus(
        root,
        corpus,
        selection_path=selection_path,
        review_paths=tuple(safe_file(root, item["source_path"]) for item in lineage["reviews"]),
        findings_path=safe_file(root, lineage["findings"]["source_path"]),
    )
    selection = read_json(selection_path)
    keys = ("company", "source", "source_id", "document_type", "published_at", "raw_sha256")
    selected = {tuple(row[key] for key in keys) for row in selection["records"]}
    included = {tuple(row[key] for key in keys) for row in manifest["records"]}
    if selected != included or len(selected) != len(selection["records"]) or len(included) != len(manifest["records"]):
        raise ValueError("corrected corpus membership differs from frozen selection")
    if (
        selection["evaluation_universe"] != list(RESEARCH_TICKERS)
        or selection["manifest_version"] != RESEARCH_SELECTION_VERSION
    ):
        raise ValueError("frozen selection universe/version mismatch")
    for field in ("corpus_window", "development_ends", "held_out_starts"):
        if selection[field] != manifest[field]:
            raise ValueError("frozen selection boundaries differ from corrected corpus")
    previous = read_json(safe_file(corpus, lineage["predecessor"]["path"]))
    original = {row["record_id"]: row for row in previous["records"]}
    references = []
    for row in manifest["records"]:
        references.append(
            {
                "record_id": row["record_id"],
                **{key: row[key] for key in keys},
                "raw_path": row["raw_path"],
                "cleaned_path": row["cleaned_path"],
                "previous_cleaned_sha256": original[row["record_id"]]["cleaned_sha256"],
                "cleaned_sha256": row["cleaned_sha256"],
                "parser_version": row["parser_version"],
                "canonical_for_scoring": row["canonical_for_scoring"],
                "content_group_id": row["content_group_id"],
            }
        )
    reconciliation = {
        "source_records": len(references),
        "selection_membership_exact": True,
        "source_metadata_and_raw_bytes_preserved": True,
        "predecessor_unchanged": True,
        "publication": read_json(safe_file(corpus, "publication.json")),
        "records": references,
    }
    external = [selection_path, *(safe_file(root, row["raw_path"]) for row in selection["records"])]
    external.extend(safe_file(root, item["path"]) for item in selection["inputs"])
    external.extend(safe_file(root, item["source_path"]) for item in lineage["reviews"])
    external.append(safe_file(root, lineage["findings"]["source_path"]))
    # Also retain the original downloaded/reviewed sector bundle, not just its copy.
    _, sector_files = load_sector_review(root, manifest["sector_review_path"], manifest["sector_review_sha256"])
    external.extend(safe_file(root, relative) for relative in sector_files)
    return manifest, reconciliation, {path.relative_to(root).as_posix(): checksum(path) for path in external}


def _build(root: Path, market_snapshot: str) -> tuple[dict[str, Any], dict[str, bytes]]:
    market_snapshot = safe_component(market_snapshot)
    source, reconciliation, inputs = _source_reconciliation(root)
    market_relative = f"data/market_prices/{market_snapshot}"
    market_folder = safe_file(root, f"{market_relative}/market_prices.json").parent
    download_nasdaq_historical.verify_snapshot(market_folder)
    market = read_json(market_folder / "market_prices.json")
    routes = {company["ticker"]: company["benchmark"] for company in source["companies"]}
    expected_symbols = {(symbol, "stocks") for symbol in RESEARCH_TICKERS} | {
        (symbol, "etf") for symbol in (*set(routes.values()), "SPY")
    }
    if {(row["symbol"], row["asset_class"]) for row in market["series"]} != expected_symbols:
        raise ValueError("market snapshot must contain exactly the six research stocks and required ETFs")
    start = source["corpus_window"]["start"]
    for row in market["series"]:
        if row["requested_start"] != start:
            raise ValueError("market coverage does not start at the frozen source window")
        if row["symbol"] in RESEARCH_TICKERS:
            earliest = min(r["published_at"] for r in source["records"] if r["company"] == row["symbol"])
            if row["first_trading_date"] > earliest:
                raise ValueError("market coverage omits the beginning of source publications")
        retrieved = date.fromisoformat(row["retrieved_at"][:10])
        if date.fromisoformat(row["requested_end"]) >= retrieved:
            raise ValueError("snapshot boundary must precede retrieval day to exclude incomplete sessions")
    if len({row["requested_end"] for row in market["series"]}) != 1:
        raise ValueError("market series must share one requested snapshot boundary")
    trees = [f"data/corpora/{FINAL_CORPUS_VERSION}", f"data/corpora/{RESEARCH_SELECTION_VERSION}", market_relative]
    for tree in trees:
        inputs.update({f"{tree}/{name}": digest for name, digest in file_inventory(root / tree).items()})
    coverage = build_market_coverage(
        CachedCsvMarketData(market_folder),
        sources=tuple(
            CoverageSource(row["record_id"], row["company"], date.fromisoformat(row["published_at"]))
            for row in source["records"]
        ),
        company_benchmarks=routes,
        window_start=date.fromisoformat(start),
        cutoff=date.fromisoformat(source["corpus_window"]["end"]),
        development_ends=date.fromisoformat(source["development_ends"]),
    )
    artifacts = {"reconciliation.json": _encode(reconciliation), "coverage.json": _encode(coverage)}
    for module in (acquire_corpus, download_nasdaq_historical, cached_files, evaluation_bundle, market_coverage):
        path = Path(inspect.getfile(module))
        artifacts[f"implementation/{path.name}"] = path.read_bytes()
    artifacts["implementation/freeze_evaluation_manifest.py"] = Path(__file__).read_bytes()

    def link(relative: str, version: str) -> dict[str, str]:
        return {"path": relative, "sha256": inputs[relative], "version": version}

    manifest = {
        "schema_version": 1,
        "manifest_version": EVALUATION_MANIFEST_VERSION,
        "scope": "Frozen source and price artifacts with coverage; no prediction results or sampling schedule.",
        "selection": link(f"data/research_selection/{RESEARCH_SELECTION_VERSION}.json", RESEARCH_SELECTION_VERSION),
        "corpus": link(f"data/corpora/{FINAL_CORPUS_VERSION}/manifest.json", FINAL_CORPUS_VERSION),
        "market": link(f"{market_relative}/market_prices.json", market_snapshot),
        **{field: source[field] for field in ("corpus_window", "development_ends", "held_out_starts")},
        "evaluation_universe": list(RESEARCH_TICKERS),
        "company_benchmarks": routes,
        "snapshot_requested_start": start,
        "snapshot_requested_end": market["series"][0]["requested_end"],
        "protocol": evaluation_protocol(),
        "input_artifacts": inputs,
        "input_trees": trees,
        "price_coverage": market["series"],
        "artifacts": {relative: hashlib.sha256(content).hexdigest() for relative, content in artifacts.items()},
    }
    return manifest, artifacts


def verify_evaluation_manifest(root: Path, *, market_snapshot: str | None = None) -> Path:
    """Verify pinned artifacts, replay responses, and recompute coverage offline."""
    load_evaluation_scope(root)
    output = root / f"data/evaluation/{EVALUATION_MANIFEST_VERSION}"
    manifest = read_json(output / "manifest.json")
    frozen_market = manifest["market"]["version"]
    if market_snapshot is not None and market_snapshot != frozen_market:
        raise ValueError("requested market snapshot differs from immutable evaluation manifest")
    expected, artifacts = _build(root, frozen_market)
    # Historical creation fingerprints remain valid after today's code evolves.
    expected["artifacts"] = manifest["artifacts"]
    if _encode(expected) != (output / "manifest.json").read_bytes():
        raise ValueError("immutable evaluation manifest differs from verified inputs")
    for relative in ("coverage.json", "reconciliation.json"):
        if artifacts[relative] != (output / relative).read_bytes():
            raise ValueError(f"immutable evaluation derivation mismatch: {relative}")
    return output


def freeze_evaluation_manifest(root: Path, *, market_snapshot: str) -> Path:
    """Publish once; reruns validate existing evidence without acquisition."""
    output = root / f"data/evaluation/{EVALUATION_MANIFEST_VERSION}"
    if output.exists() or output.is_symlink():
        return verify_evaluation_manifest(root, market_snapshot=market_snapshot)
    manifest, artifacts = _build(root, market_snapshot)
    parent = output.parent
    if not parent.resolve().is_relative_to(root.resolve()) or parent.is_symlink():
        raise ValueError("evaluation output escapes data root")
    parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{output.name}-", dir=parent))
    try:
        for relative, content in artifacts.items():
            path = staging / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        (staging / "manifest.json").write_bytes(_encode(manifest))
        staging.rename(output)
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    load_evaluation_scope(root)
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, default=os.environ.get("SENTIMENT_DATA_ROOT"))
    parser.add_argument("--market-snapshot", default=None)
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    if args.data_root is None or not args.data_root.is_dir():
        parser.error("set SENTIMENT_DATA_ROOT or --data-root to the existing research-data repository")
    if args.verify:
        output = verify_evaluation_manifest(args.data_root, market_snapshot=args.market_snapshot)
    else:
        if args.market_snapshot is None:
            parser.error("--market-snapshot is required when publishing")
        output = freeze_evaluation_manifest(args.data_root, market_snapshot=args.market_snapshot)
    print(f"Verified evaluation bundle: {output}")
    print(f"Manifest SHA-256: {checksum(output / 'manifest.json')}")


if __name__ == "__main__":
    main()
