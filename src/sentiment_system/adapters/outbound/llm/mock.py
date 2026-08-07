"""Deterministic mock LLM adapter for unit and offline tests."""

import hashlib
import json
from collections.abc import Mapping

from sentiment_system.application.ports.llm import ChunkScoringResult, TokenUsage
from sentiment_system.domain.documents import DocumentChunk
from sentiment_system.domain.sentiment import SentimentScore


class DeterministicLLMScorer:
    """Produce stable investor-independent scores without network calls."""

    def __init__(self, overrides: Mapping[str, ChunkScoringResult] | None = None) -> None:
        self._overrides = dict(overrides or {})

    def score_chunk(self, chunk: DocumentChunk, *, context: str = "") -> ChunkScoringResult:
        """Return a stable result; context is intentionally not part of the score."""
        del context
        override = self._overrides.get(chunk.chunk_id)
        if override is not None:
            return override

        digest = hashlib.sha256(chunk.content.encode("utf-8")).digest()
        score = digest[0] / 255
        confidence = 0.5 + digest[1] / 510
        importance = digest[2] / 255
        parsed_output = {
            "score": score,
            "confidence": confidence,
            "importance_score": importance,
        }
        return ChunkScoringResult(
            sentiment=SentimentScore(score=score, confidence=confidence),
            importance_score=importance,
            raw_response=json.dumps(parsed_output, sort_keys=True),
            parsed_output=parsed_output,
            token_usage=TokenUsage(prompt_tokens=len(chunk.content.split()), completion_tokens=3),
        )
