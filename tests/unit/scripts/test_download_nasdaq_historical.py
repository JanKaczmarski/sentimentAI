"""Tests for Nasdaq daily-price snapshot acquisition."""

import hashlib
import json
from datetime import date, datetime, timezone
from pathlib import Path

import httpx
import pytest

from scripts.download_nasdaq_historical import (
    DailyPrice,
    DownloadedSeries,
    NasdaqDownloadError,
    fetch_historical,
    verify_snapshot,
    write_snapshot,
)


def test_fetch_historical_validates_and_sorts_daily_prices() -> None:
    response_body = {
        "status": {"rCode": 200},
        "data": {
            "tradesTable": {
                "rows": [
                    _row("01/03/2025", "101.00", "104.00", "100.00", "103.00", "2,000"),
                    _row("01/02/2025", "100.00", "103.00", "99.00", "102.00", "1,000"),
                ]
            }
        },
    }
    client = _client(response_body)

    downloaded = fetch_historical(
        client,
        "aapl",
        start=date(2025, 1, 2),
        end=date(2025, 1, 3),
        asset_class="stocks",
        retrieved_at=datetime(2026, 9, 26, tzinfo=timezone.utc),
    )

    assert downloaded.symbol == "AAPL"
    assert downloaded.asset_class == "stocks"
    assert downloaded.source_url == (
        "https://api.nasdaq.com/api/quote/AAPL/historical?assetclass=stocks&fromdate=2025-01-02"
        "&todate=2025-01-03&limit=9999"
    )
    assert [price.trading_date for price in downloaded.prices] == [date(2025, 1, 2), date(2025, 1, 3)]
    assert downloaded.prices[0].close == 102.0


def test_fetch_historical_rejects_duplicate_or_incomplete_rows() -> None:
    response_body = {
        "status": {"rCode": 200},
        "data": {
            "tradesTable": {
                "rows": [
                    _row("01/02/2025", "100.00", "103.00", "99.00", "102.00", "1,000"),
                    _row("01/02/2025", "100.00", "103.00", "99.00", "102.00", "1,000"),
                ]
            }
        },
    }

    with pytest.raises(NasdaqDownloadError, match="strictly increasing"):
        fetch_historical(
            _client(response_body),
            "AAPL",
            start=date(2025, 1, 2),
            end=date(2025, 1, 3),
            asset_class="stocks",
            retrieved_at=datetime(2026, 9, 26, tzinfo=timezone.utc),
        )


def test_fetch_historical_preserves_an_unavailable_volume_as_null() -> None:
    response_body = {
        "status": {"rCode": 200},
        "data": {"tradesTable": {"rows": [_row("01/02/2025", "100.00", "103.00", "99.00", "102.00", "N/A")]}},
    }

    downloaded = fetch_historical(
        _client(response_body),
        "SPY",
        start=date(2025, 1, 2),
        end=date(2025, 1, 2),
        asset_class="etf",
        retrieved_at=datetime(2026, 9, 26, tzinfo=timezone.utc),
    )

    assert downloaded.prices[0].volume is None


def test_write_snapshot_creates_csvs_and_json_provenance(tmp_path: Path) -> None:
    downloaded = DownloadedSeries(
        symbol="AAPL",
        asset_class="stocks",
        requested_start=date(2025, 1, 2),
        requested_end=date(2025, 1, 3),
        retrieved_at=datetime(2026, 9, 26, tzinfo=timezone.utc),
        source_url="https://api.nasdaq.com/api/quote/AAPL/historical?assetclass=stocks",
        response_sha256="a" * 64,
        prices=(
            DailyPrice(date(2025, 1, 2), 100.0, 103.0, 99.0, 102.0, 1000),
            DailyPrice(date(2025, 1, 3), 101.0, 104.0, 100.0, 103.0, 2000),
        ),
    )
    output_dir = tmp_path / "nasdaq"

    write_snapshot((downloaded,), output_dir=output_dir)

    assert (output_dir / "AAPL.csv").read_text(encoding="utf-8") == (
        "Date,Open,High,Low,Close,Volume\n"
        "2025-01-02,100.0,103.0,99.0,102.0,1000\n"
        "2025-01-03,101.0,104.0,100.0,103.0,2000\n"
    )
    manifest = json.loads((output_dir / "market_prices.json").read_text(encoding="utf-8"))
    assert manifest["schema_version"] == 1
    assert manifest["price_frequency"] == "daily_trading_day"
    assert manifest["nullable_csv_fields"] == ["Volume"]
    assert manifest["series"] == [
        {
            "asset_class": "stocks",
            "csv_file": "AAPL.csv",
            "csv_sha256": "663a8eb451268eb027b8c3d9c4f5830b6ff9d6476acf5acd98c85cb8bf542870",
            "first_trading_date": "2025-01-02",
            "last_trading_date": "2025-01-03",
            "requested_end": "2025-01-03",
            "requested_start": "2025-01-02",
            "response_sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            "retrieved_at": "2026-09-26T00:00:00+00:00",
            "rows": 2,
            "source_url": "https://api.nasdaq.com/api/quote/AAPL/historical?assetclass=stocks",
            "symbol": "AAPL",
        }
    ]

    write_snapshot((downloaded,), output_dir=output_dir)


def test_download_retains_replayable_raw_response_and_verifies_offline_reruns(tmp_path: Path) -> None:
    payload = {
        "status": {"rCode": 200},
        "data": {
            "symbol": "META",
            "totalRecords": 1,
            "tradesTable": {"rows": [_row("01/02/2025", "100", "103", "99", "102", "1000")]},
        },
    }
    downloaded = fetch_historical(
        _client(payload), "META", start=date(2025, 1, 2), end=date(2025, 1, 2), asset_class="stocks"
    )
    output = tmp_path / "snapshot"
    write_snapshot((downloaded,), output_dir=output)
    manifest = json.loads((output / "market_prices.json").read_bytes())
    record = manifest["series"][0]
    raw = output / record["response_file"]
    assert json.loads(raw.read_bytes()) == payload
    assert hashlib.sha256(raw.read_bytes()).hexdigest() == record["response_sha256"]
    verify_snapshot(output, requested_series=(("META", "stocks"),), start=date(2025, 1, 2), end=date(2025, 1, 2))
    write_snapshot((downloaded,), output_dir=output)
    with pytest.raises(NasdaqDownloadError, match="requested"):
        verify_snapshot(output, requested_series=(("META", "stocks"),), start=date(2025, 1, 1), end=date(2025, 1, 2))
    raw.write_bytes(b"{}")
    with pytest.raises(NasdaqDownloadError, match="checksum"):
        verify_snapshot(output)


@pytest.mark.parametrize("change", [{"totalRecords": 2}, {"symbol": "CRM"}])
def test_fetch_rejects_truncated_or_wrong_symbol_responses(change) -> None:
    data = {
        "symbol": "META",
        "totalRecords": 1,
        "tradesTable": {"rows": [_row("01/02/2025", "100", "103", "99", "102", "1000")]},
    }
    data.update(change)
    with pytest.raises(NasdaqDownloadError):
        fetch_historical(
            _client({"status": {"rCode": 200}, "data": data}),
            "META",
            start=date(2025, 1, 2),
            end=date(2025, 1, 2),
            asset_class="stocks",
        )


def _client(response_body: dict[str, object]) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=response_body, request=request)

    return httpx.Client(transport=httpx.MockTransport(handler))


def _row(trading_date: str, open_price: str, high: str, low: str, close: str, volume: str) -> dict[str, str]:
    return {
        "date": trading_date,
        "open": open_price,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
    }
