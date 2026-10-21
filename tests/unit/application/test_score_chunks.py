"""Tests for investor-independent chunk scoring."""

from datetime import datetime, timedelta, timezone

import pytest

from sentiment_system.adapters.outbound.llm.mock import DeterministicLLMScorer
from sentiment_system.adapters.outbound.persistence.in_memory import (
    InMemoryChunkScoreRepository,
    InMemoryExperimentRunRepository,
    InMemoryProvenanceRepository,
)
from sentiment_system.application.use_cases.score_chunks import ScoreChunks
from sentiment_system.domain.documents import DocumentChunk
from sentiment_system.domain.predictions import ExperimentRun


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


@pytest.mark.parametrize(
    ("importance", "excluded"),
    [((0.01, 0.01, 0.9, 0.01), False), ((0.9, 0.01, 0.01, 0.01), True), ((0.01, 0.01, 0.01, 0.05), False)],
)
def test_exclusion_follows_execution_order_and_can_recover(importance, excluded) -> None:
    scores = InMemoryChunkScoreRepository()
    runs = InMemoryExperimentRunRepository()
    provenance = InMemoryProvenanceRepository()
    for index, (run_id, value) in enumerate(zip(("run-x", "run-y", "run-a", "run-z"), importance)):
        ScoreChunks(
            DeterministicLLMScorer({"chunk-1": _result(importance=value)}),
            scores,
            provenance,
            runs,
            now=lambda index=index: datetime(2026, 8, 26, tzinfo=timezone.utc) + timedelta(hours=index),
        ).execute((_chunk(),), run_id=run_id, prompt="Score.")
    final = next(item for item in scores.list_for_chunk("chunk-1") if item.run_id == "run-z")
    assert final.excluded is excluded
    assert len(scores.list_for_chunk("chunk-1")) == 4


def test_scoring_stage_keeps_parent_batch_started_until_aggregation_finishes() -> None:
    runs = InMemoryExperimentRunRepository()
    parent = ExperimentRun(
        run_id="batch",
        run_type="batch",
        status="started",
        started_at=datetime(2026, 8, 26, tzinfo=timezone.utc),
        configuration={"as_of": "2025-02-01", "company": "AAPL"},
    )
    runs.save(parent)
    ScoreChunks(
        DeterministicLLMScorer(),
        InMemoryChunkScoreRepository(),
        InMemoryProvenanceRepository(),
        runs,
        now=lambda: parent.started_at + timedelta(minutes=1),
    ).execute((_chunk(),), run_id="batch", prompt="Score.")
    assert runs.get("batch") == parent


def test_failed_standalone_scoring_records_failed_run() -> None:
    class FailingScorer:
        def score_chunk(self, chunk, *, context=None):
            raise RuntimeError("provider unavailable")

    runs = InMemoryExperimentRunRepository()
    with pytest.raises(RuntimeError, match="provider unavailable"):
        ScoreChunks(
            FailingScorer(),
            InMemoryChunkScoreRepository(),
            InMemoryProvenanceRepository(),
            runs,
        ).execute((_chunk(),), run_id="failed-run", prompt="Score.")
    assert runs.get("failed-run").status == "failed"


@pytest.mark.parametrize(
    ("status", "run_type"), [("failed", "scoring"), ("started", "scoring"), ("completed", "evaluation")]
)
def test_ineligible_prior_run_does_not_count_toward_exclusion(status, run_type) -> None:
    from dataclasses import replace

    runs = InMemoryExperimentRunRepository()
    scores = InMemoryChunkScoreRepository(runs=runs)
    provenance = InMemoryProvenanceRepository()
    for hour, run_id in enumerate(("run-x", "run-y")):
        ScoreChunks(
            DeterministicLLMScorer({"chunk-1": _result(importance=0.01)}),
            scores,
            provenance,
            runs,
            now=lambda hour=hour: datetime(2026, 8, 26, hour, tzinfo=timezone.utc),
        ).execute((_chunk(),), run_id=run_id, prompt="Score.")
    runs.save(replace(runs.get("run-y"), status=status, run_type=run_type))
    ScoreChunks(
        DeterministicLLMScorer({"chunk-1": _result(importance=0.01)}),
        scores,
        provenance,
        runs,
        now=lambda: datetime(2026, 8, 26, 2, tzinfo=timezone.utc),
    ).execute((_chunk(),), run_id="run-a", prompt="Score.")
    assert scores.list_for_chunk("chunk-1")[-1].excluded is False


def _result(*, importance: float):
    from sentiment_system.application.ports.llm import ChunkScoringResult
    from sentiment_system.domain.sentiment import SentimentScore

    return ChunkScoringResult(
        sentiment=SentimentScore(score=0.7, confidence=0.8),
        importance_score=importance,
        raw_response='{"importance_score": 0.01}',
        parsed_output={"score": 0.7, "confidence": 0.8, "importance_score": importance},
    )
