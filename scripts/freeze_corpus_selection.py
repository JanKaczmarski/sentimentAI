"""Freeze source references and the derived research split from existing local history.

This records selection, not cleaned source material or completed FEAT-015 delivery.
Run: uv run python -m scripts.freeze_corpus_selection --data-root /path/to/sentimentAI-data
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import date
from pathlib import Path
from typing import Any

from scripts.curate_earnings_calls import contained_file
from sentiment_system.domain.research import RESEARCH_SELECTION_VERSION, RESEARCH_TICKERS, CorpusSplit


def build_selection(root: Path) -> dict[str, Any]:
    """Use supported cached records only; retain supersets without changing evaluation."""
    candidates: list[dict[str, Any]] = []
    inputs = []
    cached_dates = []
    for ticker in RESEARCH_TICKERS:
        for source, relative in (
            ("sec", f"data/sec/history/{ticker}/manifest.json"),
            ("investor_relations", f"data/company_communications/curated/{ticker}/manifest.json"),
        ):
            content = contained_file(root, relative).read_bytes()
            manifest = json.loads(content)
            if manifest["ticker"] != ticker:
                raise ValueError("source manifest company mismatch")
            if source == "sec" and (not manifest["discovery_complete"] or manifest["index_errors"]):
                raise ValueError(f"{ticker}: SEC discovery is incomplete")
            inputs.append({"path": relative, "sha256": hashlib.sha256(content).hexdigest()})
            for item in manifest["documents"]:
                if source == "sec":
                    if item["status"] not in {"existing", "downloaded"}:
                        raise ValueError(f"{ticker}: unresolved SEC download")
                    published = item["filed_at"]
                    cached_dates.append(published)
                    if item["form"] not in {"10-K", "10-Q"} and not (
                        item["form"] == "8-K" and "2.02" in item["form_items"]
                    ):
                        continue
                    raw_path, checksum = item["raw_path"], item["raw_sha256"]
                    source_id = item["accession_number"]
                    document_type = "earnings_release" if item["form"] == "8-K" else item["form"]
                else:
                    published = item["published_at"]
                    cached_dates.append(published)
                    if item["document_type"] != "earnings_call_transcript":
                        continue
                    raw_path, checksum = item["curated_path"], item["sha256"]
                    source_id, document_type = item["canonical_filename"], item["document_type"]
                candidates.append(
                    {
                        "company": ticker,
                        "source": source,
                        "source_id": source_id,
                        "document_type": document_type,
                        "published_at": date.fromisoformat(published).isoformat(),
                        "raw_path": raw_path,
                        "raw_sha256": checksum,
                        "source_manifest": relative,
                    }
                )
    split = CorpusSplit.from_publications(date.fromisoformat(item["published_at"]) for item in candidates)
    selected = sorted(
        (item for item in candidates if item["published_at"] >= split.start.isoformat()),
        key=lambda item: (item["published_at"], item["company"], item["source"], item["source_id"]),
    )
    for item in selected:
        content = contained_file(root, item["raw_path"]).read_bytes()
        if hashlib.sha256(content).hexdigest() != item["raw_sha256"]:
            raise ValueError(f"selected source checksum mismatch: {item['raw_path']}")
    coverage = []
    for ticker in RESEARCH_TICKERS:
        records = [item for item in selected if item["company"] == ticker]
        kinds = {item["document_type"] for item in records}
        if not {"10-K", "10-Q", "earnings_release", "earnings_call_transcript"} <= kinds:
            raise ValueError(f"{ticker}: missing a required source type in the selected window")
        coverage.append(
            {
                "ticker": ticker,
                "records": len(records),
                "first_publication": min(item["published_at"] for item in records),
                "last_publication": max(item["published_at"] for item in records),
                "by_document_type": {
                    kind: sum(item["document_type"] == kind for item in records) for kind in sorted(kinds)
                },
            }
        )
    return {
        "schema_version": 1,
        "manifest_version": RESEARCH_SELECTION_VERSION,
        "scope": "Frozen local source selection; cleaned final corpus and market-data coverage are separate FEAT-015 work.",
        "selection_rule": "SEC 10-K, 10-Q and 8-K Item 2.02 plus curated complete IR call transcripts; latest eligible publication, trailing five calendar years.",
        "latest_cached_publication": max(cached_dates),
        "corpus_window": {"start": split.start.isoformat(), "end": split.cutoff.isoformat()},
        "development_ends": split.development_ends.isoformat(),
        "held_out_starts": split.held_out_starts.isoformat(),
        "evaluation_universe": list(RESEARCH_TICKERS),
        "inputs": inputs,
        "coverage": coverage,
        "records": selected,
    }


def freeze_selection(root: Path) -> Path:
    payload = build_selection(root)
    destination = root / f"data/research_selection/{RESEARCH_SELECTION_VERSION}.json"
    if not destination.parent.resolve().is_relative_to(root.resolve()) or destination.is_symlink():
        raise ValueError("selection path escapes data root")
    encoded = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode()
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        if destination.read_bytes() != encoded:
            raise ValueError("selection is immutable; changed inputs require a new version and decision")
    else:
        # Exclusive creation: a rerun can never silently replace a frozen selection.
        with destination.open("xb") as handle:
            handle.write(encoded)
    return destination


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, default=os.environ.get("SENTIMENT_DATA_ROOT"))
    args = parser.parse_args()
    if args.data_root is None or not args.data_root.is_dir():
        parser.error("set SENTIMENT_DATA_ROOT or --data-root to the existing data repository")
    path = freeze_selection(args.data_root)
    payload = json.loads(path.read_bytes())
    print(
        json.dumps(
            {key: payload[key] for key in ("corpus_window", "development_ends", "held_out_starts", "coverage")},
            indent=2,
        )
    )
    print(path)


if __name__ == "__main__":
    main()
