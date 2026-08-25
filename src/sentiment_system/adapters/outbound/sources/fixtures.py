"""Local fixture adapter for reproducible ingestion and tests."""

from collections.abc import Iterable, Mapping
from datetime import date

from sentiment_system.domain.documents import SourceDocument


class FixtureDocumentSource:
    """Serve an immutable-in-practice, deterministically ordered fixture set."""

    def __init__(self, documents: Iterable[SourceDocument | Mapping[str, object]] = ()) -> None:
        normalized = (_to_source_document(document) for document in documents)
        self._documents: dict[str, SourceDocument] = {document.document_id: document for document in normalized}

    def add(self, document: SourceDocument | Mapping[str, object]) -> None:
        """Insert or replace one fixture document."""
        normalized = _to_source_document(document)
        self._documents[normalized.document_id] = normalized

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


def _to_source_document(document: SourceDocument | Mapping[str, object]) -> SourceDocument:
    if isinstance(document, SourceDocument):
        return document
    if not isinstance(document, Mapping):
        raise ValueError("fixture document must be a SourceDocument or mapping")

    document_id = _required_string(document, "document_id")
    source_id = _required_string(document, "source_id")
    company = _required_string(document, "company")
    source = _required_string(document, "source")
    published_at = _parse_date(_required_value(document, "published_at"))
    document_type = _required_string(document, "document_type")
    raw_content = _required_string(document, "raw_content")
    return SourceDocument(
        document_id=document_id,
        source_id=source_id,
        company=company,
        source=source,
        published_at=published_at,
        document_type=document_type,
        raw_content=raw_content,
        cleaned_content=raw_content,
    )


def _required_value(document: Mapping[str, object], name: str) -> object:
    value = document.get(name)
    if value is None or (isinstance(value, str) and not value.strip()):
        raise ValueError(f"{name} is required")
    return value


def _required_string(document: Mapping[str, object], name: str) -> str:
    value = _required_value(document, name)
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a string")
    return value


def _parse_date(value: object) -> date:
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError as exc:
            raise ValueError("published_at must be an ISO date") from exc
    raise ValueError("published_at must be a date or ISO date")
