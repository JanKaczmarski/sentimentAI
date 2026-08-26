"""Tests for the external research-data repository paths."""

from pathlib import Path

import pytest

from tools.data_paths import cik_map_path, data_repository_root, sec_directory


def test_data_paths_require_an_external_repository(monkeypatch) -> None:
    monkeypatch.delenv("SENTIMENT_DATA_ROOT", raising=False)

    with pytest.raises(RuntimeError, match="SENTIMENT_DATA_ROOT"):
        data_repository_root()


def test_data_paths_can_target_the_separate_data_repository(monkeypatch) -> None:
    monkeypatch.setenv("SENTIMENT_DATA_ROOT", "~/datasets/sentimentAI-data")

    root = Path.home() / "datasets/sentimentAI-data"
    assert data_repository_root() == root
    assert cik_map_path() == root / "cik_map.csv"
    assert sec_directory() == root / "data/sec"
