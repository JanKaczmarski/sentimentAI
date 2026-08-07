"""Port for scoring chunks and generating structured LLM responses."""

from collections.abc import Mapping
from dataclasses import dataclass
from math import isfinite
from typing import Protocol, runtime_checkable

from sentiment_system.domain.documents import DocumentChunk
from sentiment_system.domain.sentiment import SentimentScore


@dataclass(frozen=True, slots=True)
class TokenUsage:
    """Provider-neutral token counts retained for experiment provenance."""

    prompt_tokens: int
    completion_tokens: int

    def __post_init__(self) -> None:
        if isinstance(self.prompt_tokens, bool) or not isinstance(self.prompt_tokens, int) or self.prompt_tokens < 0:
            raise ValueError("prompt_tokens must be a non-negative integer")
        if (
            isinstance(self.completion_tokens, bool)
            or not isinstance(self.completion_tokens, int)
            or self.completion_tokens < 0
        ):
            raise ValueError("completion_tokens must be a non-negative integer")

    @property
    def total_tokens(self) -> int:
        """Return the total number of reported tokens."""
        return self.prompt_tokens + self.completion_tokens


@dataclass(frozen=True, slots=True)
class ChunkScoringResult:
    """Provider-neutral parsed and raw output for one chunk score."""

    sentiment: SentimentScore
    importance_score: float
    raw_response: str
    parsed_output: Mapping[str, object]
    token_usage: TokenUsage | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.sentiment, SentimentScore):
            raise ValueError("sentiment must be a SentimentScore")
        if (
            isinstance(self.importance_score, bool)
            or not isinstance(self.importance_score, (int, float))
            or not isfinite(self.importance_score)
            or not 0 <= self.importance_score <= 1
        ):
            raise ValueError("importance_score must be between 0 and 1")
        if not isinstance(self.raw_response, str) or not self.raw_response.strip():
            raise ValueError("raw_response is required")
        if not isinstance(self.parsed_output, Mapping):
            raise ValueError("parsed_output must be a mapping")
        if self.token_usage is not None and not isinstance(self.token_usage, TokenUsage):
            raise ValueError("token_usage must be a TokenUsage")


@runtime_checkable
class LLMScorer(Protocol):
    """Score a chunk independently of any investor thesis."""

    def score_chunk(self, chunk: DocumentChunk, *, context: str = "") -> ChunkScoringResult:
        """Return deterministic, provider-neutral chunk scoring output."""
