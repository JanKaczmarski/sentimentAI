"""Port for loading cached historical prices and benchmark data."""

from dataclasses import dataclass
from datetime import date
from math import isfinite
from typing import Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class PricePoint:
    """One historical close used by leakage-safe evaluation."""

    symbol: str
    trading_date: date
    close: float

    def __post_init__(self) -> None:
        if not isinstance(self.symbol, str) or not self.symbol.strip():
            raise ValueError("symbol is required")
        if not isinstance(self.trading_date, date):
            raise ValueError("trading_date must be a date")
        if not isinstance(self.close, (int, float)) or isinstance(self.close, bool) or not isfinite(self.close):
            raise ValueError("close must be finite")
        if self.close <= 0:
            raise ValueError("close must be positive")


@runtime_checkable
class MarketData(Protocol):
    """Load historical prices without exposing a market-data SDK."""

    def get_prices(
        self,
        symbol: str,
        *,
        start: date | None = None,
        end: date | None = None,
    ) -> tuple[PricePoint, ...]:
        """Return prices sorted by trading date, inclusive of bounds."""
