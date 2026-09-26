"""Tests for deterministic prediction evaluation against cached prices."""

from datetime import date, datetime, timezone

from sentiment_system.adapters.outbound.market_data.fake import InMemoryMarketData
from sentiment_system.adapters.outbound.persistence.in_memory import InMemoryEvaluationReportRepository
from sentiment_system.application.ports.market_data import PricePoint
from sentiment_system.application.use_cases.evaluate_predictions import EvaluatePredictions, EvaluationScope, _spearman
from sentiment_system.domain.evaluation import EvaluationVariant
from sentiment_system.domain.predictions import Prediction, PredictionEvidence, SnapshotWindow
from sentiment_system.domain.sentiment import PersonalizedSentiment, SentimentLabel, SentimentScore


def test_evaluate_predictions_aligns_after_as_of_and_reports_all_variants() -> None:
    reports = InMemoryEvaluationReportRepository()
    evaluator = EvaluatePredictions(_market_data(), reports, now=lambda: datetime(2026, 9, 26, tzinfo=timezone.utc))

    report = evaluator.execute(predictions=(_prediction(),), scope=_scope())

    assert reports.get(report.report_id) == report
    assert {observation.variant for observation in report.observations} == set(EvaluationVariant)
    assert len(report.observations) == 8
    sector_base = next(
        observation
        for observation in report.observations
        if observation.variant is EvaluationVariant.BASE and observation.benchmark_mode == "sector"
    )
    assert sector_base.entry_date == date(2025, 1, 6)
    assert sector_base.exit_date == date(2025, 1, 7)
    assert sector_base.subject_return == 0.1
    assert sector_base.benchmark_symbol == "XLK"
    assert sector_base.excess_return == 0.05
    assert sector_base.used_spy_fallback is False

    keyword = next(
        observation
        for observation in report.observations
        if observation.variant is EvaluationVariant.KEYWORD and observation.benchmark_mode == "sector"
    )
    assert keyword.predicted_score == 0.75
    base_metric = next(
        metric
        for metric in report.metrics
        if metric.variant is EvaluationVariant.BASE and metric.benchmark_mode == "sector"
    )
    assert base_metric.directional_sample_size == 1
    assert base_metric.directional_hit_rate == 1.0
    no_signal_metric = next(
        metric
        for metric in report.metrics
        if metric.variant is EvaluationVariant.NO_SIGNAL and metric.benchmark_mode == "sector"
    )
    assert no_signal_metric.directional_sample_size == 0
    assert no_signal_metric.directional_hit_rate is None
    assert no_signal_metric.spearman_correlation is None


def test_evaluate_predictions_uses_spy_when_the_sector_benchmark_is_unavailable() -> None:
    market_data = InMemoryMarketData(
        (
            PricePoint("AAPL", date(2025, 1, 6), 100),
            PricePoint("AAPL", date(2025, 1, 7), 110),
            PricePoint("SPY", date(2025, 1, 6), 100),
            PricePoint("SPY", date(2025, 1, 7), 102),
        )
    )

    report = EvaluatePredictions(market_data, InMemoryEvaluationReportRepository()).execute(
        predictions=(_prediction(),), scope=_scope()
    )

    observation = next(
        item
        for item in report.observations
        if item.variant is EvaluationVariant.BASE and item.benchmark_mode == "sector"
    )
    assert observation.benchmark_symbol == "SPY"
    assert observation.used_spy_fallback is True
    assert observation.excess_return == 0.08


def test_evaluate_predictions_retains_an_incomplete_horizon_as_an_exclusion() -> None:
    report = EvaluatePredictions(_market_data(), InMemoryEvaluationReportRepository()).execute(
        predictions=(_prediction(forecast_horizon_days=5),), scope=_scope()
    )

    assert report.observations == ()
    assert len(report.exclusions) == 1
    assert report.exclusions[0].reason == "subject_horizon_unavailable"
    assert report.exclusions[0].prediction_as_of == date(2025, 1, 3)


def test_spearman_uses_average_ranks_for_tied_scores() -> None:
    assert _spearman((0.2, 0.2, 0.8), (-0.1, -0.1, 0.1)) == 1.0
    assert _spearman((0.5, 0.5), (0.1, -0.1)) is None


def _scope() -> EvaluationScope:
    return EvaluationScope(
        corpus_manifest_version="fixture-corpus-v1",
        market_snapshot_version="fixture-prices-v1",
        company_benchmarks={"AAPL": "XLK"},
    )


def _market_data() -> InMemoryMarketData:
    return InMemoryMarketData(
        (
            PricePoint("AAPL", date(2025, 1, 6), 100),
            PricePoint("AAPL", date(2025, 1, 7), 110),
            PricePoint("XLK", date(2025, 1, 6), 100),
            PricePoint("XLK", date(2025, 1, 7), 105),
            PricePoint("SPY", date(2025, 1, 6), 100),
            PricePoint("SPY", date(2025, 1, 7), 102),
        )
    )


def _prediction(*, forecast_horizon_days: int = 1) -> Prediction:
    return Prediction(
        company="AAPL",
        as_of=date(2025, 1, 3),
        lookback_days=SnapshotWindow.NINETY_DAYS,
        forecast_horizon_days=forecast_horizon_days,
        base_sentiment=SentimentScore(score=0.8, confidence=0.7),
        personalized_sentiment=PersonalizedSentiment(
            score=0.2,
            confidence=0.8,
            label=SentimentLabel.NEGATIVE,
        ),
        confidence=0.8,
        evidence=(
            PredictionEvidence(
                chunk_id="chunk-1",
                published_at=date(2025, 1, 2),
                sentiment=SentimentScore(score=0.8, confidence=0.7),
                importance_score=0.9,
                excerpt="Revenue growth was strong despite risk.",
            ),
        ),
        run_id="run-1",
        user_id="user-1",
    )
