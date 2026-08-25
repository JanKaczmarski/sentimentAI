"""Contract coverage for the SQLite ingestion workspace adapter."""

from sentiment_system.adapters.outbound.persistence.sqlite_workspace import SQLiteIngestionWorkspace
from sentiment_system.application.ports.ingestion_workspace import IngestionWorkspace


def test_sqlite_workspace_implements_the_provider_neutral_port(tmp_path) -> None:
    assert isinstance(SQLiteIngestionWorkspace(tmp_path / "workspace.sqlite3"), IngestionWorkspace)
