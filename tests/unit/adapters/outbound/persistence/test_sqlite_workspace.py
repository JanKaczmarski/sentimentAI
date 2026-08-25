"""Unit tests for the disposable SQLite ingestion workspace."""

from datetime import date, datetime, timezone

import pytest

from sentiment_system.adapters.outbound.persistence.sqlite_workspace import SQLiteIngestionWorkspace
from sentiment_system.application.ports.ingestion_workspace import IngestionCursor, WorkspaceDocument
from sentiment_system.domain.documents import SourceDocument


def test_workspace_reopens_from_the_configured_file_and_preserves_state(tmp_path) -> None:
    path = tmp_path / "workspace.sqlite3"
    first = SQLiteIngestionWorkspace(path)
    first.record_document(_record())
    first.update_cursor(_cursor())

    reopened = SQLiteIngestionWorkspace(path)

    assert reopened.get_document("document-1") == _record()
    assert reopened.get_cursor("AAPL", "fixture") == _cursor()


def _document(company: str = "AAPL") -> SourceDocument:
    return SourceDocument(
        document_id="document-1",
        source_id="fixture-1",
        company=company,
        source="fixture",
        published_at=date(2025, 1, 30),
        document_type="company_communication",
        raw_content="Raw payload.",
        cleaned_content="Cleaned payload.",
    )


def _record() -> WorkspaceDocument:
    return WorkspaceDocument(
        document=_document(),
        request_key="request-1",
        raw_payload='{"body":"Raw payload."}',
        fetched_at=datetime(2025, 2, 1, tzinfo=timezone.utc),
    )


def _cursor() -> IngestionCursor:
    return IngestionCursor(
        company="AAPL",
        source="fixture",
        value="cursor-1",
        updated_at=datetime(2025, 2, 1, tzinfo=timezone.utc),
    )


def test_workspace_initializes_and_seeds_the_approved_registry_idempotently(tmp_path) -> None:
    workspace = SQLiteIngestionWorkspace(tmp_path / "workspace.sqlite3")

    workspace.initialize()
    first_companies = workspace.list_companies()
    workspace.record_document(_record())
    workspace.update_cursor(_cursor())
    workspace.initialize()

    assert len(first_companies) == 64
    assert workspace.list_companies() == first_companies
    assert workspace.get_document("document-1") == _record()
    assert workspace.get_cursor("AAPL", "fixture") == _cursor()


def test_workspace_rejects_documents_for_unsupported_companies(tmp_path) -> None:
    workspace = SQLiteIngestionWorkspace(tmp_path / "workspace.sqlite3")

    with pytest.raises(ValueError, match="unsupported company ticker: UNKNOWN"):
        workspace.record_document(
            WorkspaceDocument(
                document=_document("UNKNOWN"),
                request_key="request-1",
                raw_payload="payload",
                fetched_at=datetime(2025, 2, 1, tzinfo=timezone.utc),
            )
        )
