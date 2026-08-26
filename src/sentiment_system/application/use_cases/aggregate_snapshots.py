"""Use case for deterministic document and company sentiment aggregation."""

from collections.abc import Sequence
from datetime import date
from math import exp, log

from sentiment_system.application.ports.repositories import (
    ChunkRepository,
    ChunkScoreRepository,
    DocumentRepository,
    SnapshotRepository,
)
from sentiment_system.domain.documents import DocumentChunk
from sentiment_system.domain.predictions import (
    CompanySentimentSnapshot,
    PredictionEvidence,
    SnapshotWindow,
)
from sentiment_system.domain.scoring import ChunkScoreRecord
from sentiment_system.domain.sentiment import SentimentScore

RULE_VERSION = "aggregation-personalization-v1"
_RECENCY_HALF_LIFE_DAYS = 90
_IMPORTANCE_THRESHOLD = 0.05


class AggregateSnapshots:
    """Aggregate one scoring run into auditable company snapshots."""

    def __init__(
        self,
        documents: DocumentRepository,
        chunks: ChunkRepository,
        scores: ChunkScoreRepository,
        snapshots: SnapshotRepository,
    ) -> None:
        self._documents = documents
        self._chunks = chunks
        self._scores = scores
        self._snapshots = snapshots

    def execute(self, *, company: str, as_of: date, run_id: str) -> int:
        """Create 30-, 90-, and 365-day snapshots for one company and run."""
        inputs = self._scored_chunks(company=company, run_id=run_id)
        for window in SnapshotWindow:
            sentiment, evidence = _aggregate(inputs, as_of=as_of, window=window)
            self._snapshots.save(
                CompanySentimentSnapshot(
                    company=company,
                    as_of=as_of,
                    window_days=window,
                    sentiment=sentiment,
                    evidence=evidence,
                    run_id=run_id,
                    rule_version=RULE_VERSION,
                )
            )
        return len(tuple(SnapshotWindow))

    def _scored_chunks(self, *, company: str, run_id: str) -> tuple[tuple[DocumentChunk, date, ChunkScoreRecord], ...]:
        result: list[tuple[DocumentChunk, date, ChunkScoreRecord]] = []
        for document in self._documents.list_documents(company=company):
            for chunk in self._chunks.list_for_document(document.document_id):
                score = next(
                    (item for item in reversed(self._scores.list_for_chunk(chunk.chunk_id)) if item.run_id == run_id),
                    None,
                )
                if score is not None:
                    result.append((chunk, document.published_at, score))
        return tuple(result)


def _aggregate(
    inputs: Sequence[tuple[DocumentChunk, date, ChunkScoreRecord]],
    *,
    as_of: date,
    window: SnapshotWindow,
) -> tuple[SentimentScore, tuple[PredictionEvidence, ...]]:
    weighted: list[tuple[float, float, float]] = []
    evidence: list[PredictionEvidence] = []
    for chunk, published_at, score_record in inputs:
        age_days = (as_of - published_at).days
        if age_days < 0 or age_days > int(window) or score_record.excluded:
            continue
        recency = exp(-log(2) * age_days / _RECENCY_HALF_LIFE_DAYS)
        base_weight = score_record.importance_score * recency
        weight = base_weight * score_record.sentiment.confidence
        if weight <= 0 or score_record.importance_score < _IMPORTANCE_THRESHOLD:
            continue
        weighted.append((score_record.sentiment.score, weight, base_weight))
        evidence.append(
            PredictionEvidence(
                chunk_id=chunk.chunk_id,
                published_at=published_at,
                importance_score=score_record.importance_score,
                excerpt=chunk.content,
            )
        )

    denominator = sum(item[1] for item in weighted)
    if denominator == 0:
        return SentimentScore(score=0.5, confidence=0.0), ()
    score = sum(item[0] * item[1] for item in weighted) / denominator
    confidence = sum(item[1] for item in weighted) / sum(item[2] for item in weighted)
    return SentimentScore(score=score, confidence=confidence), tuple(evidence)
