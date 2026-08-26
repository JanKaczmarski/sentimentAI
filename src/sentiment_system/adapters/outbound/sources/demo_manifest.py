"""Bounded, hash-verified source adapter for the supervisor demonstration."""

import hashlib
import json
from collections.abc import Mapping
from datetime import date
from pathlib import Path
from typing import Any

from pypdf import PdfReader

from sentiment_system.domain.documents import SourceDocument


class DemoManifestError(ValueError):
    """Raised when the bounded demonstration manifest or source files are invalid."""


class DemoManifestDocumentSource:
    """Load only explicitly listed external source records for the supervisor demo."""

    def __init__(self, *, root: Path, manifest_path: Path) -> None:
        self._root = root.resolve()
        self._manifest_path = manifest_path
        payload = _read_json(manifest_path)
        manifest_version = _required_string(payload, "manifest_version")
        cutoff_date = _parse_date(payload, "cutoff_date")
        records = payload.get("records")
        if not isinstance(records, list) or not records:
            raise DemoManifestError(f"{manifest_path} must contain a non-empty records list")
        self._documents = tuple(
            _document_from_record(
                record,
                root=self._root,
                manifest_version=manifest_version,
                cutoff_date=cutoff_date,
            )
            for record in records
        )

    def fetch_documents(
        self,
        *,
        company: str | None = None,
        published_after: date | None = None,
        published_before: date | None = None,
    ) -> tuple[SourceDocument, ...]:
        """Return only listed records in deterministic publication order."""
        documents = (
            document
            for document in self._documents
            if (company is None or document.company == company.upper())
            and (published_after is None or document.published_at > published_after)
            and (published_before is None or document.published_at < published_before)
        )
        return tuple(sorted(documents, key=lambda item: (item.published_at, item.source, item.source_id)))


def _document_from_record(
    record: object,
    *,
    root: Path,
    manifest_version: str,
    cutoff_date: date,
) -> SourceDocument:
    if not isinstance(record, Mapping):
        raise DemoManifestError("manifest record must be an object")
    source = _required_string(record, "source")
    if source not in {"sec", "investor_relations"}:
        raise DemoManifestError(f"unsupported demo source: {source}")
    published_at = _parse_date(record, "published_at")
    if published_at > cutoff_date:
        raise DemoManifestError("record published_at must not exceed cutoff_date")
    raw_path = root / _required_string(record, "raw_path")
    try:
        raw_path = raw_path.resolve()
        raw_path.relative_to(root)
    except ValueError as error:
        raise DemoManifestError("raw_path must remain within the configured data root") from error
    if not raw_path.is_file():
        raise DemoManifestError(f"missing demo source file: {raw_path}")
    expected_hash = _required_string(record, "raw_sha256")
    if hashlib.sha256(raw_path.read_bytes()).hexdigest() != expected_hash:
        raise DemoManifestError(f"checksum mismatch for {raw_path}")
    _required_string(record, "cleaned_content_version")
    return SourceDocument(
        document_id=_required_string(record, "document_id"),
        source_id=_required_string(record, "source_id"),
        company=_required_string(record, "company").upper(),
        source=source,
        published_at=published_at,
        document_type=_required_string(record, "document_type"),
        raw_content=_read_content(raw_path),
        cleaned_content=_read_content(raw_path),
        manifest_version=manifest_version,
    )


def _read_content(path: Path) -> str:
    if path.suffix.casefold() == ".pdf":
        content = "\n".join(page.extract_text() or "" for page in PdfReader(str(path)).pages).strip()
    else:
        content = path.read_text(encoding="utf-8")
    if not content.strip():
        raise DemoManifestError(f"demo source file has no readable text: {path}")
    return content


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise DemoManifestError(f"unable to read demo manifest: {path}") from error
    if not isinstance(payload, dict):
        raise DemoManifestError(f"{path} must contain an object")
    return payload


def _required_string(payload: Mapping[str, object], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise DemoManifestError(f"manifest field {key} is required")
    return value.strip()


def _parse_date(payload: Mapping[str, object], key: str) -> date:
    try:
        return date.fromisoformat(_required_string(payload, key))
    except ValueError as error:
        raise DemoManifestError(f"manifest field {key} must be an ISO date") from error
