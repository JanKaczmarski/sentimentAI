"""Document and document-chunk entities shared by ingestion and scoring."""

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True, slots=True)
class SourceDocument:
    """An auditable source document with raw and cleaned representations."""

    document_id: str
    source_id: str
    company: str # TODO: I think company should be enum
    source: str # TODO: same here, enummmmmmmmmmm (overall 3 sources we have)
    published_at: date
    document_type: str
    raw_content: str
    cleaned_content: str

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


@dataclass(frozen=True, slots=True)
class DocumentChunk:
    """A stable source excerpt with document lineage and ordinal position."""

    chunk_id: str
    document_id: str
    ordinal: int
    content: str

    def __post_init__(self) -> None:
        _require_non_empty_string("chunk_id", self.chunk_id)
        _require_non_empty_string("document_id", self.document_id)
        if not isinstance(self.ordinal, int) or isinstance(self.ordinal, bool) or self.ordinal < 0:
            raise ValueError("ordinal must be a non-negative integer")
        _require_non_empty_string("content", self.content)


def _require_non_empty_string(name: str, value: object) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} is required")


def _require_string(name: str, value: object) -> None:
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a string")
