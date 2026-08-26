"""Tests for investor-independent chunk scoring."""

from datetime import datetime, timezone

from sentiment_system.adapters.outbound.llm.mock import DeterministicLLMScorer
from sentiment_system.adapters.outbound.persistence.in_memory import (
    InMemoryChunkScoreRepository,
    InMemoryExperimentRunRepository,
    InMemoryProvenanceRepository,
)
from sentiment_system.application.use_cases.score_chunks import ScoreChunks
from sentiment_system.domain.documents import DocumentChunk


def _chunk(chunk_id: str = "chunk-1") -> DocumentChunk:
    return DocumentChunk(chunk_id=chunk_id, document_id="document-1", ordinal=0, content="Quarterly results.")


def test_score_chunks_persists_normalized_scores_and_provenance() -> None:
    scores = InMemoryChunkScoreRepository()
    provenance = InMemoryProvenanceRepository()
    runs = InMemoryExperimentRunRepository()

    result = ScoreChunks(
        DeterministicLLMScorer(),
        scores,
        provenance,
        runs,
        now=lambda: datetime(2026, 8, 26, tzinfo=timezone.utc),
    ).execute((_chunk(),), run_id="run-1", prompt="Score sentiment and importance.")

    assert result == 1
    stored = scores.list_for_chunk("chunk-1")[0]
    assert 0 <= stored.sentiment.score <= 1
    assert 0 <= stored.sentiment.confidence <= 1
    assert 0 <= stored.importance_score <= 1
    assert stored.excluded is False
    assert stored.token_usage["prompt_tokens"] > 0
    assert stored.token_usage["truncated"] is False
    assert provenance.get("run-1") is not None
    assert provenance.get("run-1").model_provider == "deterministic"
    assert runs.get("run-1").status == "completed"


def test_score_chunks_soft_excludes_after_three_consecutive_low_scores() -> None:
    chunk = _chunk()
    low = DeterministicLLMScorer(
        {chunk.chunk_id: _result(importance=0.01)},
    )
    scores = InMemoryChunkScoreRepository()
    provenance = InMemoryProvenanceRepository()
    runs = InMemoryExperimentRunRepository()
    scorer = ScoreChunks(low, scores, provenance, runs)

    for run_id in ("run-1", "run-2", "run-3"):
        scorer.execute((chunk,), run_id=run_id, prompt="Score.")

    assert scores.list_for_chunk(chunk.chunk_id)[-1].excluded is True


def _result(*, importance: float):
    from sentiment_system.application.ports.llm import ChunkScoringResult
    from sentiment_system.domain.sentiment import SentimentScore

    return ChunkScoringResult(
        sentiment=SentimentScore(score=0.7, confidence=0.8),
        importance_score=importance,
        raw_response='{"importance_score": 0.01}',
        parsed_output={"score": 0.7, "confidence": 0.8, "importance_score": importance},
    )
