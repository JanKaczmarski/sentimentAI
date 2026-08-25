"""Resolve paths in the separate local research-data repository."""

import os
from pathlib import Path


def data_repository_root() -> Path:
    """Return the configured data repository root."""
    return Path(os.environ.get("SENTIMENT_DATA_ROOT", ".")).expanduser()


def cik_map_path() -> Path:
    """Return the ticker-to-CIK mapping path."""
    return data_repository_root() / "cik_map.csv"


def sec_directory() -> Path:
    """Return the directory containing SEC inputs and manifests."""
    return data_repository_root() / "data" / "sec"
