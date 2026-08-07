"""Auditable sentiment snapshots, predictions, and experiment provenance."""

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from enum import IntEnum
from math import isfinite
from types import MappingProxyType

from sentiment_system.domain.sentiment import SentimentScore


class SnapshotWindow(IntEnum):
    """Supported company-sentiment lookback windows."""

    THIRTY_DAYS = 30
    NINETY_DAYS = 90
    YEAR = 365


@dataclass(frozen=True, slots=True)
class PredictionEvidence:
    """A source excerpt retained as evidence for a prediction."""

    chunk_id: str
    published_at: date
    importance_score: float
    excerpt: str

    def __post_init__(self) -> None:
        _require_non_empty_string("chunk_id", self.chunk_id)
        if not isinstance(self.published_at, date):
            raise ValueError("published_at must be a date")
        _require_unit_interval("importance_score", self.importance_score)
        _require_non_empty_string("excerpt", self.excerpt)


@dataclass(frozen=True, slots=True)
class CompanySentimentSnapshot:
    """Investor-independent sentiment for a company and supported time window."""

    company: str
    as_of: date
    window_days: SnapshotWindow
    sentiment: SentimentScore
    evidence: tuple[PredictionEvidence, ...]
    run_id: str

    def __post_init__(self) -> None:
        _require_non_empty_string("company", self.company)
        if not isinstance(self.as_of, date):
            raise ValueError("as_of must be a date")
        object.__setattr__(self, "window_days", _coerce_snapshot_window(self.window_days))
        if not isinstance(self.sentiment, SentimentScore):
            raise ValueError("sentiment must be a SentimentScore")
        _validate_evidence(self.evidence)
        _require_non_empty_string("run_id", self.run_id)


@dataclass(frozen=True, slots=True)
class Prediction:
    """A base and personalized prediction with reproducible source evidence."""

    company: str
    as_of: date
    lookback_days: SnapshotWindow
    forecast_horizon_days: int
    base_sentiment: SentimentScore
    personalized_sentiment: SentimentScore
    confidence: float
    evidence: tuple[PredictionEvidence, ...]
    run_id: str
    reasoning: str | None = None

    def __post_init__(self) -> None:
        _require_non_empty_string("company", self.company)
        if not isinstance(self.as_of, date):
            raise ValueError("as_of must be a date")
        object.__setattr__(self, "lookback_days", _coerce_snapshot_window(self.lookback_days))
        if (
            isinstance(self.forecast_horizon_days, bool)
            or not isinstance(self.forecast_horizon_days, int)
            or self.forecast_horizon_days <= 0
        ):
            raise ValueError("forecast_horizon_days must be a positive integer")
        if not isinstance(self.base_sentiment, SentimentScore):
            raise ValueError("base_sentiment must be a SentimentScore")
        if not isinstance(self.personalized_sentiment, SentimentScore):
            raise ValueError("personalized_sentiment must be a SentimentScore")
        _require_unit_interval("confidence", self.confidence)
        _validate_evidence(self.evidence)
        _require_non_empty_string("run_id", self.run_id)
        if self.reasoning is not None and not isinstance(self.reasoning, str):
            raise ValueError("reasoning must be a string")

    @property
    def sources(self) -> tuple[PredictionEvidence, ...]:
        """Return evidence under the API contract's source vocabulary."""
        return self.evidence


@dataclass(frozen=True, slots=True)
class ExperimentProvenance:
    """Secret-free inputs and outputs needed to reproduce one experiment run."""

    run_id: str
    input_source: str
    input_version: str
    processing_config: Mapping[str, object]
    model_provider: str
    model_name: str
    prompt: str
    raw_response: str
    parsed_output: Mapping[str, object]
    thesis_parameters: Mapping[str, object]
    created_at: datetime

    def __post_init__(self) -> None:
        _require_non_empty_string("run_id", self.run_id)
        _require_non_empty_string("input_source", self.input_source)
        _require_non_empty_string("input_version", self.input_version)
        _require_non_empty_string("model_provider", self.model_provider)
        _require_non_empty_string("model_name", self.model_name)
        _require_non_empty_string("prompt", self.prompt)
        _require_string("raw_response", self.raw_response)
        if not isinstance(self.created_at, datetime):
            raise ValueError("created_at must be a datetime")

        object.__setattr__(self, "processing_config", _freeze_secret_free_mapping(self.processing_config))
        object.__setattr__(self, "parsed_output", _freeze_secret_free_mapping(self.parsed_output))
        object.__setattr__(self, "thesis_parameters", _freeze_secret_free_mapping(self.thesis_parameters))
        _reject_secret_like_value(self.prompt)
        _reject_secret_like_value(self.raw_response)
        _reject_secret_like_value(self.input_source)
        _reject_secret_like_value(self.input_version)
        _reject_secret_like_value(self.model_provider)
        _reject_secret_like_value(self.model_name)


_SECRET_KEY_PATTERN = re.compile(
    r"(?:api[_-]?key|access[_-]?key|auth(?:orization)?|bearer|client[_-]?secret|"
    r"credential|password|passwd|private[_-]?key|refresh[_-]?token|secret|"
    r"(?:api|access|auth|bearer|refresh|id)[_-]?token)",
    re.IGNORECASE,
)
_SECRET_VALUE_PATTERNS = (
    re.compile(r"\bBearer\s+\S+", re.IGNORECASE),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"\b(?:sk|ghp|github_pat|xox[abprs])-[A-Za-z0-9_-]{8,}\b"),
    re.compile(r"\b(?:api[_-]?key|authorization|password|secret)\s*[:=]", re.IGNORECASE),
)


def _coerce_snapshot_window(value: SnapshotWindow | int) -> SnapshotWindow:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("window_days must be one of 30, 90, or 365")
    try:
        return SnapshotWindow(value)
    except ValueError as error:
        raise ValueError("window_days must be one of 30, 90, or 365") from error


def _validate_evidence(evidence: tuple[PredictionEvidence, ...]) -> None:
    if not isinstance(evidence, tuple) or any(not isinstance(item, PredictionEvidence) for item in evidence):
        raise ValueError("evidence must contain PredictionEvidence values")


def _require_non_empty_string(name: str, value: object) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} is required")


def _require_string(name: str, value: object) -> None:
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a string")


def _require_unit_interval(name: str, value: object) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value) or not 0 <= value <= 1:
        raise ValueError(f"{name} must be between 0 and 1")


def _freeze_secret_free_mapping(value: Mapping[str, object]) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError("provenance values must be mappings")
    frozen: dict[str, object] = {}
    for key, item in value.items():
        if not isinstance(key, str):
            raise ValueError("provenance mapping keys must be strings")
        if _SECRET_KEY_PATTERN.search(key):
            raise ValueError("secret-like provenance value is not allowed")
        _reject_secret_like_value(item)
        frozen[key] = _freeze_value(item)
    return MappingProxyType(frozen)


def _freeze_value(value: object) -> object:
    if isinstance(value, Mapping):
        return _freeze_secret_free_mapping(value)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return tuple(_freeze_value(item) for item in value)
    return value


def _reject_secret_like_value(value: object) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if isinstance(key, str) and _SECRET_KEY_PATTERN.search(key):
                raise ValueError("secret-like provenance value is not allowed")
            _reject_secret_like_value(item)
        return
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for item in value:
            _reject_secret_like_value(item)
        return
    if isinstance(value, str) and any(pattern.search(value) for pattern in _SECRET_VALUE_PATTERNS):
        raise ValueError("secret-like provenance value is not allowed")
