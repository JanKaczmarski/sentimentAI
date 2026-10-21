"""Verify and canonically copy raw IR transcripts, preserving bytes and provenance.

Run: uv run python -m scripts.curate_earnings_calls --data-root /path/to/sentimentAI-data
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
from datetime import date
from io import StringIO
from pathlib import Path
from typing import Any

from scripts.download_earnings_calls import AcquisitionError, _atomic_json, inspect_pdf, official_url
from sentiment_system.domain.research import RESEARCH_TICKERS

_FIELDS = (
    "canonical_filename",
    "original_filename",
    "ticker",
    "fiscal_period",
    "published_at",
    "source",
    "document_type",
    "source_url",
    "sha256",
)


def contained_file(root: Path, relative: str) -> Path:
    """Resolve only regular local files inside the declared data tree."""
    path = root / relative
    if Path(relative).is_absolute() or ".." in Path(relative).parts or path.is_symlink():
        raise ValueError("source path must be a safe regular relative file")
    if not path.resolve().is_relative_to(root.resolve()) or not path.is_file():
        raise ValueError("source path is missing or escapes the data directory")
    return path


def curate_company(data_root: Path, ticker: str) -> dict[str, Any]:
    """Validate metadata/checksums/PDF content and keep renamed, unmodified copies."""
    if ticker not in RESEARCH_TICKERS:
        raise ValueError(f"unsupported research ticker: {ticker}")
    base = data_root / "data/company_communications"
    raw_root = base / "raw"
    raw_manifest = raw_root / ticker / "earnings_calls_manifest.json"
    payload = json.loads(raw_manifest.read_text(encoding="utf-8"))
    if payload.get("ticker") != ticker:
        raise ValueError("raw manifest ticker does not match")
    folder = base / "curated" / ticker
    folder.mkdir(parents=True, exist_ok=True)
    if folder.is_symlink() or not folder.resolve().is_relative_to(base.resolve()):
        raise ValueError("curated directory escapes data root")
    documents: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []
    seen: dict[tuple[str, str, str], dict[str, Any]] = {}
    review_path = base / "reviewed_dates.json"
    reviewed_dates = json.loads(review_path.read_text()) if review_path.exists() else {}
    for item in payload["documents"]:
        try:
            if item["status"] not in ("downloaded", "existing"):
                raise ValueError(item.get("error") or item.get("exclusion_reason") or "raw download not available")
            path = contained_file(raw_root, item["local_path"])
            content = path.read_bytes()
            checksum = hashlib.sha256(content).hexdigest()
            if checksum != item["sha256"]:
                raise ValueError("raw checksum mismatch")
            inspection = inspect_pdf(content)
            review = reviewed_dates.get(item["source_url"], {})
            if review:
                official_url(review["evidence_url"])
            published_at = item.get("published_at") or inspection["call_date"] or review.get("published_at")
            if not published_at:
                raise ValueError("publication date unavailable")
            published = date.fromisoformat(published_at).isoformat()
            period = item["fiscal_period"]
            if not re.fullmatch(r"FY\d{4}-Q[1-4]", period):
                raise ValueError("invalid fiscal period")
            if item.get("ticker") != ticker or item.get("document_type") != "earnings_call_transcript":
                raise ValueError("unexpected company or document type")
            official_url(item["source_url"])
            key = (period, published, checksum)
            if key in seen:
                seen[key]["raw_sources"].append(item)
                continue
            filename = f"{ticker}__{period}__{published}__investor_relations__earnings_call_transcript.pdf"
            destination = folder / filename
            if destination.exists() and hashlib.sha256(destination.read_bytes()).hexdigest() != checksum:
                filename = filename.removesuffix(".pdf") + f"__{checksum[:12]}.pdf"
                destination = folder / filename
            if destination.is_symlink():
                raise ValueError("curated destination must not be a symlink")
            if destination.exists():
                if destination.read_bytes() != content:
                    raise ValueError("curated content conflict; refusing to overwrite")
            else:
                destination.write_bytes(content)
            record = {
                **item,
                "canonical_filename": filename,
                "ticker": ticker,
                "published_at": published,
                "publication_date_basis": (
                    item.get("publication_date_basis")
                    if item.get("published_at")
                    else "pdf_header_review" if inspection["call_date"] else "reviewed_official_event"
                ),
                "date_review_evidence": (
                    review if not item.get("published_at") and not inspection["call_date"] else None
                ),
                "source": "investor_relations",
                "document_type": "earnings_call_transcript",
                "raw_path": path.relative_to(data_root).as_posix(),
                "curated_path": destination.relative_to(data_root).as_posix(),
                "review": "checksum, source metadata, readable earnings call and Q&A verified; bytes unchanged",
                "pdf_header_date": inspection["call_date"],
                "pages": inspection["pages"],
                "raw_sources": [item],
            }
            seen[key] = record
            documents.append(record)
        except (ValueError, AcquisitionError, OSError, KeyError) as exc:
            issues.append(
                {"fiscal_period": item.get("fiscal_period"), "source_url": item.get("source_url"), "reason": str(exc)}
            )
    documents.sort(key=lambda row: (row["fiscal_period"], row["published_at"], row["sha256"]))
    dates = sorted(row["published_at"] for row in documents)
    periods = sorted({row["fiscal_period"] for row in documents})
    archive_periods = set(payload.get("archive_fiscal_periods", []))
    expected: set[str] = set()
    if periods:
        first, last = periods[0], periods[-1]
        expected |= {
            f"FY{year}-Q{quarter}"
            for year in range(int(first[2:6]), int(last[2:6]) + 1)
            for quarter in range(1, 5)
            if first <= f"FY{year}-Q{quarter}" <= last
        }
    result = {
        "schema_version": 1,
        "ticker": ticker,
        "document_type": "earnings_call_transcript",
        "raw_manifest": raw_manifest.relative_to(data_root).as_posix(),
        "raw_manifest_sha256": hashlib.sha256(raw_manifest.read_bytes()).hexdigest(),
        "coverage": {
            "documents": len(documents),
            "fiscal_periods": periods,
            "publication_start": dates[0] if dates else None,
            "publication_end": dates[-1] if dates else None,
            "missing_fiscal_periods": sorted(expected - set(periods)),
            "archive_periods_without_curated_transcript": sorted(archive_periods - set(periods)),
        },
        "issues": issues,
        "documents": documents,
    }
    _atomic_json(folder / "manifest.json", result)
    output = StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=_FIELDS, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(documents)
    (folder / "manifest.csv").write_text(output.getvalue(), encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, default=os.environ.get("SENTIMENT_DATA_ROOT"))
    parser.add_argument("--tickers", nargs="+", choices=RESEARCH_TICKERS, default=RESEARCH_TICKERS)
    args = parser.parse_args()
    if args.data_root is None or not args.data_root.is_dir():
        parser.error("set SENTIMENT_DATA_ROOT or --data-root to the existing data repository")
    summaries = []
    for ticker in args.tickers:
        result = curate_company(args.data_root.resolve(), ticker)
        summary = {"ticker": ticker, **result["coverage"], "issues": result["issues"]}
        summaries.append(summary)
        print(json.dumps(summary), flush=True)
    _atomic_json(
        args.data_root / "data/company_communications/curated/coverage.json",
        {
            "schema_version": 1,
            "companies": [
                {"ticker": ticker, **item["coverage"], "issues": item["issues"]}
                for ticker in RESEARCH_TICKERS
                if (path := args.data_root / f"data/company_communications/curated/{ticker}/manifest.json").is_file()
                for item in [json.loads(path.read_text())]
            ],
        },
    )
    return int(any(item["issues"] for item in summaries))


if __name__ == "__main__":
    raise SystemExit(main())
