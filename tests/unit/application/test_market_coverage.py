"""Coverage and prediction evaluation must use the same strictly-forward outcomes."""

from datetime import date

import pytest

from sentiment_system.adapters.outbound.market_data.fake import InMemoryMarketData
from sentiment_system.application.ports.market_data import PricePoint
from sentiment_system.application.use_cases.market_coverage import (
    CoverageSource,
    MarketOutcomeResolver,
    build_market_coverage,
)


def _market(*, missing_sector=False, missing_spy=False):
    dates = (date(2025, 1, 3), date(2025, 1, 6), date(2025, 1, 7), date(2025, 1, 8))
    return InMemoryMarketData(
        PricePoint(symbol, day, 100 + index * step)
        for symbol, step in (("META", 10), ("XLC", 5), ("SPY", 2))
        for index, day in enumerate(dates)
        if not (missing_sector and symbol == "XLC" and index == 2)
        and not (missing_spy and symbol == "SPY" and index == 2)
    )


def test_coverage_aligns_strictly_after_weekend_and_counts_h_not_h_minus_one():
    resolver = MarketOutcomeResolver(_market())
    friday = resolver.resolve("META", date(2025, 1, 3), 1, "XLC")
    weekend = resolver.resolve("META", date(2025, 1, 5), 1, "XLC")
    assert friday == weekend
    assert friday.entry_date == date(2025, 1, 6)
    assert friday.exit_date == date(2025, 1, 7)
    assert friday.subject_return == round(120 / 110 - 1, 12)
    assert resolver.resolve("META", date(2025, 1, 7), 1, "XLC").reason == "subject_horizon_unavailable"
    assert resolver.resolve("META", date(2025, 1, 6), 1, "XLC").exit_date == date(2025, 1, 8)


def test_coverage_uses_same_date_spy_fallback_but_requires_sensitivity_endpoints():
    fallback = MarketOutcomeResolver(_market(missing_sector=True)).resolve("META", date(2025, 1, 3), 1, "XLC")
    assert fallback.reason is None
    assert fallback.used_spy_fallback
    assert fallback.sector_symbol == "SPY"
    assert fallback.sector_return == fallback.sp500_return
    missing = MarketOutcomeResolver(_market(missing_spy=True)).resolve("META", date(2025, 1, 3), 1, "XLC")
    assert missing.reason == "sp500_benchmark_unavailable"
    assert missing.entry_date == date(2025, 1, 6)
    assert missing.exit_date == date(2025, 1, 7)


def test_coverage_retains_every_source_horizon_and_distinguishes_entry_from_as_of_boundary():
    sources = (
        CoverageSource("first", "META", date(2025, 1, 3)),
        CoverageSource("second", "META", date(2025, 1, 7)),
    )
    result = build_market_coverage(
        _market(),
        sources=sources,
        company_benchmarks={"META": "XLC"},
        window_start=date(2025, 1, 3),
        cutoff=date(2025, 1, 7),
        development_ends=date(2025, 1, 3),
    )
    assert len(result["outcomes"]) == 10
    assert {row["horizon"] for row in result["outcomes"]} == {1, 5, 20, 60, 252}
    summary = next(row for row in result["summary"] if row["horizon"] == 1)
    assert summary["all"]["complete"] == 1
    assert summary["held_out"]["unavailable"] == 1
    assert summary["latest_complete_entry"] == "2025-01-07"
    assert summary["latest_complete_as_of"] == "2025-01-06"
    assert summary["as_of_intervals"] == [
        {"start": "2025-01-03", "end": "2025-01-06", "reason": None},
        {"start": "2025-01-07", "end": "2025-01-08", "reason": "subject_horizon_unavailable"},
    ]
    assert all(row["reason"] == "subject_horizon_unavailable" for row in result["outcomes"] if row["horizon"] != 1)


def test_interior_benchmark_gap_is_preserved_in_boundary_intervals():
    result = build_market_coverage(
        _market(missing_spy=True),
        sources=(CoverageSource("first", "META", date(2025, 1, 3)),),
        company_benchmarks={"META": "XLC"},
        window_start=date(2025, 1, 3),
        cutoff=date(2025, 1, 7),
        development_ends=date(2025, 1, 3),
    )
    summary = next(row for row in result["summary"] if row["horizon"] == 1)
    assert summary["as_of_intervals"][0]["reason"] == "sp500_benchmark_unavailable"
    assert summary["all"]["exclusion_reasons"] == {"sp500_benchmark_unavailable": 1}


@pytest.mark.parametrize("horizon", [0, -1, True, 1.5])
def test_outcome_rejects_invalid_horizons(horizon):
    with pytest.raises(ValueError, match="horizon"):
        MarketOutcomeResolver(_market()).resolve("META", date(2025, 1, 3), horizon, "XLC")
