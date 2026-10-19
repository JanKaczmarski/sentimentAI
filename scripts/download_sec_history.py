"""Acquire SEC history back to each research company's earliest IR publication year.

Preserves raw indexes and filings with resumable manifests and coverage inventories.
10-K/10-Q: primary HTML document; 8-K: complete submission including exhibits.
All original 8-K items are acquired, not only Item 2.02. Amendments are excluded.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx
from dotenv import load_dotenv

from scripts.acquire_corpus import _validate_sec_user_agent
from scripts.download_earnings_calls import _atomic_json
from sentiment_system.domain.research import RESEARCH_TICKERS

# Disney's 2019 holding-company reorganization changed its SEC registrant.
COMPANY_CIKS = {
    "META": ("1326801",),
    "CRM": ("1108524",),
    "V": ("1403161",),
    "DIS": ("1001039", "1744489"),
    "WHR": ("106640",),
    "T": ("732717",),
}
_ACCESSION = re.compile(r"\d{10}-\d{2}-\d{6}")
_HISTORY = re.compile(r"CIK\d{10}-submissions-\d+\.json")
_MAX_BYTES = 256 * 1024 * 1024


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


class SecFetcher:
    """Official-only bounded SEC GETs, with pacing and transient-error retries."""

    def __init__(self, client: httpx.Client, user_agent: str, *, delay: float = 0.25) -> None:
        _validate_sec_user_agent(user_agent)
        self.client = client
        self.user_agent = user_agent
        self.delay = delay

    def get(self, url: str) -> bytes:
        parsed = urlsplit(url)
        if (
            parsed.scheme != "https"
            or parsed.hostname not in {"www.sec.gov", "data.sec.gov", "www.archives.sec.gov"}
            or parsed.username
            or parsed.password
            or parsed.port not in (None, 443)
        ):
            raise ValueError("expected an official SEC HTTPS URL")
        for attempt in range(3):
            time.sleep(self.delay)
            try:
                with self.client.stream(
                    "GET", url, headers={"User-Agent": self.user_agent}, follow_redirects=False
                ) as response:
                    response.raise_for_status()
                    content = bytearray()
                    for chunk in response.iter_bytes(chunk_size=64 * 1024):
                        content.extend(chunk)
                        if len(content) > _MAX_BYTES:
                            raise ValueError("SEC source exceeds size limit")
                    if not content:
                        raise ValueError("SEC source is empty")
                    return bytes(content)
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code not in (429, 500, 502, 503, 504) or attempt == 2:
                    raise ValueError(f"HTTP {exc.response.status_code}: {url}") from None
            except httpx.TransportError:
                if attempt == 2:
                    raise ValueError(f"SEC network error: {url}") from None
            time.sleep(2 ** (attempt + 1))
        raise AssertionError("unreachable")


def select_filings(columns: dict[str, Any], cik: str, start: date, end: date) -> list[dict[str, Any]]:
    """Parse recent or historical parallel arrays without truncating mismatches."""
    keys = ("form", "filingDate", "accessionNumber", "reportDate", "items", "primaryDocument")
    arrays = [columns.get(key) for key in keys]
    if any(not isinstance(column, list) for column in arrays):
        raise ValueError("SEC filing columns are missing or have inconsistent lengths")
    if len({len(column) for column in arrays if isinstance(column, list)}) != 1:
        raise ValueError("SEC filing columns are missing or have inconsistent lengths")
    records: list[dict[str, Any]] = []
    for form, filed, accession, report, items, primary in zip(*arrays, strict=True):
        if not all(isinstance(value, str) for value in (form, filed, accession, report, items, primary)):
            raise ValueError("SEC filing columns must contain strings")
        if form not in {"10-K", "10-Q", "8-K"} or not start <= date.fromisoformat(filed) <= end:
            continue
        if not _ACCESSION.fullmatch(accession) or not re.fullmatch(r"[A-Za-z0-9_.-]+", primary):
            raise ValueError("unsafe SEC filing identifier or primary document")
        base = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession.replace('-', '')}"
        records.append(
            {
                "cik": f"{int(cik):010d}",
                "accession_number": accession,
                "form": form,
                "filed_at": filed,
                "published_at": filed,
                "report_date": report,
                "form_items": [item.strip() for item in items.split(",") if item.strip()],
                "primary_document": primary,
                "representation": "complete_submission" if form == "8-K" else "primary_document",
                "source_url": f"{base}/{accession}.txt" if form == "8-K" else f"{base}/{primary}",
            }
        )
    return records


def acquire_company(
    data_root: Path, ticker: str, start: date, end: date, fetcher: SecFetcher, *, indexes_only: bool = False
) -> dict[str, Any]:
    """Reconcile every selected accession against verified local downloads."""
    folder = data_root / "data/sec/history" / ticker
    folder.mkdir(parents=True, exist_ok=True)
    if folder.is_symlink() or not folder.resolve().is_relative_to(data_root.resolve()):
        raise ValueError("SEC output directory escapes data repository")
    index_folder = folder / "indexes"
    index_folder.mkdir(exist_ok=True)
    manifest_path = folder / "manifest.json"
    previous = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    by_accession = {item["accession_number"]: item for item in previous.get("documents", [])}
    indexes: list[dict[str, Any]] = []
    index_errors: list[dict[str, str]] = []
    selected: dict[str, dict[str, Any]] = {}

    def read_index(name: str) -> dict[str, Any]:
        url = f"https://data.sec.gov/submissions/{name}"
        content = fetcher.get(url)
        value: dict[str, Any] = json.loads(content)
        # Index snapshots are content-addressed so refreshed metadata never destroys evidence.
        digest = hashlib.sha256(content).hexdigest()
        path = index_folder / f"{name.removesuffix('.json')}__{digest}.json"
        if not path.exists():
            path.write_bytes(content)
        indexes.append(
            {
                "source_url": url,
                "retrieved_at": now(),
                "sha256": digest,
                "local_path": path.relative_to(data_root).as_posix(),
            }
        )
        return value

    for cik in COMPANY_CIKS[ticker]:
        try:
            submission = read_index(f"CIK{int(cik):010d}.json")
            batches = [submission["filings"]["recent"]]
            for history in submission["filings"].get("files", []):
                first, last = date.fromisoformat(history["filingFrom"]), date.fromisoformat(history["filingTo"])
                if first > last:
                    raise ValueError("SEC historical index has reversed dates")
                if first <= end and last >= start:
                    name = history["name"]
                    if not _HISTORY.fullmatch(name) or not name.startswith(f"CIK{int(cik):010d}-"):
                        raise ValueError("unsafe SEC historical index name")
                    try:
                        batches.append(read_index(name))
                    except (ValueError, OSError) as exc:
                        index_errors.append({"cik": cik, "index": name, "error": str(exc)})
            for columns in batches:
                for record in select_filings(columns, cik, start, end):
                    accession = record["accession_number"]
                    if accession in selected and selected[accession] != record:
                        raise ValueError(f"conflicting SEC metadata for accession {accession}")
                    selected[accession] = record
        except (ValueError, KeyError, TypeError, OSError) as exc:
            index_errors.append({"cik": cik, "error": str(exc)})

    records: list[dict[str, Any]] = []
    result: dict[str, Any] = {}

    def save() -> None:
        nonlocal result
        result = {
            "schema_version": 1,
            "ticker": ticker,
            "updated_at": now(),
            "requested_window": {"start": start.isoformat(), "end": end.isoformat()},
            "selection": "all original 10-K, 10-Q and 8-K; amendments excluded; all 8-K items retained",
            "ciks": list(COMPANY_CIKS[ticker]),
            "indexes": indexes,
            "index_errors": index_errors,
            "discovery_complete": not index_errors,
            "documents": records,
            "coverage": coverage(list(selected.values()), records, start, end, index_errors),
        }
        _atomic_json(manifest_path, result)

    # Retain provenance for every downloaded record before beginning a refresh.
    for accession, old in by_accession.items():
        if accession not in selected:
            records.append({**old, "in_current_selection": False})
    ordered = sorted(selected.values(), key=lambda item: (item["filed_at"], item["accession_number"]))
    for record in ordered:
        old = by_accession.get(record["accession_number"])
        records.append(
            {
                **record,
                **(
                    {
                        key: old[key]
                        for key in ("raw_path", "raw_sha256", "retrieved_at", "bytes", "status")
                        if key in old
                    }
                    if old
                    else {"status": "pending"}
                ),
                "in_current_selection": True,
            }
        )
    save()
    for index, record in enumerate(records):
        if not record.get("in_current_selection"):
            continue
        try:
            previous_path = record.get("raw_path")
            existing = data_root / previous_path if previous_path else None
            if existing is not None and (
                existing.is_symlink() or not existing.resolve().is_relative_to(data_root.resolve())
            ):
                raise ValueError("cached SEC path escapes data repository")
            if existing is not None and existing.is_file():
                if hashlib.sha256(existing.read_bytes()).hexdigest() != record.get("raw_sha256"):
                    raise ValueError("cached SEC checksum mismatch; refusing overwrite")
                record["status"] = "existing"
            elif not indexes_only:
                content = fetcher.get(record["source_url"])
                if record["form"] == "8-K":
                    if (
                        b"<SEC-DOCUMENT>" not in content[:12000]
                        or record["accession_number"].encode() not in content[:12000]
                    ):
                        raise ValueError("response is not the requested SEC submission")
                elif b"<html" not in content[:3000].lower() and b"<HTML" not in content[:3000]:
                    raise ValueError("response is not an HTML SEC filing")
                digest = hashlib.sha256(content).hexdigest()
                suffix = ".txt" if record["form"] == "8-K" else ".html"
                destination = folder / f"{record['accession_number']}__{digest}{suffix}"
                if destination.is_symlink():
                    raise ValueError("SEC destination must not be a symlink")
                staging = destination.with_suffix(suffix + ".part")
                staging.write_bytes(content)
                staging.replace(destination)
                record.update(
                    {
                        "raw_path": destination.relative_to(data_root).as_posix(),
                        "raw_sha256": digest,
                        "bytes": len(content),
                        "retrieved_at": now(),
                        "status": "downloaded",
                    }
                )
            else:
                record["status"] = "pending"
            if record["status"] in ("existing", "downloaded"):
                record.pop("error", None)
        except (ValueError, OSError) as exc:
            record.update({"status": "failed", "error": str(exc)})
        save()
        if not indexes_only and ((index + 1) % 20 == 0 or record["status"] == "failed"):
            print(
                f"{ticker}: {index + 1}/{len(records)} {record['form']} {record['filed_at']}: {record['status']}",
                flush=True,
            )
    print(json.dumps({"ticker": ticker, **result["coverage"]["totals"], "index_errors": index_errors}), flush=True)
    return result


def coverage(
    expected: list[dict[str, Any]],
    records: list[dict[str, Any]],
    start: date,
    end: date,
    index_errors: list[dict[str, str]],
) -> dict[str, Any]:
    saved = {
        item["accession_number"]: item
        for item in records
        if item.get("in_current_selection") and item["status"] in ("existing", "downloaded")
    }
    missing = [
        {
            **item,
            "reason": next(
                (
                    row.get("error", "not downloaded")
                    for row in records
                    if row["accession_number"] == item["accession_number"]
                ),
                "not downloaded",
            ),
        }
        for item in expected
        if item["accession_number"] not in saved
    ]
    by_form = {}
    for form in ("10-K", "10-Q", "8-K", "8-K:2.02"):

        def matches(item: dict[str, Any]) -> bool:
            return item["form"] == form or (
                form == "8-K:2.02" and item["form"] == "8-K" and "2.02" in item["form_items"]
            )

        found = [item for item in expected if matches(item)]
        acquired = [item for item in found if item["accession_number"] in saved]
        dates = sorted(item["filed_at"] for item in acquired)
        by_form[form] = {
            "expected": len(found),
            "downloaded": len(acquired),
            "publication_start": dates[0] if dates else None,
            "publication_end": dates[-1] if dates else None,
            "by_year": {
                str(year): {
                    "expected": sum(item["filed_at"].startswith(str(year)) for item in found),
                    "downloaded": sum(item["filed_at"].startswith(str(year)) for item in acquired),
                }
                for year in range(start.year, end.year + 1)
            },
        }
    return {
        "expected": len(expected),
        "downloaded": len(saved),
        "missing": missing,
        "by_form": by_form,
        "totals": {"expected": len(expected), "downloaded": len(saved), "missing": len(missing)},
        "complete_against_indexes": not missing and not index_errors,
        "period_note": "Year counts reflect filing/publication dates, not fiscal years; boundary years may be partial.",
    }


def main() -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, default=os.environ.get("SENTIMENT_DATA_ROOT"))
    parser.add_argument("--tickers", nargs="+", choices=RESEARCH_TICKERS, default=RESEARCH_TICKERS)
    parser.add_argument("--end", type=date.fromisoformat, default=date.today())
    parser.add_argument("--indexes-only", action="store_true")
    args = parser.parse_args()
    if args.data_root is None or not args.data_root.is_dir():
        parser.error("set SENTIMENT_DATA_ROOT or --data-root to the existing external data repository")
    root = args.data_root.resolve()
    summaries = []
    with httpx.Client(timeout=60.0, follow_redirects=False) as client:
        fetcher = SecFetcher(client, os.environ.get("SEC_USER_AGENT", ""))
        for ticker in args.tickers:
            ir_manifest = root / f"data/company_communications/curated/{ticker}/manifest.json"
            ir = json.loads(ir_manifest.read_text())
            earliest = ir["coverage"]["publication_start"]
            if earliest is None:
                raise ValueError(f"{ticker}: no dated curated IR available")
            start = date(date.fromisoformat(earliest).year, 1, 1)
            if start > args.end:
                parser.error("end precedes IR coverage")
            print(f"{ticker}: SEC window {start} through {args.end}", flush=True)
            manifest = acquire_company(root, ticker, start, args.end, fetcher, indexes_only=args.indexes_only)
            summaries.append(
                {
                    "ticker": ticker,
                    "requested_window": manifest["requested_window"],
                    "ir": ir["coverage"],
                    "sec": manifest["coverage"],
                    "index_errors": manifest["index_errors"],
                }
            )
    # A selected-company retry must not erase other companies' coverage.
    all_summaries = []
    for ticker in RESEARCH_TICKERS:
        path = root / f"data/sec/history/{ticker}/manifest.json"
        if path.is_file():
            item = json.loads(path.read_text())
            all_summaries.append(
                {
                    "ticker": ticker,
                    "requested_window": item["requested_window"],
                    "sec": item["coverage"],
                    "index_errors": item["index_errors"],
                }
            )
    _atomic_json(
        root / "data/sec/history/coverage.json", {"schema_version": 1, "updated_at": now(), "companies": all_summaries}
    )
    return int(any(item["index_errors"] or item["sec"]["missing"] for item in summaries))


if __name__ == "__main__":
    raise SystemExit(main())
