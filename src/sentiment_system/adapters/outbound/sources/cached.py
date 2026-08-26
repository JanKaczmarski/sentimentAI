"""Offline source adapter for the separate SEC and investor-relations cache."""

import csv
import hashlib
import json
from datetime import date
from pathlib import Path
from typing import Any

from pypdf import PdfReader

from sentiment_system.domain.documents import SourceDocument


class CacheManifestError(ValueError):
    """Raised when a cache manifest or referenced source file is invalid."""


class CachedCorpusDocumentSource:
    """Load immutable local SEC and curated IR documents without network access."""

    def __init__(self, root: Path) -> None:
        self._root = root
        self._documents = tuple((*self._load_sec(), *self._load_ir()))

    def fetch_documents(
        self,
        *,
        company: str | None = None,
        published_after: date | None = None,
        published_before: date | None = None,
    ) -> tuple[SourceDocument, ...]:
        documents = (
            document
            for document in self._documents
            if (company is None or document.company == company.upper())
            and (published_after is None or document.published_at > published_after)
            and (published_before is None or document.published_at < published_before)
        )
        return tuple(sorted(documents, key=lambda item: (item.published_at, item.source, item.source_id)))

    def _load_sec(self) -> tuple[SourceDocument, ...]:
        manifest_path = self._root / "data" / "sec" / "manifests" / "previous_calendar_quarter_earnings_releases.json"
        if not manifest_path.is_file():
            return ()
        payload = _read_json(manifest_path)
        manifest_version = _manifest_version(payload, "sec-v1")
        releases = payload.get("releases")
        if not isinstance(releases, list):
            raise CacheManifestError(f"{manifest_path} has no releases list")
        documents = []
        for release in releases:
            if not isinstance(release, dict):
                raise CacheManifestError(f"{manifest_path} contains an invalid release")
            ticker = _string(release, "ticker")
            source_id = _string(release, "accession_number")
            path = self._root / "data" / "sec" / "earnings_releases" / f"{ticker}_{source_id}.txt"
            documents.append(
                _document(
                    path=path,
                    document_id=f"sec:{source_id}",
                    source_id=source_id,
                    company=ticker,
                    source="sec",
                    published_at=date.fromisoformat(_string(release, "report_date")),
                    document_type=str(release.get("document_type") or "earnings_release"),
                    manifest_version=manifest_version,
                )
            )
        return tuple(documents)

    def _load_ir(self) -> tuple[SourceDocument, ...]:
        root = self._root / "data" / "company_communications" / "curated"
        documents = []
        for manifest_path in sorted(root.glob("*/manifest.csv")):
            with manifest_path.open(encoding="utf-8", newline="") as handle:
                for row in csv.DictReader(handle):
                    filename = _row_string(row, "canonical_filename", manifest_path)
                    ticker = _row_string(row, "ticker", manifest_path)
                    path = manifest_path.parent / filename
                    expected_hash = _row_string(row, "sha256", manifest_path)
                    actual_hash = hashlib.sha256(path.read_bytes()).hexdigest()
                    if actual_hash != expected_hash:
                        raise CacheManifestError(f"checksum mismatch for {path}")
                    documents.append(
                        SourceDocument(
                            document_id=f"investor_relations:{filename}",
                            source_id=filename,
                            company=ticker,
                            source="investor_relations",
                            published_at=date.fromisoformat(_row_string(row, "published_at", manifest_path)),
                            document_type=_row_string(row, "document_type", manifest_path),
                            raw_content=_read_text(path),
                            cleaned_content=_read_text(path),
                            manifest_version="ir-v1",
                        )
                    )
        return tuple(documents)


def _document(**values: object) -> SourceDocument:
    path = values.pop("path")
    if not isinstance(path, Path) or not path.is_file():
        raise CacheManifestError(f"missing cached source file: {path}")
    content = _read_text(path)
    return SourceDocument(raw_content=content, cleaned_content=content, **values)  # type: ignore[arg-type]


def _read_text(path: Path) -> str:
    if path.suffix.lower() == ".pdf":
        content = "\n".join(page.extract_text() or "" for page in PdfReader(str(path)).pages).strip()
    else:
        content = path.read_text(encoding="utf-8")
    if not content.strip():
        raise CacheManifestError(f"cached source file has no text: {path}")
    return content


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise CacheManifestError(f"{path} must contain an object")
    return payload


def _manifest_version(payload: dict[str, Any], default: str) -> str:
    value = payload.get("manifest_version", default)
    return value if isinstance(value, str) and value.strip() else default


def _string(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise CacheManifestError(f"manifest field {key} is required")
    return value


def _row_string(row: dict[str, str], key: str, path: Path) -> str:
    value = row.get(key)
    if not isinstance(value, str) or not value.strip():
        raise CacheManifestError(f"{path} field {key} is required")
    return value
