"""Tests for prediction generation and user-scoped history."""

from datetime import date
from hashlib import sha256
from uuid import uuid4

from sentiment_system.adapters.outbound.persistence.in_memory import (
    InMemoryInvestmentThesisRepository,
    InMemoryPredictionRepository,
    InMemorySnapshotRepository,
    InMemoryUserAccountRepository,
)
from sentiment_system.application.use_cases.generate_prediction import GeneratePrediction
from sentiment_system.application.use_cases.manage_investment_theses import ManageInvestmentTheses
from sentiment_system.domain.accounts import UserAccount
from sentiment_system.domain.investment_thesis import InvestmentHorizon, InvestmentStyle, RiskTolerance
from sentiment_system.domain.predictions import CompanySentimentSnapshot, PredictionEvidence, SnapshotWindow
from sentiment_system.domain.sentiment import SentimentScore


def test_generate_prediction_persists_user_scoped_evidence_and_history() -> None:
    accounts = InMemoryUserAccountRepository()
    account = UserAccount(
        user_id=uuid4(),
        email="investor@example.com",
        username="investor",
        api_key_digest=sha256(b"key").hexdigest(),
    )
    accounts.save(account)
    thesis_repository = InMemoryInvestmentThesisRepository()
    theses = ManageInvestmentTheses(accounts, thesis_repository)
    theses.create(
        api_key="key",
        companies=("AAPL",),
        risk_tolerance=RiskTolerance.MEDIUM,
        investment_horizon=InvestmentHorizon.LONG_TERM,
        investment_style=InvestmentStyle.PASSIVE,
        description=None,
    )
    snapshots = InMemorySnapshotRepository(
        _snapshots(thesis_run="run-1"),
    )
    predictions = InMemoryPredictionRepository()

    result = GeneratePrediction(accounts, thesis_repository, snapshots, predictions).execute(
        api_key="key",
        company="AAPL",
        as_of=date(2025, 2, 1),
        forecast_horizon_days=20,
    )

    assert result.user_id == str(account.user_id)
    assert result.personalized_sentiment.score == 0.54
    assert len(result.evidence) == 2
    assert predictions.list_for_company("AAPL") == (result,)


def _snapshots(*, thesis_run: str) -> tuple[CompanySentimentSnapshot, ...]:
    return tuple(
        CompanySentimentSnapshot(
            company="AAPL",
            as_of=date(2025, 2, 1),
            window_days=window,
            sentiment=SentimentScore(score=score, confidence=0.8),
            evidence=(
                PredictionEvidence(
                    chunk_id=f"chunk-{window}",
                    published_at=date(2025, 1, 1),
                    importance_score=0.9,
                    excerpt=f"Evidence {window}",
                ),
            ),
            run_id=thesis_run,
        )
        for window, score in ((SnapshotWindow.NINETY_DAYS, 0.4), (SnapshotWindow.YEAR, 0.6))
    )
