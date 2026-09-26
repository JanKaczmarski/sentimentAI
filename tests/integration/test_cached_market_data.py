"""Integration coverage for the external cached market-price snapshot."""

import os
from datetime import date
from pathlib import Path

import pytest

from sentiment_system.adapters.outbound.market_data.cached_files import CachedCsvMarketData


@pytest.mark.integration
def test_external_nasdaq_market_snapshot_is_hash_verified_and_queryable() -> None:
    root_value = os.getenv("SENTIMENT_DATA_ROOT")
    if not root_value:
        pytest.skip("SENTIMENT_DATA_ROOT is not configured")
    snapshot = Path(root_value) / "data" / "market_prices" / "nasdaq_2026_09_26"
    if not snapshot.is_dir():
        pytest.skip(f"market-price snapshot is not available: {snapshot}")

    market_data = CachedCsvMarketData(snapshot)
    prices = market_data.get_prices("AAPL")

    assert len(prices) == 2514
    assert prices[0].trading_date == date(2016, 9, 26)
    assert prices[-1].trading_date == date(2026, 9, 25)
    assert market_data.get_prices("AAPL", start=date(2026, 9, 25), end=date(2026, 9, 25)) == (prices[-1],)
