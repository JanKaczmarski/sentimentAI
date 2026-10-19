"""Verify and inventory actual curated IR and downloaded SEC research history."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from scripts.curate_earnings_calls import contained_file
from scripts.download_earnings_calls import _atomic_json
from sentiment_system.domain.research import RESEARCH_TICKERS


def build_inventory(root: Path, tickers: tuple[str, ...] = RESEARCH_TICKERS) -> dict[str, Any]:
    """Independently verify each manifest reference, not just successful statuses."""
    companies = []
    errors: list[dict[str, str]] = []
    verified = 0
    total_bytes = 0

    def verify(relative: str, checksum: str) -> None:
        nonlocal verified, total_bytes
        try:
            path = contained_file(root, relative)
            digest = hashlib.sha256()
            with path.open("rb") as handle:
                while chunk := handle.read(1024 * 1024):
                    digest.update(chunk)
            if digest.hexdigest() != checksum:
                raise ValueError("checksum mismatch")
            verified += 1
            total_bytes += path.stat().st_size
        except (ValueError, OSError) as exc:
            errors.append({"path": relative, "error": str(exc)})

    for ticker in tickers:
        ir_path = root / f"data/company_communications/curated/{ticker}/manifest.json"
        sec_path = root / f"data/sec/history/{ticker}/manifest.json"
        if not ir_path.is_file() or not sec_path.is_file():
            errors.append({"ticker": ticker, "error": "IR or SEC manifest unavailable"})
            continue
        ir, sec = json.loads(ir_path.read_text()), json.loads(sec_path.read_text())
        for item in ir["documents"]:
            verify(item["raw_path"], item["sha256"])
            verify(item["curated_path"], item["sha256"])
        for item in sec["indexes"]:
            verify(item["local_path"], item["sha256"])
        for item in sec["documents"]:
            if item["status"] in ("downloaded", "existing"):
                verify(item["raw_path"], item["raw_sha256"])
        companies.append(
            {
                "ticker": ticker,
                "ir_manifest": ir_path.relative_to(root).as_posix(),
                "ir": {
                    **ir["coverage"],
                    "issues": ir["issues"],
                    "unique_fiscal_periods": len(ir["coverage"]["fiscal_periods"]),
                },
                "sec_manifest": sec_path.relative_to(root).as_posix(),
                "sec": {
                    "requested_window": sec["requested_window"],
                    "ciks": sec["ciks"],
                    "discovery_complete": sec["discovery_complete"],
                    "index_errors": sec["index_errors"],
                    **sec["coverage"],
                },
            }
        )
    return {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "universe": list(tickers),
        "scope": "historical acquisition superset; not an immutable evaluation split",
        "companies": companies,
        "verification": {"files_verified": verified, "bytes_verified": total_bytes, "errors": errors},
    }


def markdown(inventory: dict[str, Any]) -> str:
    lines = [
        "# Research History Inventory",
        "",
        f"Verified at: {inventory['generated_at']}",
        "",
        "Core companies: **META, CRM, V, DIS, WHR, T**.",
        "",
        "All counts below come from local manifests with every referenced source file SHA-256 checked.",
        "SEC coverage is publication-date coverage, starting January 1 of the first available IR publication year.",
        "10-K/10-Q are primary HTML filings; 8-K are complete submissions with exhibits. Amendments are excluded.",
        "Item 2.02 counts are a **subset** of all 8-K, not additional files.",
        "",
        "| Company | IR PDFs | IR publication span | SEC requested span | 10-K | 10-Q | All 8-K | Item 2.02 | Missing SEC |",
        "|---|---:|---|---|---:|---:|---:|---:|---:|",
    ]
    for item in inventory["companies"]:
        ir, sec = item["ir"], item["sec"]
        counts = [str(sec["by_form"][form]["downloaded"]) for form in ("10-K", "10-Q", "8-K", "8-K:2.02")]
        window = sec["requested_window"]
        lines.append(
            f"| {item['ticker']} | {ir['documents']} | {ir['publication_start']} – {ir['publication_end']} | "
            f"{window['start']} – {window['end']} | " + " | ".join(counts) + f" | {len(sec['missing'])} |"
        )
    lines += ["", "## Source spans and gaps", ""]
    for item in inventory["companies"]:
        ir, sec = item["ir"], item["sec"]
        periods = ir["fiscal_periods"]
        lines += [
            f"### {item['ticker']}",
            "",
            f"- IR fiscal span: **{periods[0]} – {periods[-1]}**; {ir['unique_fiscal_periods']} distinct periods.",
            "- Missing IR quarters within that span: " + (", ".join(ir["missing_fiscal_periods"]) or "none") + ".",
            f"- Raw candidate issues retained: {len(ir['issues'])}; these may be rejected alternates, not missing quarters.",
            "- SEC CIKs: " + ", ".join(sec["ciks"]) + ".",
            f"- SEC index reconciliation complete: {sec['complete_against_indexes']}; index errors: {len(sec['index_errors'])}.",
            f"- Full provenance: `{item['ir_manifest']}` and `{item['sec_manifest']}`.",
            "",
            "| SEC category | Saved | First filing | Last filing |",
            "|---|---:|---|---|",
        ]
        for form, values in sec["by_form"].items():
            lines.append(
                f"| {form} | {values['downloaded']} | {values['publication_start']} | {values['publication_end']} |"
            )
        lines += ["", "| Filing year | 10-K | 10-Q | All 8-K | Item 2.02 |", "|---|---:|---:|---:|---:|"]
        years = sec["by_form"]["10-K"]["by_year"]
        for year in years:
            counts = [
                str(sec["by_form"][form]["by_year"][year]["downloaded"]) for form in ("10-K", "10-Q", "8-K", "8-K:2.02")
            ]
            lines.append(f"| {year} | " + " | ".join(counts) + " |")
        if ir["archive_periods_without_curated_transcript"]:
            lines += [
                "",
                "Other archive periods without a curated transcript (may precede the transcript archive or be future calls):",
                ", ".join(ir["archive_periods_without_curated_transcript"]) + ".",
            ]
        for missing in sec["missing"]:
            lines.append(
                f"- Missing SEC: {missing['form']} {missing['filed_at']} {missing['accession_number']} — {missing['source_url']} ({missing['reason']})"
            )
        for error in sec["index_errors"]:
            lines.append(f"- Index error: {error}")
        lines.append("")
    verification = inventory["verification"]
    lines += [
        "## Verification",
        "",
        f"- File references verified: {verification['files_verified']}.",
        f"- Bytes checked (includes unchanged raw/curated IR copies): {verification['bytes_verified']}.",
        f"- Integrity errors: {len(verification['errors'])}.",
        "",
        "`inventory.json` contains the complete machine-readable ranges, yearly counts, source gaps and errors.",
        "Raw sources and older snapshots are retained. Curation renames/copies PDFs; text cleaning is a separate ingestion step.",
        "This historical cache is a superset for final research corpus selection; it does not define a held-out split.",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, default=os.environ.get("SENTIMENT_DATA_ROOT"))
    args = parser.parse_args()
    if args.data_root is None or not args.data_root.is_dir():
        parser.error("provide the existing external research-data repository")
    inventory = build_inventory(args.data_root.resolve())
    output = args.data_root / "data/research_history"
    output.mkdir(exist_ok=True)
    _atomic_json(output / "inventory.json", inventory)
    (output / "README.md").write_text(markdown(inventory), encoding="utf-8")
    for item in inventory["companies"]:
        print(
            json.dumps(
                {
                    "ticker": item["ticker"],
                    "ir_pdfs": item["ir"]["documents"],
                    "sec": {form: row["downloaded"] for form, row in item["sec"]["by_form"].items()},
                    "missing_sec": len(item["sec"]["missing"]),
                    "ir_gaps": item["ir"]["missing_fiscal_periods"],
                }
            )
        )
    print(json.dumps(inventory["verification"]))
    return int(
        bool(inventory["verification"]["errors"])
        or any(not item["sec"]["complete_against_indexes"] for item in inventory["companies"])
    )


if __name__ == "__main__":
    raise SystemExit(main())
