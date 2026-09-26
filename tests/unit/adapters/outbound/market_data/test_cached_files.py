"""Tests for the validated offline market-price snapshot adapter."""

import hashlib
import json
from datetime import date
from pathlib import Path

import pytest

from sentiment_system.adapters.outbound.market_data.cached_files import CachedCsvMarketData, MarketDataCacheError
from sentiment_system.application.ports.market_data import MarketData, PricePoint


def test_cached_csv_market_data_verifies_snapshot_and_filters_prices_inclusively(tmp_path: Path) -> None:
    snapshot = _write_snapshot(
        tmp_path,
        "Date,Open,High,Low,Close,Volume\n" "2025-01-02,100,103,99,102,1000\n" "2025-01-03,101,104,100,103,2000\n",
        series_overrides={"rows": 2, "last_trading_date": "2025-01-03"},
    )

    market_data = CachedCsvMarketData(snapshot)

    assert isinstance(market_data, MarketData)
    assert market_data.get_prices("AAPL", start=date(2025, 1, 2), end=date(2025, 1, 2)) == (
        PricePoint("AAPL", date(2025, 1, 2), 102.0),
    )
    assert market_data.get_prices("AAPL", start=date(2025, 1, 3), end=date(2025, 1, 3)) == (
        PricePoint("AAPL", date(2025, 1, 3), 103.0),
    )
    assert market_data.get_prices("MSFT") == ()


def test_cached_csv_market_data_rejects_a_csv_hash_mismatch(tmp_path: Path) -> None:
    snapshot = _write_snapshot(tmp_path, _CSV_CONTENT)
    (snapshot / "AAPL.csv").write_text(_CSV_CONTENT.replace("102", "202"), encoding="utf-8")

    with pytest.raises(MarketDataCacheError, match="checksum mismatch"):
        CachedCsvMarketData(snapshot)


@pytest.mark.parametrize(
    ("content", "series_overrides"),
    [
        (
            "Date,Open,High,Low,Adj Close,Volume\n2025-01-02,100,103,99,102,1000\n",
            {},
        ),
        (
            "Date,Open,High,Low,Close,Volume\n2025-01-02,100,103,99,0,1000\n",
            {},
        ),
        (
            "Date,Open,High,Low,Close,Volume\n2025-01-02,100,103,99,102,1000\n" "2025-01-02,101,104,100,103,2000\n",
            {"rows": 2, "last_trading_date": "2025-01-02"},
        ),
        (
            "Date,Open,High,Low,Close,Volume\n2025-01-03,101,104,100,103,2000\n" "2025-01-02,100,103,99,102,1000\n",
            {"rows": 2, "last_trading_date": "2025-01-03"},
        ),
        (
            "Date,Open,High,Low,Close,Volume\nnot-a-date,100,103,99,102,1000\n",
            {},
        ),
    ],
)
def test_cached_csv_market_data_rejects_invalid_csv_rows(
    tmp_path: Path, content: str, series_overrides: dict[str, object]
) -> None:
    snapshot = _write_snapshot(tmp_path, content, series_overrides=series_overrides)

    with pytest.raises(MarketDataCacheError):
        CachedCsvMarketData(snapshot)


def test_cached_csv_market_data_rejects_invalid_manifest_and_metadata(tmp_path: Path) -> None:
    snapshot = _write_snapshot(
        tmp_path,
        _CSV_CONTENT,
        manifest_overrides={"schema_version": 2},
        series_overrides={"rows": 2},
    )

    with pytest.raises(MarketDataCacheError, match="schema_version"):
        CachedCsvMarketData(snapshot)


def test_cached_csv_market_data_rejects_unsafe_csv_filenames(tmp_path: Path) -> None:
    snapshot = _write_snapshot(tmp_path, _CSV_CONTENT, series_overrides={"csv_file": "../AAPL.csv"})

    with pytest.raises(MarketDataCacheError, match="direct child"):
        CachedCsvMarketData(snapshot)


def test_cached_csv_market_data_rejects_inconsistent_series_metadata(tmp_path: Path) -> None:
    snapshot = _write_snapshot(tmp_path, _CSV_CONTENT, series_overrides={"rows": 2})

    with pytest.raises(MarketDataCacheError, match="row count"):
        CachedCsvMarketData(snapshot)


_CSV_CONTENT = "Date,Open,High,Low,Close,Volume\n2025-01-02,100,103,99,102,1000\n"


def _write_snapshot(
    root: Path,
    content: str,
    *,
    manifest_overrides: dict[str, object] | None = None,
    series_overrides: dict[str, object] | None = None,
) -> Path:
    snapshot = root / "snapshot"
    snapshot.mkdir()
    (snapshot / "AAPL.csv").write_text(content, encoding="utf-8")
    series = {
        "asset_class": "stocks",
        "csv_file": "AAPL.csv",
        "csv_sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
        "first_trading_date": "2025-01-02",
        "last_trading_date": "2025-01-02",
        "requested_end": "2025-01-03",
        "requested_start": "2025-01-02",
        "response_sha256": "a" * 64,
        "retrieved_at": "2026-09-26T00:00:00+00:00",
        "rows": 1,
        "source_url": "https://example.test/AAPL",
        "symbol": "AAPL",
    }
    if series_overrides:
        series.update(series_overrides)
    manifest = {
        "csv_fields": ["Date", "Open", "High", "Low", "Close", "Volume"],
        "nullable_csv_fields": ["Volume"],
        "price_frequency": "daily_trading_day",
        "provider": "example",
        "return_price_field": "Close",
        "schema_version": 1,
        "series": [series],
    }
    if manifest_overrides:
        manifest.update(manifest_overrides)
    (snapshot / "market_prices.json").write_text(json.dumps(manifest), encoding="utf-8")
    return snapshot
