"""Export offline SEC extraction evidence for manual development review.

Run with uv run python -m scripts.review_sec_extraction --data-root PATH.
Default: 36 stratified records filed strictly before 2024-08-27; --all or
--limit 0 exports every eligible downloaded record. No models are invoked.
"""

from __future__ import annotations

import argparse
import hashlib
import inspect
import json
import os
import re
import sys
from collections import defaultdict
from collections.abc import Sequence
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup

from scripts.curate_earnings_calls import contained_file
from sentiment_system.application.use_cases.ingest_documents import _clean_content
from sentiment_system.application.use_cases.sec_content import SEC_PARSER_VERSION, select_sec_content
from sentiment_system.domain.research import RESEARCH_TICKERS

DEFAULT_BEFORE = date(2024, 8, 27)
_ACCESSION = re.compile(r"\d{10}-\d{2}-\d{6}")
_BINARY_SUFFIXES = {
    ".pdf",
    ".jpg",
    ".jpeg",
    ".gif",
    ".png",
    ".bmp",
    ".tif",
    ".tiff",
    ".ico",
    ".zip",
    ".gz",
    ".xls",
    ".xlsx",
    ".doc",
    ".docx",
    ".ppt",
    ".pptx",
    ".mp3",
    ".mp4",
}
_README = """# SEC extraction review bundle

Status: **manual review pending** (`reviewed=false`). This is diagnostic
development evidence; it does not update or certify the final corpus.
The script invokes no models and makes no automatic semantic pass claim.

## Review procedure

1. Read `review.json` for the exact inputs, manifest snapshots/hashes, selected
   accessions, parser version, warnings and actual extraction errors. An error
   makes the command exit nonzero; a warning is an observation requiring review.
2. For each record open `metadata.json`, then compare the original raw file
   (`inputs.data_root` + `raw_path`) with `cleaned.txt`. Verify hashes if the
   external raw repository has changed. `inputs/*.manifest.json` are exact
   manifest snapshots from this run.
3. Compare ALL `documents/*` readable source evidence, including excluded
   attachments, against the selected output. Source evidence uses an independent
   BeautifulSoup text flattening, removing only script/style/head elements.
   Repeated values, XBRL-wrapped text and hidden metadata are retained; evidence
   is not a visible-only browser rendering. The final text uses the production
   SEC/form-aware cleaner. Original raw HTML/SGML remains authoritative for
   structure and anything either text rendering may omit.
   Binary/unsupported bodies have no readable file; their decisions, reasons
   and body hashes remain in metadata. Inspect them in the original as needed.
   Excluded binaries are normal metadata; only selected binaries warn. Empty
   readable evidence is retained with a warning and does not abort the record.
4. Check earnings narrative, guidance, financial tables, row/column association,
   minus signs, units, and footnotes for omissions or corruption. Check that
   presentations and unrelated exhibits are excluded from selected earnings
   content; their readable evidence must still be available for comparison.
5. Distinguish a **selection omission** (relevant material exists in this raw
   submission but was excluded) from an **external incorporated source missing**
   (a reference points to material not embedded in the downloaded submission).
   Neither a reference nor a parser warning proves that external content was read.

## Findings and iteration

Agent findings are external manual annotations, not an automatic semantic
verdict from this script. Record reviewer/model identity, accession, parser
version, raw/cleaned hashes, concrete source/output quotations and locations,
severity, and one of: selection omission, cleaning loss, unrelated inclusion,
external incorporated source missing, or no issue observed. Leave generated
evidence intact; store findings separately. A reviewer owns any eventual review
completion decision; generated bundles always start unreviewed.

After parser changes rerun the same `--accessions` into a NEW output directory
and compare findings. For a new batch choose different accessions, optionally
from earlier years. Use `--limit 0` / `--all` for all eligible development records.
Never overwrite raw sources, a frozen corpus, or a previous review bundle.
"""


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _new_output(root: Path, output: Path) -> Path:
    """Claim a new directory exclusively, rejecting aliases and protected data."""
    output = output.absolute()
    if ".." in output.parts:
        raise ValueError("output must not contain parent traversal")
    for ancestor in (output, *output.parents):
        if ancestor.is_symlink():
            raise ValueError("output and its parents must not be symlinks")
        if (ancestor / "review.json").exists() or (ancestor / "manifest.json").exists():
            raise ValueError("output must not be inside a previous review or corpus")
    if output.is_relative_to(root / "data") and not output.is_relative_to(root / "data/extraction_reviews"):
        raise ValueError("output inside research data must be under data/extraction_reviews")
    if output == root / "data/extraction_reviews":
        raise ValueError("output must be a fresh subdirectory of data/extraction_reviews")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.mkdir(exist_ok=False)
    return output


