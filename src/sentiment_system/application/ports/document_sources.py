"""Port for loading normalized documents from SEC, IR, and fixture sources."""

from datetime import date
from typing import Protocol, runtime_checkable

from sentiment_system.domain.documents import SourceDocument


@runtime_checkable
class DocumentSource(Protocol):
    """Load normalized documents without exposing a source-provider API."""

    def fetch_documents(
        self,
        *,
        company: str | None = None,
        published_after: date | None = None,
        published_before: date | None = None,
    ) -> tuple[SourceDocument, ...]:
        """Return matching documents in deterministic publication order."""
