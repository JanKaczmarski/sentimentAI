"""Runtime configuration loaded by the composition root."""

import os
from collections.abc import Mapping
from pathlib import Path

DEFAULT_INGESTION_WORKSPACE_PATH = Path(".local") / "ingestion.sqlite3"


def ingestion_workspace_path(environ: Mapping[str, str] | None = None) -> Path:
    """Return the disposable ingestion workspace path from runtime settings."""
    settings = os.environ if environ is None else environ
    configured = settings.get("INGESTION_SQLITE_PATH", "").strip()
    return Path(configured).expanduser() if configured else DEFAULT_INGESTION_WORKSPACE_PATH