def _sample(records: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    """Round-robin ticker/form quotas, then evenly spaced dates within each quota."""
    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for record in sorted(
        records, key=lambda row: (row["ticker"], row["form"], row["filed_at"], row["accession_number"])
    ):
        groups[(record["ticker"], record["form"])].append(record)
    quotas = dict.fromkeys(groups, 0)
    remaining = min(limit, len(records)) if limit else len(records)
    while remaining:
        for key, group in groups.items():
            if quotas[key] < len(group):
                quotas[key] += 1
                remaining -= 1
                if not remaining:
                    break
    selected = []
    for key, group in groups.items():
        count = quotas[key]
        if count == 1:
            selected.append(group[len(group) // 2])
        elif count > 1:
            selected.extend(group[index * (len(group) - 1) // (count - 1)] for index in range(count))
    return selected


def _load_records(
    root: Path,
    output: Path,
    tickers: tuple[str, ...],
    before: date,
    accessions: tuple[str, ...],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, str]]]:
    records: list[dict[str, Any]] = []
    manifests: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    (output / "inputs").mkdir()
    for ticker in sorted(tickers):
        relative = f"data/sec/history/{ticker}/manifest.json"
        try:
            raw = contained_file(root, relative).read_bytes()
            manifest = json.loads(raw)
            if manifest["ticker"] != ticker or not isinstance(manifest["documents"], list):
                raise ValueError("invalid SEC manifest ticker/documents")
            snapshot = f"inputs/{ticker}.manifest.json"
            (output / snapshot).write_bytes(raw)
            provenance = {
                "source_manifest": relative,
                "source_manifest_sha256": _sha(raw),
                "source_manifest_snapshot": snapshot,
            }
            manifests.append({"ticker": ticker, **provenance})
            seen = set()
            for record in manifest["documents"]:
                form = record["form"]
                if form not in {"10-K", "10-Q", "8-K"}:
                    continue
                if form == "8-K" and "2.02" not in record.get("form_items", []):
                    continue
                if record.get("status") not in {"downloaded", "existing"}:
                    continue
                if date.fromisoformat(record["filed_at"]) >= before:
                    continue
                accession = record["accession_number"]
                if not isinstance(accession, str) or not _ACCESSION.fullmatch(accession):
                    raise ValueError("unsafe accession number")
                if accession in seen:
                    raise ValueError(f"duplicate accession {accession}")
                seen.add(accession)
                if accessions and accession not in accessions:
                    continue
                records.append({**record, "ticker": ticker, **provenance})
        except Exception as exc:
            errors.append({"ticker": ticker, "source_manifest": relative, "error": f"{type(exc).__name__}: {exc}"})
    found = {record["accession_number"] for record in records}
    for missing in sorted(set(accessions) - found):
        errors.append({"accession_number": missing, "error": "requested accession not eligible or not downloaded"})
    return records, manifests, errors


def _unsupported_body(filename: str | None, document_type: str | None, content: str) -> bool:
    return (
        Path(filename or "").suffix.lower() in _BINARY_SUFFIXES
        or (document_type or "").upper() in {"GRAPHIC", "ZIP", "PDF"}
        or "\x00" in content
        or re.search(r"(?m)^begin [0-7]{3} ", content) is not None
    )


def _source_evidence(content: str) -> str:
    """Flatten source independently, retaining XBRL, hidden text and duplicates."""
    soup = BeautifulSoup(content, "html.parser")
    for tag in soup.find_all(["script", "style", "head"]):
        if tag.parent is not None:
            tag.decompose()
    return soup.get_text("\n", strip=True)


def _extract_record(root: Path, output: Path, record: dict[str, Any]) -> dict[str, Any]:
    folder = output / "records" / f"{record['ticker']}__{record['accession_number']}"
    folder.mkdir(parents=True)
    metadata: dict[str, Any] = {
        **record,
        "parser_version": SEC_PARSER_VERSION,
        "reviewed": False,
        "review_status": "manual_review_pending",
        "status": "error",
        "metadata_path": (folder / "metadata.json").relative_to(output).as_posix(),
        "observed_raw_sha256": None,
        "raw_path": record.get("raw_path"),
        "raw_sha256": record.get("raw_sha256"),
        "cleaned_path": None,
        "cleaned_sha256": None,
        "documents": [],
        "issues": [],
        "warnings": [],
        "error": None,
    }
    try:
        raw = contained_file(root, record["raw_path"]).read_bytes()
        metadata["observed_raw_sha256"] = _sha(raw)
        if metadata["observed_raw_sha256"] != record["raw_sha256"]:
            raise ValueError("raw SHA256 mismatch; extraction refused")
        try:
            text = raw.decode("utf-8")
            metadata["raw_encoding"] = "utf-8"
        except UnicodeDecodeError:
            text = raw.decode("cp1252")
            metadata["raw_encoding"] = "cp1252"
            metadata["warnings"].append("raw content decoded as cp1252, not UTF-8")
        extraction = select_sec_content(text, form=record["form"])
        metadata["extracted_form"] = extraction.form
        metadata["selected_content_sha256"] = _sha(extraction.content.encode("utf-8"))
        metadata["issues"] = list(extraction.issues)
        metadata["warnings"].extend(extraction.issues)
        if not extraction.documents:
            metadata["warnings"].append("no document decisions available; inspect original raw")
        documents_folder = folder / "documents"
        documents_folder.mkdir()
        for index, decision in enumerate(extraction.documents, 1):
            item = {
                "index": index,
                "document_type": decision.document_type,
                "filename": decision.filename,
                "description": decision.description,
                "selected": decision.selected,
                "reason": decision.reason,
                "content_sha256": _sha(decision.content.encode("utf-8")),
                "readable_path": None,
                "readable_sha256": None,
                "evidence_status": "unsupported_binary",
            }
            metadata["documents"].append(item)
            if _unsupported_body(decision.filename, decision.document_type, decision.content):
                if decision.selected:
                    metadata["warnings"].append(f"document {index}: selected binary/unsupported body; see original raw")
                continue
            readable = _source_evidence(decision.content).encode("utf-8")
            path = documents_folder / f"{index:03d}.txt"
            path.write_bytes(readable)
            item.update(
                {
                    "readable_path": path.relative_to(output).as_posix(),
                    "readable_sha256": _sha(readable),
                    "evidence_status": "readable" if readable.strip() else "empty_readable",
                }
            )
            if not readable.strip():
                metadata["warnings"].append(f"document {index}: readable evidence is empty; inspect original raw")
        cleaned = _clean_content(text, source="sec", form=record["form"]).encode("utf-8")
        path = folder / "cleaned.txt"
        path.write_bytes(cleaned)
        metadata.update(
            {
                "cleaned_path": path.relative_to(output).as_posix(),
                "cleaned_sha256": _sha(cleaned),
                "cleaned_bytes": len(cleaned),
                "status": "extracted",
            }
        )
        if not cleaned.strip():
            metadata["warnings"].append("selected cleaned output is empty; manual investigation required")
    except Exception as exc:
        # Preserve independent records and retain failures in both metadata and summary.
        metadata["error"] = f"{type(exc).__name__}: {exc}"
    _write_json(folder / "metadata.json", metadata)
    return metadata


def export_review(
    data_root: Path,
    output: Path,
    *,
    tickers: tuple[str, ...] = RESEARCH_TICKERS,
    limit: int = 36,
    before: date = DEFAULT_BEFORE,
    accessions: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Write a fresh diagnostic bundle. Per-record errors remain in review.json."""
    root = data_root.resolve()
    if not root.is_dir():
        raise ValueError("data root must be an existing directory")
    if limit < 0 or not tickers or set(tickers) - set(RESEARCH_TICKERS):
        raise ValueError("limit must be nonnegative and tickers must belong to the research universe")
    if any(not _ACCESSION.fullmatch(value) for value in accessions):
        raise ValueError("invalid accession number")
    output = _new_output(root, output)
    (output / "README.md").write_text(_README, encoding="utf-8")
    result: dict[str, Any] = {
        "schema_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "parser_version": SEC_PARSER_VERSION,
        "scope": "diagnostic development extraction; final corpus untouched",
        "implementation_sha256": {
            "review_script": _sha(Path(__file__).read_bytes()),
            "sec_selector": _sha(Path(inspect.getfile(select_sec_content)).read_bytes()),
            "text_cleaner": _sha(Path(inspect.getfile(_clean_content)).read_bytes()),
        },
        "reviewed": False,
        "review_status": "manual_review_pending",
        "inputs": {
            "data_root": str(root),
            "output": str(output),
            "tickers": sorted(set(tickers)),
            "limit": limit,
            "before": before.isoformat(),
            "before_exclusive": True,
            "accessions": sorted(set(accessions)),
            "sampling": "round-robin ticker/form quotas; evenly spaced filing-date ranks; median for quota one",
            "forms": ["10-K", "10-Q", "8-K Item 2.02"],
        },
        "source_manifests": [],
        "records": [],
        "errors": [],
        "warnings": [],
    }
    records, manifests, errors = _load_records(root, output, tuple(sorted(set(tickers))), before, accessions)
    result["source_manifests"] = manifests
    result["errors"] = errors
    result["eligible_count"] = len(records)
    selected = _sample(records, limit)
    result["selected_count"] = len(selected)
    if not selected:
        result["warnings"].append({"warning": "no eligible downloaded records selected"})
    _write_json(output / "review.json", result)
    for record in selected:
        metadata = _extract_record(root, output, record)
        identity = {key: metadata[key] for key in ("ticker", "accession_number", "form", "filed_at", "metadata_path")}
        result["records"].append(
            {
                **identity,
                "status": metadata["status"],
                "raw_path": metadata["raw_path"],
                "raw_sha256": metadata["raw_sha256"],
                "cleaned_sha256": metadata["cleaned_sha256"],
            }
        )
        if metadata["error"]:
            result["errors"].append({**identity, "error": metadata["error"]})
        result["warnings"].extend({**identity, "warning": warning} for warning in metadata["warnings"])
        _write_json(output / "review.json", result)
    return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, default=os.environ.get("SENTIMENT_DATA_ROOT"))
    parser.add_argument("--output", type=Path, help="new directory; default: data/extraction_reviews/<UTC timestamp>")
    parser.add_argument("--tickers", nargs="+", choices=RESEARCH_TICKERS, default=RESEARCH_TICKERS)
    parser.add_argument("--accessions", nargs="+", default=[])
    parser.add_argument(
        "--before", type=date.fromisoformat, default=DEFAULT_BEFORE, help="exclusive filing-date cutoff"
    )
    limits = parser.add_mutually_exclusive_group()
    limits.add_argument("--limit", type=int, default=36, help="stratified sample size (0 means all)")
    limits.add_argument("--all", action="store_true", help="all eligible downloaded records")
    args = parser.parse_args(argv)
    if args.data_root is None:
        parser.error("set SENTIMENT_DATA_ROOT or --data-root to the existing data repository")
    output = args.output or args.data_root / "data/extraction_reviews" / datetime.now(timezone.utc).strftime(
        "%Y%m%dT%H%M%S.%fZ"
    )
    try:
        result = export_review(
            args.data_root,
            output,
            tickers=tuple(args.tickers),
            limit=0 if args.all else args.limit,
            before=args.before,
            accessions=tuple(args.accessions),
        )
    except (ValueError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    for error in result["errors"]:
        print("ERROR: " + json.dumps(error), file=sys.stderr)
    for warning in result["warnings"]:
        print("WARNING: " + json.dumps(warning), file=sys.stderr)
    print(
        json.dumps(
            {
                "output": str(output.absolute()),
                "selected": result["selected_count"],
                "errors": len(result["errors"]),
                "warnings": len(result["warnings"]),
                "reviewed": False,
            }
        )
    )
    return int(bool(result["errors"]))


if __name__ == "__main__":
    raise SystemExit(main())
