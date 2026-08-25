"""Integration coverage for persistent disposable ingestion state."""

from datetime import date, datetime, timezone

from sentiment_system.adapters.outbound.persistence.sqlite_workspace import SQLiteIngestionWorkspace
from sentiment_system.application.ports.ingestion_workspace import IngestionCursor, WorkspaceDocument
from sentiment_system.domain.documents import SourceDocument


def test_sqlite_workspace_round_trips_raw_normalized_and_cursor_state(tmp_path) -> None:
    workspace = SQLiteIngestionWorkspace(tmp_path / "workspace.sqlite3")
    record = WorkspaceDocument(
        document=SourceDocument(
            document_id="document-1",
            source_id="source-1",
            company="AAPL",
            source="fixture",
            published_at=date(2025, 1, 30),
            document_type="company_communication",
            raw_content="Raw content.",
            cleaned_content="Cleaned content.",
        ),
        request_key="request-1",
        raw_payload="raw fixture payload",
        fetched_at=datetime(2025, 2, 1, tzinfo=timezone.utc),
    )
    cursor = IngestionCursor(
        company="AAPL",
        source="fixture",
        value="cursor-1",
        updated_at=datetime(2025, 2, 1, tzinfo=timezone.utc),
    )

    workspace.record_document(record)
    workspace.update_cursor(cursor)

    assert workspace.get_document("document-1") == record
    assert workspace.get_cursor("AAPL", "fixture") == cursor
