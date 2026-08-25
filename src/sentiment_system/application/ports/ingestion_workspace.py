"""Port and provider-neutral records for the disposable ingestion workspace."""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, runtime_checkable

from sentiment_system.domain.companies import Company
from sentiment_system.domain.documents import SourceDocument


@dataclass(frozen=True, slots=True)
class WorkspaceDocument:
    """A fetched payload plus its normalized document representation."""

    document: SourceDocument
    request_key: str
    raw_payload: str
    fetched_at: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.document, SourceDocument):
            raise ValueError("document must be a SourceDocument")
        _require_non_empty_string("request_key", self.request_key)
        _require_non_empty_string("raw_payload", self.raw_payload)
        if not isinstance(self.fetched_at, datetime):
            raise ValueError("fetched_at must be a datetime")


@dataclass(frozen=True, slots=True)
class IngestionCursor:
    """Provider-neutral progress marker for one company/source pair."""

    company: str
    source: str
    value: str
    updated_at: datetime

    def __post_init__(self) -> None:
        _require_non_empty_string("company", self.company)
        _require_non_empty_string("source", self.source)
        _require_non_empty_string("value", self.value)
        if not isinstance(self.updated_at, datetime):
            raise ValueError("updated_at must be a datetime")


@runtime_checkable
class IngestionWorkspace(Protocol):
    """Narrow development-only persistence boundary for ingestion state."""

    def initialize(self) -> None:
        """Create the disposable schema and seed the approved registry."""

    def list_companies(self) -> tuple[Company, ...]:
        """Return the seeded company metadata without provider types."""

    def get_company(self, ticker: str) -> Company | None:
        """Return one seeded company by ticker."""

    def record_document(self, record: WorkspaceDocument) -> None:
        """Insert or replace one fetched development document."""

    def get_document(self, document_id: str) -> WorkspaceDocument | None:
        """Return one recorded development document."""

    def update_cursor(self, cursor: IngestionCursor) -> None:
        """Insert or replace one source cursor."""

    def get_cursor(self, company: str, source: str) -> IngestionCursor | None:
        """Return one source cursor."""


def _require_non_empty_string(name: str, value: object) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} is required")
