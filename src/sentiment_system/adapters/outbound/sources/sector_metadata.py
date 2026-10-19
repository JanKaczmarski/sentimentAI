"""Offline validation of reviewed sector classifications and downloaded evidence."""

import hashlib
import json
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from sentiment_system.domain.research import RESEARCH_TICKERS, SECTOR_BENCHMARKS


def verified_file(root: Path, relative: str, checksum: str | None = None) -> bytes:
    """Require a bounded, contained regular file and, when supplied, its SHA-256."""
    path = root / relative
    parts = PurePosixPath(relative)
    if parts.is_absolute() or ".." in parts.parts or path.is_symlink():
        raise ValueError("evidence path must be a safe relative regular file")
    if not path.resolve().is_relative_to(root.resolve()) or not path.is_file():
        raise ValueError(f"evidence file missing or outside data root: {relative}")
    if path.stat().st_size > 8 * 1024 * 1024:
        raise ValueError("evidence file exceeds size limit")
    content = path.read_bytes()
    if checksum is not None and hashlib.sha256(content).hexdigest() != checksum:
        raise ValueError(f"evidence checksum mismatch: {relative}")
    return content


def load_sector_review(
    root: Path, review_path: str, checksum: str | None = None
) -> tuple[list[dict[str, Any]], dict[str, bytes]]:
    """Return corpus company metadata plus the complete, hash-verified evidence bundle."""
    artifacts = {review_path: verified_file(root, review_path, checksum)}
    review = json.loads(artifacts[review_path])
    if review.get("schema_version") != 1 or not review.get("reviewer") or not review.get("note"):
        raise ValueError("sector review requires schema, reviewer and provenance note")
    downloads_path = review["downloads_path"]
    artifacts[downloads_path] = verified_file(root, downloads_path, review["downloads_sha256"])
    downloads = json.loads(artifacts[downloads_path])
    if downloads.get("schema_version") != 1:
        raise ValueError("unsupported sector downloads schema")
    entries = downloads["downloads"]
    by_ticker = {item["ticker"]: item for item in entries}
    reviewed = review["companies"]
    if (
        len(by_ticker) != len(entries)
        or set(by_ticker) != set(RESEARCH_TICKERS)
        or len(reviewed) != len(RESEARCH_TICKERS)
        or {item["ticker"] for item in reviewed} != set(RESEARCH_TICKERS)
    ):
        raise ValueError("sector evidence must cover exactly the six research companies")
    companies = []
    for item in reviewed:
        download = by_ticker[item["ticker"]]
        for kind in ("raw", "text"):
            relative = download[f"{kind}_path"]
            artifacts[relative] = verified_file(root, relative, download[f"{kind}_sha256"])
        # Check the reviewed quote against both the original HTML and saved text.
        text = artifacts[download["text_path"]].decode("utf-8")
        soup = BeautifulSoup(artifacts[download["raw_path"]], "html.parser")
        quote = item["evidence_quote"]
        if (
            quote != f"Sector\n{item['source_sector']}"
            or quote not in text
            or quote not in soup.get_text("\n", strip=True)
            or f"Ticker Symbol\n{item['ticker']}" not in text
        ):
            raise ValueError("sector review quote or company identity is not supported by the download")
        normalized = "Information Technology" if item["source_sector"] == "Technology" else item["source_sector"]
        if item["sector"] != normalized or not item.get("normalization_note"):
            raise ValueError("sector normalization must be explicit and supported")
        url = urlparse(download["source_url"])
        if url.scheme != "https" or not url.hostname or url.username or url.password:
            raise ValueError("sector source must be a credential-free HTTPS URL")
        if datetime.fromisoformat(download["retrieved_at"]).tzinfo is None:
            raise ValueError("sector retrieval timestamp must include a timezone")
        companies.append(
            {
                "ticker": item["ticker"],
                "evaluation_member": True,
                "sector": normalized,
                "benchmark": SECTOR_BENCHMARKS.get(normalized, "SPY"),
                "sector_source_url": download["source_url"],
                "sector_retrieved_at": download["retrieved_at"],
            }
        )
    return companies, artifacts
