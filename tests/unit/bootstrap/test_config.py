"""Tests for runtime workspace configuration."""

from pathlib import Path

from sentiment_system.bootstrap.config import DEFAULT_INGESTION_WORKSPACE_PATH, ingestion_workspace_path


def test_ingestion_workspace_path_uses_disposable_default() -> None:
    assert ingestion_workspace_path({}) == DEFAULT_INGESTION_WORKSPACE_PATH


def test_ingestion_workspace_path_accepts_explicit_runtime_path() -> None:
    assert (
        ingestion_workspace_path({"INGESTION_SQLITE_PATH": "~/sentiment/workspace.sqlite3"})
        == Path("~/sentiment/workspace.sqlite3").expanduser()
    )
