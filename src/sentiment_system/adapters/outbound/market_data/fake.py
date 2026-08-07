"""Deterministic in-memory market-data adapter for tests."""

from collections.abc import Iterable
from datetime import date

from sentiment_system.application.ports.market_data import PricePoint


class InMemoryMarketData:
    """Store and query a deterministic set of historical price points."""

    def __init__(self, prices: Iterable[PricePoint] = ()) -> None:
        self._prices: dict[tuple[str, date], PricePoint] = {}
        for price in prices:
            self._prices[(price.symbol, price.trading_date)] = price

    def add(self, price: PricePoint) -> None:
        """Insert or replace one price point."""
        self._prices[(price.symbol, price.trading_date)] = price

    def get_prices(
        self,
        symbol: str,
        *,
        start: date | None = None,
        end: date | None = None,
    ) -> tuple[PricePoint, ...]:
        """Return matching prices sorted by trading date with inclusive bounds."""
        prices = (
            price
            for price in self._prices.values()
            if price.symbol == symbol
            and (start is None or price.trading_date >= start)
            and (end is None or price.trading_date <= end)
        )
        return tuple(sorted(prices, key=lambda item: item.trading_date))
