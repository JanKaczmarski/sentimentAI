"""Use case for joining predictions with future benchmark-adjusted market outcomes."""

from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from math import sqrt
from types import MappingProxyType
from uuid import uuid4

from sentiment_system.application.ports.market_data import MarketData, PricePoint
from sentiment_system.application.ports.repositories import EvaluationReportRepository
from sentiment_system.domain.evaluation import (
    EvaluationExclusion,
    EvaluationMetric,
    EvaluationObservation,
    EvaluationReport,
    EvaluationVariant,
)
from sentiment_system.domain.predictions import Prediction

_POSITIVE_KEYWORDS = (
    "growth",
    "exceeded",
    "beat",
    "strong",
    "record",
    "increased",
    "raised guidance",
    "momentum",
    "outperformed",
    "expansion",
    "revenue growth",
    "profit",
    "upside",
    "optimistic",
)
_NEGATIVE_KEYWORDS = (
    "decline",
    "missed",
    "below",
    "weak",
    "loss",
    "decreased",
    "lowered guidance",
    "headwinds",
    "underperformed",
    "contraction",
    "revenue decline",
    "impairment",
    "downside",
    "concerns",
    "risk",
)


@dataclass(frozen=True, slots=True)
class EvaluationScope:
    """Immutable manifest metadata and company-to-sector benchmark routing."""

    corpus_manifest_version: str
    market_snapshot_version: str
    company_benchmarks: Mapping[str, str]

    def __post_init__(self) -> None:
        if not isinstance(self.corpus_manifest_version, str) or not self.corpus_manifest_version.strip():
            raise ValueError("corpus_manifest_version is required")
        if not isinstance(self.market_snapshot_version, str) or not self.market_snapshot_version.strip():
            raise ValueError("market_snapshot_version is required")
        if not isinstance(self.company_benchmarks, Mapping) or not self.company_benchmarks:
            raise ValueError("company_benchmarks is required")
        normalized: dict[str, str] = {}
        for company, benchmark in self.company_benchmarks.items():
            if (
                not isinstance(company, str)
                or not company.strip()
                or not isinstance(benchmark, str)
                or not benchmark.strip()
            ):
                raise ValueError("company_benchmarks must contain non-empty strings")
            normalized[company.upper()] = benchmark.upper()
        object.__setattr__(self, "company_benchmarks", MappingProxyType(normalized))


