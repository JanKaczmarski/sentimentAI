"""Immutable market-outcome observations and reproducible evaluation reports."""

from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum
from math import isfinite


class EvaluationVariant(str, Enum):
    """Independent prediction and baseline values compared to market outcomes."""

    BASE = "base"
    PERSONALIZED = "personalized"
    KEYWORD = "keyword-baseline-v1"
    NO_SIGNAL = "no-signal-v1"


@dataclass(frozen=True, slots=True)
class EvaluationObservation:
    """One successful prediction-to-market comparison for one variant and benchmark."""

    company: str
    prediction_as_of: date
    entry_date: date
    exit_date: date
    forecast_horizon_days: int
    variant: EvaluationVariant
    benchmark_mode: str
    benchmark_symbol: str
    used_spy_fallback: bool
    predicted_score: float
    subject_return: float
    benchmark_return: float
    excess_return: float

    def __post_init__(self) -> None:
        _required_string("company", self.company)
        _required_date("prediction_as_of", self.prediction_as_of)
        _required_date("entry_date", self.entry_date)
        _required_date("exit_date", self.exit_date)
        if self.entry_date <= self.prediction_as_of or self.exit_date <= self.entry_date:
            raise ValueError("evaluation dates must be strictly increasing")
        _positive_int("forecast_horizon_days", self.forecast_horizon_days)
        if not isinstance(self.variant, EvaluationVariant):
            raise ValueError("variant must be an EvaluationVariant")
        if self.benchmark_mode not in {"sector", "sp500"}:
            raise ValueError("benchmark_mode must be sector or sp500")
        _required_string("benchmark_symbol", self.benchmark_symbol)
        if not isinstance(self.used_spy_fallback, bool):
            raise ValueError("used_spy_fallback must be a bool")
        _finite("predicted_score", self.predicted_score)
        if not 0 <= self.predicted_score <= 1:
            raise ValueError("predicted_score must be between 0 and 1")
        _finite("subject_return", self.subject_return)
        _finite("benchmark_return", self.benchmark_return)
        _finite("excess_return", self.excess_return)


@dataclass(frozen=True, slots=True)
class EvaluationExclusion:
    """A prediction that could not receive a complete market outcome."""

    company: str
    prediction_as_of: date
    forecast_horizon_days: int
    reason: str

    def __post_init__(self) -> None:
        _required_string("company", self.company)
        _required_date("prediction_as_of", self.prediction_as_of)
        _positive_int("forecast_horizon_days", self.forecast_horizon_days)
        _required_string("reason", self.reason)


@dataclass(frozen=True, slots=True)
class EvaluationMetric:
    """Aggregate metric for one variant, benchmark mode, and return horizon."""

    variant: EvaluationVariant
    benchmark_mode: str
    forecast_horizon_days: int
    observation_count: int
    directional_sample_size: int
    directional_hit_rate: float | None
    spearman_correlation: float | None

    def __post_init__(self) -> None:
        if not isinstance(self.variant, EvaluationVariant):
            raise ValueError("variant must be an EvaluationVariant")
        if self.benchmark_mode not in {"sector", "sp500"}:
            raise ValueError("benchmark_mode must be sector or sp500")
        _positive_int("forecast_horizon_days", self.forecast_horizon_days)
        _non_negative_int("observation_count", self.observation_count)
        _non_negative_int("directional_sample_size", self.directional_sample_size)
        if self.directional_sample_size > self.observation_count:
            raise ValueError("directional_sample_size cannot exceed observation_count")
        _optional_unit_interval("directional_hit_rate", self.directional_hit_rate)
        _optional_correlation("spearman_correlation", self.spearman_correlation)


@dataclass(frozen=True, slots=True)
class EvaluationReport:
    """Append-only evaluation output and all data needed to audit its metrics."""

    report_id: str
    created_at: datetime
    corpus_manifest_version: str
    market_snapshot_version: str
    observations: tuple[EvaluationObservation, ...]
    exclusions: tuple[EvaluationExclusion, ...]
    metrics: tuple[EvaluationMetric, ...]

    def __post_init__(self) -> None:
        _required_string("report_id", self.report_id)
        if not isinstance(self.created_at, datetime):
            raise ValueError("created_at must be a datetime")
        _required_string("corpus_manifest_version", self.corpus_manifest_version)
        _required_string("market_snapshot_version", self.market_snapshot_version)
        if not isinstance(self.observations, tuple) or any(
            not isinstance(item, EvaluationObservation) for item in self.observations
        ):
            raise ValueError("observations must contain EvaluationObservation values")
        if not isinstance(self.exclusions, tuple) or any(
            not isinstance(item, EvaluationExclusion) for item in self.exclusions
        ):
            raise ValueError("exclusions must contain EvaluationExclusion values")
        if not isinstance(self.metrics, tuple) or any(not isinstance(item, EvaluationMetric) for item in self.metrics):
            raise ValueError("metrics must contain EvaluationMetric values")


def _required_string(name: str, value: object) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} is required")


def _required_date(name: str, value: object) -> None:
    if not isinstance(value, date):
        raise ValueError(f"{name} must be a date")


def _positive_int(name: str, value: object) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ValueError(f"{name} must be a positive integer")


def _non_negative_int(name: str, value: object) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")


def _finite(name: str, value: object) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value):
        raise ValueError(f"{name} must be finite")


def _optional_unit_interval(name: str, value: float | None) -> None:
    if value is not None:
        _finite(name, value)
        if not 0 <= value <= 1:
            raise ValueError(f"{name} must be between 0 and 1")


def _optional_correlation(name: str, value: float | None) -> None:
    if value is not None:
        _finite(name, value)
        if not -1 <= value <= 1:
            raise ValueError(f"{name} must be between -1 and 1")
