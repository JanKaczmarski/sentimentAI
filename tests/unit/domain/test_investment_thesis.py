"""Tests for Investment Thesis value objects."""

from sentiment_system.domain.investment_thesis import (
    InvestmentHorizon,
    InvestmentStyle,
    InvestmentThesis,
    RiskTolerance,
)


def test_short_term_thesis_uses_short_lookback() -> None:
    thesis = InvestmentThesis(
        user_id="user-1",
        companies=("AAPL",),
        risk_tolerance=RiskTolerance.MEDIUM,
        investment_horizon=InvestmentHorizon.SHORT_TERM,
        investment_style=InvestmentStyle.ACTIVE,
    )

    assert thesis.lookback_days == 30


def test_long_term_thesis_uses_long_lookback() -> None:
    thesis = InvestmentThesis(
        user_id="user-1",
        companies=("AAPL", "MSFT"),
        risk_tolerance=RiskTolerance.LOW,
        investment_horizon=InvestmentHorizon.LONG_TERM,
        investment_style=InvestmentStyle.PASSIVE,
    )

    assert thesis.lookback_days == 365
