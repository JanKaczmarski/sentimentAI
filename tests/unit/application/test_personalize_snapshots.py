"""Tests for deterministic Investment Thesis personalization."""

from datetime import date

import pytest

from sentiment_system.adapters.outbound.persistence.in_memory import InMemorySnapshotRepository
from sentiment_system.application.use_cases.personalize_snapshots import PersonalizeSnapshots
from sentiment_system.domain.investment_thesis import (
    InvestmentHorizon,
    InvestmentStyle,
    InvestmentThesis,
    RiskTolerance,
)
from sentiment_system.domain.predictions import CompanySentimentSnapshot, SnapshotWindow
from sentiment_system.domain.sentiment import SentimentLabel, SentimentScore


@pytest.mark.parametrize(
    ("horizon", "style", "expected"),
    [
        (InvestmentHorizon.SHORT_TERM, InvestmentStyle.ACTIVE, 0.26),
        (InvestmentHorizon.SHORT_TERM, InvestmentStyle.PASSIVE, 0.34),
        (InvestmentHorizon.LONG_TERM, InvestmentStyle.ACTIVE, 0.46),
        (InvestmentHorizon.LONG_TERM, InvestmentStyle.PASSIVE, 0.54),
    ],
)
def test_personalization_applies_horizon_and_style_weights(
    horizon: InvestmentHorizon,
    style: InvestmentStyle,
    expected: float,
) -> None:
    result = _personalizer().execute(
        company="AAPL",
        as_of=date(2025, 2, 1),
        thesis=_thesis(horizon=horizon, style=style),
        run_id="run-1",
    )

    assert result.personalized_sentiment.score == pytest.approx(expected)
    assert result.rule_version == "aggregation-personalization-v1"
    assert result.run_id == "run-1"


def test_personalization_applies_risk_thresholds_and_preserves_evidence() -> None:
    result = _personalizer().execute(
        company="AAPL",
        as_of=date(2025, 2, 1),
        thesis=_thesis(risk=RiskTolerance.HIGH),
        run_id="run-1",
    )

    assert result.personalized_sentiment.label is SentimentLabel.NEUTRAL
    assert result.base_sentiment.score == pytest.approx(0.5)
    assert [item.chunk_id for item in result.evidence] == ["chunk-90", "chunk-365"]


def _personalizer() -> PersonalizeSnapshots:
    snapshots = InMemorySnapshotRepository(
        (
            _snapshot(SnapshotWindow.THIRTY_DAYS, 0.2, "chunk-30"),
            _snapshot(SnapshotWindow.NINETY_DAYS, 0.4, "chunk-90"),
            _snapshot(SnapshotWindow.YEAR, 0.6, "chunk-365"),
        )
    )
    return PersonalizeSnapshots(snapshots)


def _snapshot(window: SnapshotWindow, score: float, chunk_id: str) -> CompanySentimentSnapshot:
    from sentiment_system.domain.predictions import PredictionEvidence

    return CompanySentimentSnapshot(
        company="AAPL",
        as_of=date(2025, 2, 1),
        window_days=window,
        sentiment=SentimentScore(score=score, confidence=0.8),
        evidence=(
            PredictionEvidence(
                chunk_id=chunk_id,
                published_at=date(2025, 1, 1),
                importance_score=0.9,
                excerpt=chunk_id,
            ),
        ),
        run_id="run-1",
    )


def _thesis(
    *,
    horizon: InvestmentHorizon = InvestmentHorizon.LONG_TERM,
    style: InvestmentStyle = InvestmentStyle.PASSIVE,
    risk: RiskTolerance = RiskTolerance.MEDIUM,
) -> InvestmentThesis:
    return InvestmentThesis(
        thesis_id="thesis-1",
        user_id="user-1",
        companies=("AAPL",),
        risk_tolerance=risk,
        investment_horizon=horizon,
        investment_style=style,
    )
