"""Provider-neutral forward outcomes and source-publication coverage (no scoring)."""

from bisect import bisect_right
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from typing import Any

from sentiment_system.application.ports.market_data import MarketData, PricePoint

HORIZONS = (1, 5, 20, 60, 252)
ALIGNMENT_VERSION = "strict-after-close-v1"


def evaluation_protocol() -> dict[str, Any]:
    """Pre-registered rules; acquisition never tunes them to outcome availability."""
    return {
        "alignment_version": ALIGNMENT_VERSION,
        "entry": "first_subject_trading_day_strictly_after_as_of",
        "exit": "subject_trading_day_at_entry_index_plus_horizon",
        "return": "Close[t+h] / Close[t] - 1",
        "return_price_field": "Close",
        "price_basis": "provider_reported_Close; no dividend-adjusted total-return claim",
        "horizons": list(HORIZONS),
        "benchmark_endpoints": "exact_subject_entry_and_exit_dates",
        "sector_unavailable": "SPY_fallback",
        "sp500_sensitivity": "SPY_required_for_each_complete_observation",
        "missing_future_prices": "retain_source_and_explicit_unavailable_outcome; never_shift_source_cutoff",
        "coverage_unit": "source_publication; not predictions, metric_samples or an evaluation_sampling_schedule",
    }


@dataclass(frozen=True, slots=True)
class MarketOutcome:
    """Explicit endpoints survive an exclusion; absent future prices remain absent."""

    reason: str | None = None
    entry_date: date | None = None
    exit_date: date | None = None
    subject_return: float | None = None
    sector_symbol: str | None = None
    sector_return: float | None = None
    sp500_return: float | None = None
    used_spy_fallback: bool = False


class MarketOutcomeResolver:
    """Share decision 0006's alignment/fallback rules with prediction evaluation."""

    def __init__(self, market_data: MarketData) -> None:
        self._market_data = market_data
        self._series: dict[str, tuple[PricePoint, ...]] = {}
        self._dates: dict[str, tuple[date, ...]] = {}
        self._closes: dict[str, dict[date, float]] = {}

    def prices(self, symbol: str) -> tuple[PricePoint, ...]:
        """Cache immutable series once, avoiding repeated full-history scans."""
        if symbol not in self._series:
            values = self._market_data.get_prices(symbol)
            self._series[symbol] = values
            self._dates[symbol] = tuple(point.trading_date for point in values)
            self._closes[symbol] = {point.trading_date: point.close for point in values}
        return self._series[symbol]

    def resolve(self, company: str, as_of: date, horizon: int, sector_benchmark: str) -> MarketOutcome:
        """Entry is strictly after as_of; exit is h subject trading sessions later."""
        if isinstance(horizon, bool) or not isinstance(horizon, int) or horizon <= 0:
            raise ValueError("horizon must be a positive integer")
        subject = self.prices(company)
        index = bisect_right(self._dates[company], as_of)
        entry = subject[index] if index < len(subject) else None
        if index + horizon >= len(subject):
            return MarketOutcome(reason="subject_horizon_unavailable", entry_date=entry.trading_date if entry else None)
        assert entry is not None
        exit_point = subject[index + horizon]
        spy = self._return_for_dates("SPY", entry.trading_date, exit_point.trading_date)
        if spy is None:
            return MarketOutcome(
                reason="sp500_benchmark_unavailable", entry_date=entry.trading_date, exit_date=exit_point.trading_date
            )
        sector = self._return_for_dates(sector_benchmark, entry.trading_date, exit_point.trading_date)
        fallback = sector is None
        return MarketOutcome(
            entry_date=entry.trading_date,
            exit_date=exit_point.trading_date,
            subject_return=_return(entry.close, exit_point.close),
            sector_symbol="SPY" if fallback else sector_benchmark,
            sector_return=spy if fallback else sector,
            sp500_return=spy,
            used_spy_fallback=fallback,
        )

    def _return_for_dates(self, symbol: str, entry: date, exit_date: date) -> float | None:
        self.prices(symbol)
        values = self._closes[symbol]
        return _return(values[entry], values[exit_date]) if entry in values and exit_date in values else None


