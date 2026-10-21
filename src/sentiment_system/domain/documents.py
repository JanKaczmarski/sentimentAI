"""Document and document-chunk entities shared by ingestion and scoring."""

import re
from dataclasses import dataclass
from datetime import date, datetime
from hashlib import sha256
from pathlib import PurePosixPath
from urllib.parse import urlparse

_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
_SEC_FORMS = frozenset({"10-K", "10-Q", "8-K"})


@dataclass(frozen=True, slots=True)
class SourceArtifact:
    """Verified original bytes, independent of extracted text and evaluation membership."""

    sha256: str
    path: str
    source_url: str | None = None
    retrieved_at: datetime | None = None
    form: str | None = None
    form_items: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require_sha256("artifact.sha256", self.sha256)
        _require_relative_path("artifact.path", self.path)
        if self.source_url is not None:
            _require_https_url("artifact.source_url", self.source_url)
        if self.retrieved_at is not None:
            _require_timestamp("artifact.retrieved_at", self.retrieved_at)
        if self.form is not None and self.form not in _SEC_FORMS:
            raise ValueError("unsupported source form")


@dataclass(frozen=True, slots=True)
class SourceProvenance:
    """Immutable cache-manifest lineage for a source document."""

    manifest_record_id: str
    source_url: str
    retrieved_at: datetime
    raw_path: str
    raw_sha256: str
    cleaned_path: str
    cleaned_sha256: str
    parser_version: str
    source_type: str
    form: str | None
    form_items: tuple[str, ...]
    content_group_id: str
    canonical_for_scoring: bool
    evaluation_member: bool
    sector: str
    sector_source_url: str
    sector_retrieved_at: datetime

    def __post_init__(self) -> None:
        _require_non_empty_string("manifest_record_id", self.manifest_record_id)
        _require_https_url("source_url", self.source_url)
        _require_timestamp("retrieved_at", self.retrieved_at)
        _require_relative_path("raw_path", self.raw_path)
        _require_sha256("raw_sha256", self.raw_sha256)
        _require_relative_path("cleaned_path", self.cleaned_path)
        _require_sha256("cleaned_sha256", self.cleaned_sha256)
        _require_non_empty_string("parser_version", self.parser_version)
        if self.source_type not in {"sec_filing", "investor_relations_release", "investor_relations_transcript"}:
            raise ValueError("source_type is unsupported")
        if self.source_type == "sec_filing" and self.form not in _SEC_FORMS:
            raise ValueError("SEC form is unsupported")
        if self.source_type != "sec_filing" and self.form is not None:
            raise ValueError("investor-relations releases must not include an SEC form")
        if any(not isinstance(item, str) or not item.strip() for item in self.form_items):
            raise ValueError("form_items must contain non-empty strings")
        if self.source_type != "sec_filing" and self.form_items:
            raise ValueError("investor-relations releases must not include SEC items")
        _require_non_empty_string("content_group_id", self.content_group_id)
        if not isinstance(self.canonical_for_scoring, bool):
            raise ValueError("canonical_for_scoring must be a boolean")
        if not isinstance(self.evaluation_member, bool):
            raise ValueError("evaluation_member must be a boolean")
        _require_non_empty_string("sector", self.sector)
        _require_https_url("sector_source_url", self.sector_source_url)
        _require_timestamp("sector_retrieved_at", self.sector_retrieved_at)


@dataclass(frozen=True, slots=True)
class SourceDocument:
    """An auditable source document with raw and cleaned representations."""

    document_id: str
    source_id: str
    company: str
    source: str
    published_at: date
    document_type: str
    raw_content: str
    cleaned_content: str
    manifest_version: str = "unspecified"
    provenance: SourceProvenance | None = None
    artifact: SourceArtifact | None = None
    cleaning_version: str = "unspecified"

    def __post_init__(self) -> None:
        _require_non_empty_string("document_id", self.document_id)
        _require_non_empty_string("source_id", self.source_id)
        _require_non_empty_string("company", self.company)
        _require_non_empty_string("source", self.source)
        if not isinstance(self.published_at, date):
            raise ValueError("published_at must be a date")
        _require_non_empty_string("document_type", self.document_type)
        _require_non_empty_string("raw_content", self.raw_content)
        _require_string("cleaned_content", self.cleaned_content)
        _require_non_empty_string("manifest_version", self.manifest_version)
        if self.provenance is not None and not isinstance(self.provenance, SourceProvenance):
            raise ValueError("provenance must be SourceProvenance or None")
        if self.provenance is not None:
            object.__setattr__(self, "cleaning_version", self.provenance.parser_version)
        if (
            self.artifact is not None
            and self.provenance is not None
            and self.artifact.sha256 != self.provenance.raw_sha256
        ):
            raise ValueError("artifact hash disagrees with manifest provenance")
        _require_non_empty_string("cleaning_version", self.cleaning_version)

    @property
    def original_byte_sha256(self) -> str | None:
        """Unknown legacy byte identity is never inferred from extracted PDF text."""
        return self.artifact.sha256 if self.artifact else self.provenance.raw_sha256 if self.provenance else None

    @property
    def source_revision_id(self) -> str | None:
        checksum = self.original_byte_sha256
        return f"{self.company}:{self.source}:{self.source_id}:{checksum}" if checksum else None

    @property
    def derivation_id(self) -> str:
        version = self.provenance.parser_version if self.provenance else self.cleaning_version
        checksum = sha256(self.cleaned_content.encode("utf-8")).hexdigest()
        return (
            f"derived:{self.source_revision_id}:{version}:{checksum}" if self.source_revision_id else self.document_id
        )


@dataclass(frozen=True, slots=True)
class DocumentChunk:
    """A stable source excerpt with document lineage and ordinal position."""

    chunk_id: str
    document_id: str
    ordinal: int
    content: str
    processing_config_version: str = "unspecified"

    def __post_init__(self) -> None:
        _require_non_empty_string("chunk_id", self.chunk_id)
        _require_non_empty_string("document_id", self.document_id)
        if not isinstance(self.ordinal, int) or isinstance(self.ordinal, bool) or self.ordinal < 0:
            raise ValueError("ordinal must be a non-negative integer")
        _require_non_empty_string("content", self.content)
        _require_non_empty_string("processing_config_version", self.processing_config_version)


def _require_non_empty_string(name: str, value: object) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} is required")


def _require_string(name: str, value: object) -> None:
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a string")


def _require_sha256(name: str, value: object) -> None:
    if not isinstance(value, str) or _SHA256_PATTERN.fullmatch(value) is None:
        raise ValueError(f"{name} must be a lowercase SHA-256 hash")


def _require_relative_path(name: str, value: object) -> None:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name} is required")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError(f"{name} must be a safe relative path")


def _require_https_url(name: str, value: object) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} is required")
    parsed = urlparse(value)
    if parsed.scheme != "https" or not parsed.netloc:
        raise ValueError(f"{name} must be an HTTPS URL")


def _require_timestamp(name: str, value: object) -> None:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError(f"{name} must be a timezone-aware datetime")
