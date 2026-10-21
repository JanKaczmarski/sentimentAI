"""Contract coverage for the offline cached market-data adapter."""

import hashlib
import json
from datetime import date
from pathlib import Path

import httpx

from scripts.download_nasdaq_historical import fetch_historical, verify_snapshot, write_snapshot
from sentiment_system.adapters.outbound.market_data.cached_files import CachedCsvMarketData
from sentiment_system.application.ports.market_data import MarketData, PricePoint


def test_cached_csv_market_data_implements_market_data_port(tmp_path: Path) -> None:
    content = "Date,Open,High,Low,Close,Volume\n2025-01-02,100,103,99,102,1000\n"
    (tmp_path / "AAPL.csv").write_text(content, encoding="utf-8")
    (tmp_path / "market_prices.json").write_text(
        json.dumps(
            {
                "csv_fields": ["Date", "Open", "High", "Low", "Close", "Volume"],
                "nullable_csv_fields": ["Volume"],
                "price_frequency": "daily_trading_day",
                "provider": "example",
                "return_price_field": "Close",
                "schema_version": 1,
                "series": [
                    {
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
                ],
            }
        ),
        encoding="utf-8",
    )

    adapter = CachedCsvMarketData(tmp_path)

    assert isinstance(adapter, MarketData)
    assert adapter.get_prices("AAPL") == (PricePoint("AAPL", date(2025, 1, 2), 102.0),)


def test_raw_response_snapshot_remains_a_provider_neutral_offline_market_data_adapter(tmp_path, monkeypatch):
    def serve(request):
        return httpx.Response(
            200,
            json={
                "status": {"rCode": 200},
                "data": {
                    "symbol": "META",
                    "totalRecords": 1,
                    "tradesTable": {
                        "rows": [
                            {
                                "date": "01/02/2025",
                                "open": "100",
                                "high": "103",
                                "low": "99",
                                "close": "102",
                                "volume": "N/A",
                            }
                        ]
                    },
                },
            },
        )

    with httpx.Client(transport=httpx.MockTransport(serve)) as client:
        series = fetch_historical(client, "META", start=date(2025, 1, 2), end=date(2025, 1, 2), asset_class="stocks")
    output = tmp_path / "snapshot"
    write_snapshot((series,), output_dir=output)
    monkeypatch.setattr(
        httpx.Client, "request", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("network access"))
    )
    verify_snapshot(output)
    adapter = CachedCsvMarketData(output)
    assert isinstance(adapter, MarketData)
    assert adapter.get_prices("META") == (PricePoint("META", date(2025, 1, 2), 102.0),)
