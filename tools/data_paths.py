"""Resolve paths in the separate local research-data repository."""

import os
from pathlib import Path

DATA_ROOT_ENVIRONMENT_VARIABLE = "SENTIMENT_DATA_ROOT"


def data_repository_root() -> Path:
    """Return the configured data repository root."""
    configured_root = os.environ.get(DATA_ROOT_ENVIRONMENT_VARIABLE)
    if not configured_root:
        raise RuntimeError(f"{DATA_ROOT_ENVIRONMENT_VARIABLE} must point to the separate research-data repository")
    return Path(configured_root).expanduser()


def cik_map_path() -> Path:
    """Return the ticker-to-CIK mapping path."""
    return data_repository_root() / "cik_map.csv"


def sec_directory() -> Path:
    """Return the directory containing SEC inputs and manifests."""
    return data_repository_root() / "data" / "sec"
