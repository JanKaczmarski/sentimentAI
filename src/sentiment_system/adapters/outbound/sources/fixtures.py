"""Local fixture adapter for reproducible ingestion and tests."""

from collections.abc import Iterable
from datetime import date

from sentiment_system.domain.documents import SourceDocument


class FixtureDocumentSource:
    """Serve an immutable-in-practice, deterministically ordered fixture set."""

    def __init__(self, documents: Iterable[SourceDocument] = ()) -> None:
        self._documents: dict[str, SourceDocument] = {document.document_id: document for document in documents}

    def add(self, document: SourceDocument) -> None:
        """Insert or replace one fixture document."""
        self._documents[document.document_id] = document

    def fetch_documents(
        self,
        *,
        company: str | None = None,
        published_after: date | None = None,
        published_before: date | None = None,
    ) -> tuple[SourceDocument, ...]:
        """Return documents matching exclusive date bounds in stable order."""
        documents = (
            document
            for document in self._documents.values()
            if (company is None or document.company == company)
            and (published_after is None or document.published_at > published_after)
            and (published_before is None or document.published_at < published_before)
        )
        return tuple(sorted(documents, key=lambda item: (item.published_at, item.document_id)))