class EvaluatePredictions:
    """Evaluate supplied predictions without exposing market-provider details."""

    def __init__(
        self,
        market_data: MarketData,
        reports: EvaluationReportRepository,
        *,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._market_data = market_data
        self._reports = reports
        self._now = now or (lambda: datetime.now(timezone.utc))

    def execute(self, *, predictions: Iterable[Prediction], scope: EvaluationScope) -> EvaluationReport:
        """Create and persist one report for explicit predictions and manifest scope."""
        observations: list[EvaluationObservation] = []
        exclusions: list[EvaluationExclusion] = []
        seen_base: set[tuple[str, date, int, str]] = set()
        for prediction in sorted(predictions, key=_prediction_sort_key):
            benchmark = scope.company_benchmarks.get(prediction.company)
            if benchmark is None:
                exclusions.append(_exclusion(prediction, "company_not_in_evaluation_scope"))
                continue
            outcome = self._outcome(prediction, benchmark)
            if isinstance(outcome, str):
                exclusions.append(_exclusion(prediction, outcome))
                continue
            base_key = (prediction.company, prediction.as_of, prediction.forecast_horizon_days, prediction.run_id)
            if base_key not in seen_base:
                seen_base.add(base_key)
                observations.extend(_observations(outcome, _base_variant_scores(prediction)))
            observations.extend(
                _observations(outcome, ((EvaluationVariant.PERSONALIZED, prediction.personalized_sentiment.score),))
            )
        report = EvaluationReport(
            report_id=str(uuid4()),
            created_at=self._now(),
            corpus_manifest_version=scope.corpus_manifest_version,
            market_snapshot_version=scope.market_snapshot_version,
            observations=tuple(observations),
            exclusions=tuple(exclusions),
            metrics=_metrics(observations),
        )
        self._reports.save(report)
        return report

    def _outcome(self, prediction: Prediction, sector_benchmark: str) -> "_Outcome | str":
        subject_prices = self._market_data.get_prices(prediction.company, start=prediction.as_of + timedelta(days=1))
        if len(subject_prices) <= prediction.forecast_horizon_days:
            return "subject_horizon_unavailable"
        entry = subject_prices[0]
        exit_point = subject_prices[prediction.forecast_horizon_days]
        sector = _returns_for_dates(self._market_data.get_prices(sector_benchmark), entry, exit_point)
        spy = _returns_for_dates(self._market_data.get_prices("SPY"), entry, exit_point)
        if spy is None:
            return "sp500_benchmark_unavailable"
        subject_return = _return(entry.close, exit_point.close)
        if sector is None:
            sector = spy
            sector_symbol = "SPY"
            used_spy_fallback = True
        else:
            sector_symbol = sector_benchmark
            used_spy_fallback = False
        return _Outcome(
            prediction=prediction,
            entry_date=entry.trading_date,
            exit_date=exit_point.trading_date,
            subject_return=subject_return,
            sector_symbol=sector_symbol,
            sector_return=sector,
            used_spy_fallback=used_spy_fallback,
            sp500_return=spy,
        )


class EvaluationReportNotFoundError(ValueError):
    """Raised when a requested report does not exist."""


class GetEvaluationReport:
    """Read one immutable evaluation report without exposing persistence details."""

    def __init__(self, reports: EvaluationReportRepository) -> None:
        self._reports = reports

    def execute(self, report_id: str) -> EvaluationReport:
        """Return the report selected by its stable generated identifier."""
        report = self._reports.get(report_id)
        if report is None:
            raise EvaluationReportNotFoundError("evaluation report not found")
        return report


@dataclass(frozen=True, slots=True)
class _Outcome:
    prediction: Prediction
    entry_date: date
    exit_date: date
    subject_return: float
    sector_symbol: str
    sector_return: float
    used_spy_fallback: bool
    sp500_return: float


def _observations(
    outcome: _Outcome, scores: tuple[tuple[EvaluationVariant, float], ...]
) -> tuple[EvaluationObservation, ...]:
    observations = []
    for variant, score in scores:
        observations.append(
            _observation(
                outcome,
                variant,
                score,
                benchmark_mode="sector",
                benchmark_symbol=outcome.sector_symbol,
                benchmark_return=outcome.sector_return,
                used_spy_fallback=outcome.used_spy_fallback,
            )
        )
        observations.append(
            _observation(
                outcome,
                variant,
                score,
                benchmark_mode="sp500",
                benchmark_symbol="SPY",
                benchmark_return=outcome.sp500_return,
                used_spy_fallback=False,
            )
        )
    return tuple(observations)


def _observation(
    outcome: _Outcome,
    variant: EvaluationVariant,
    score: float,
    *,
    benchmark_mode: str,
    benchmark_symbol: str,
    benchmark_return: float,
    used_spy_fallback: bool,
) -> EvaluationObservation:
    return EvaluationObservation(
        company=outcome.prediction.company,
        prediction_as_of=outcome.prediction.as_of,
        entry_date=outcome.entry_date,
        exit_date=outcome.exit_date,
        forecast_horizon_days=outcome.prediction.forecast_horizon_days,
        variant=variant,
        benchmark_mode=benchmark_mode,
        benchmark_symbol=benchmark_symbol,
        used_spy_fallback=used_spy_fallback,
        predicted_score=score,
        subject_return=outcome.subject_return,
        benchmark_return=benchmark_return,
        excess_return=round(outcome.subject_return - benchmark_return, 12),
    )


def _base_variant_scores(prediction: Prediction) -> tuple[tuple[EvaluationVariant, float], ...]:
    return (
        (EvaluationVariant.BASE, prediction.base_sentiment.score),
        (EvaluationVariant.KEYWORD, _keyword_score(prediction)),
        (EvaluationVariant.NO_SIGNAL, 0.5),
    )


def _keyword_score(prediction: Prediction) -> float:
    evidence = " ".join(item.excerpt for item in prediction.evidence).casefold()
    positive = sum(phrase in evidence for phrase in _POSITIVE_KEYWORDS)
    negative = sum(phrase in evidence for phrase in _NEGATIVE_KEYWORDS)
    total = positive + negative
    return 0.5 if total == 0 else 0.5 + (positive - negative) / (2 * total)


def _returns_for_dates(prices: tuple[PricePoint, ...], entry: PricePoint, exit_point: PricePoint) -> float | None:
    close_by_date = {point.trading_date: point.close for point in prices}
    entry_close = close_by_date.get(entry.trading_date)
    exit_close = close_by_date.get(exit_point.trading_date)
    return None if entry_close is None or exit_close is None else _return(entry_close, exit_close)


def _return(entry_close: float, exit_close: float) -> float:
    return round(exit_close / entry_close - 1, 12)


def _exclusion(prediction: Prediction, reason: str) -> EvaluationExclusion:
    return EvaluationExclusion(
        company=prediction.company,
        prediction_as_of=prediction.as_of,
        forecast_horizon_days=prediction.forecast_horizon_days,
        reason=reason,
    )


def _prediction_sort_key(prediction: Prediction) -> tuple[str, date, int, str, str]:
    return (
        prediction.company,
        prediction.as_of,
        prediction.forecast_horizon_days,
        prediction.run_id,
        prediction.user_id or "",
    )


def _metrics(observations: list[EvaluationObservation]) -> tuple[EvaluationMetric, ...]:
    groups: dict[tuple[EvaluationVariant, str, int], list[EvaluationObservation]] = defaultdict(list)
    for observation in observations:
        groups[(observation.variant, observation.benchmark_mode, observation.forecast_horizon_days)].append(observation)
    return tuple(
        _metric(variant, benchmark_mode, horizon, values)
        for (variant, benchmark_mode, horizon), values in sorted(
            groups.items(), key=lambda item: (item[0][0].value, item[0][1], item[0][2])
        )
    )


def _metric(
    variant: EvaluationVariant,
    benchmark_mode: str,
    horizon: int,
    observations: list[EvaluationObservation],
) -> EvaluationMetric:
    directional = [
        observation
        for observation in observations
        if _score_direction(observation.predicted_score) != 0 and _return_direction(observation.excess_return) != 0
    ]
    hits = sum(_score_direction(item.predicted_score) == _return_direction(item.excess_return) for item in directional)
    return EvaluationMetric(
        variant=variant,
        benchmark_mode=benchmark_mode,
        forecast_horizon_days=horizon,
        observation_count=len(observations),
        directional_sample_size=len(directional),
        directional_hit_rate=None if not directional else hits / len(directional),
        spearman_correlation=_spearman(
            tuple(item.predicted_score for item in observations), tuple(item.excess_return for item in observations)
        ),
    )


def _score_direction(value: float) -> int:
    if value > 0.6:
        return 1
    if value < 0.4:
        return -1
    return 0


def _return_direction(value: float) -> int:
    if value > 0:
        return 1
    if value < 0:
        return -1
    return 0


def _spearman(scores: tuple[float, ...], returns: tuple[float, ...]) -> float | None:
    if len(scores) < 2:
        return None
    score_ranks = _average_ranks(scores)
    return_ranks = _average_ranks(returns)
    score_mean = sum(score_ranks) / len(score_ranks)
    return_mean = sum(return_ranks) / len(return_ranks)
    numerator = sum((score - score_mean) * (value - return_mean) for score, value in zip(score_ranks, return_ranks))
    score_variance = sum((score - score_mean) ** 2 for score in score_ranks)
    return_variance = sum((value - return_mean) ** 2 for value in return_ranks)
    if score_variance == 0 or return_variance == 0:
        return None
    return numerator / sqrt(score_variance * return_variance)


def _average_ranks(values: tuple[float, ...]) -> tuple[float, ...]:
    ranks = [0.0] * len(values)
    ordered = sorted(enumerate(values), key=lambda item: item[1])
    index = 0
    while index < len(ordered):
        end = index + 1
        while end < len(ordered) and ordered[end][1] == ordered[index][1]:
            end += 1
        rank = (index + 1 + end) / 2
        for original_index, _ in ordered[index:end]:
            ranks[original_index] = rank
        index = end
    return tuple(ranks)
