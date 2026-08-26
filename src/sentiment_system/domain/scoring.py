"""Auditable investor-independent chunk scoring records."""

from collections.abc import Mapping
from dataclasses import dataclass
from math import isfinite
from types import MappingProxyType

from sentiment_system.domain.sentiment import SentimentScore


@dataclass(frozen=True, slots=True)
class ChunkScoreRecord:
    """One immutable chunk score produced by a specific experiment run."""

    chunk_id: str
    run_id: str
    sentiment: SentimentScore
    importance_score: float
    excluded: bool
    prompt: str
    raw_response: str
    parsed_output: Mapping[str, object]
    token_usage: Mapping[str, object]

    def __post_init__(self) -> None:
        _require_non_empty_string("chunk_id", self.chunk_id)
        _require_non_empty_string("run_id", self.run_id)
        if not isinstance(self.sentiment, SentimentScore):
            raise ValueError("sentiment must be a SentimentScore")
        if (
            isinstance(self.importance_score, bool)
            or not isinstance(self.importance_score, (int, float))
            or not isfinite(self.importance_score)
            or not 0 <= self.importance_score <= 1
        ):
            raise ValueError("importance_score must be between 0 and 1")
        if not isinstance(self.excluded, bool):
            raise ValueError("excluded must be a boolean")
        _require_non_empty_string("prompt", self.prompt)
        _require_non_empty_string("raw_response", self.raw_response)
        object.__setattr__(self, "parsed_output", _freeze_mapping(self.parsed_output, "parsed_output"))
        object.__setattr__(self, "token_usage", _freeze_mapping(self.token_usage, "token_usage"))


def _freeze_mapping(value: Mapping[str, object], name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be a mapping")
    if any(not isinstance(key, str) for key in value):
        raise ValueError(f"{name} keys must be strings")
    return MappingProxyType(dict(value))


def _require_non_empty_string(name: str, value: object) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} is required")