def _return(entry: float, exit_close: float) -> float:
    return round(exit_close / entry - 1, 12)


@dataclass(frozen=True, slots=True)
class CoverageSource:
    """A manifest record, not a fabricated prediction or a sampling schedule."""

    record_id: str
    company: str
    published_at: date


def build_market_coverage(
    market_data: MarketData,
    *,
    sources: Sequence[CoverageSource],
    company_benchmarks: Mapping[str, str],
    window_start: date,
    cutoff: date,
    development_ends: date,
) -> dict[str, Any]:
    """Account for every source/horizon, with daily boundary intervals and gaps."""
    if len({source.record_id for source in sources}) != len(sources):
        raise ValueError("coverage source IDs must be unique")
    if any(
        source.company not in company_benchmarks or not window_start <= source.published_at <= cutoff
        for source in sources
    ):
        raise ValueError("coverage source is outside the frozen scope")
    resolver = MarketOutcomeResolver(market_data)
    rows = []
    summary = []
    calendars = {}
    spy_dates = {point.trading_date for point in resolver.prices("SPY")}
    for company, benchmark in sorted(company_benchmarks.items()):
        prices = resolver.prices(company)
        dates = {point.trading_date for point in prices}
        calendars[company] = {
            "subject_sessions_missing_from_spy": sorted(day.isoformat() for day in dates - spy_dates),
            "spy_sessions_missing_from_subject": sorted(day.isoformat() for day in spy_dates - dates),
        }
        for horizon in HORIZONS:
            company_rows = []
            for source in sorted(
                (item for item in sources if item.company == company),
                key=lambda item: (item.published_at, item.record_id),
            ):
                outcome = resolver.resolve(company, source.published_at, horizon, benchmark)
                values = asdict(outcome)
                for field in ("entry_date", "exit_date"):
                    values[field] = values[field].isoformat() if values[field] else None
                row = {
                    "record_id": source.record_id,
                    "company": company,
                    "published_at": source.published_at.isoformat(),
                    "horizon": horizon,
                    "partition": "development" if source.published_at <= development_ends else "held_out",
                    **values,
                }
                company_rows.append(row)
            rows.extend(company_rows)
            intervals: list[dict[str, Any]] = []
            latest_as_of = latest_entry = None
            # Price-supported boundaries are separate from the frozen text cutoff.
            day = window_start
            last = max(prices[-1].trading_date, cutoff) if prices else cutoff
            while day <= last:
                outcome = resolver.resolve(company, day, horizon, benchmark)
                if intervals and intervals[-1]["reason"] == outcome.reason:
                    intervals[-1]["end"] = day.isoformat()
                else:
                    intervals.append({"start": day.isoformat(), "end": day.isoformat(), "reason": outcome.reason})
                if outcome.reason is None:
                    latest_as_of = day.isoformat()
                    latest_entry = outcome.entry_date.isoformat() if outcome.entry_date else None
                day += timedelta(days=1)
            summary.append(
                {
                    "company": company,
                    "sector_benchmark": benchmark,
                    "horizon": horizon,
                    "latest_complete_as_of": latest_as_of,
                    "latest_complete_entry": latest_entry,
                    "as_of_intervals": intervals,
                    **{
                        partition: _counts(
                            company_rows
                            if partition == "all"
                            else [row for row in company_rows if row["partition"] == partition]
                        )
                        for partition in ("all", "development", "held_out")
                    },
                }
            )
    return {
        "alignment_version": ALIGNMENT_VERSION,
        "horizons": list(HORIZONS),
        "outcomes": rows,
        "summary": summary,
        "calendar_differences": calendars,
    }


def _counts(rows: list[dict[str, Any]]) -> dict[str, Any]:
    complete = [row for row in rows if row["reason"] is None]
    return {
        "total": len(rows),
        "complete": len(complete),
        "unavailable": len(rows) - len(complete),
        "spy_fallback": sum(row["used_spy_fallback"] for row in complete),
        "exclusion_reasons": dict(sorted(Counter(row["reason"] for row in rows if row["reason"] is not None).items())),
        "first_complete_publication": min((row["published_at"] for row in complete), default=None),
        "last_complete_publication": max((row["published_at"] for row in complete), default=None),
    }
