"""Tests for the external research-data repository paths."""

from pathlib import Path

from tools.data_paths import cik_map_path, data_repository_root, sec_directory


def test_data_paths_default_to_the_current_repository(monkeypatch) -> None:
    monkeypatch.delenv("SENTIMENT_DATA_ROOT", raising=False)

    assert data_repository_root() == Path(".")
    assert cik_map_path() == Path("cik_map.csv")
    assert sec_directory() == Path("data/sec")


def test_data_paths_can_target_the_separate_data_repository(monkeypatch) -> None:
    monkeypatch.setenv("SENTIMENT_DATA_ROOT", "~/datasets/sentimentAI-data")

    root = Path.home() / "datasets/sentimentAI-data"
    assert data_repository_root() == root
    assert cik_map_path() == root / "cik_map.csv"
    assert sec_directory() == root / "data/sec"
