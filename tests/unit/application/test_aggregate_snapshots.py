"""Tests for deterministic document and company sentiment aggregation."""

from datetime import date
from math import exp, log

from sentiment_system.adapters.outbound.persistence.in_memory import (
    InMemoryChunkRepository,
    InMemoryChunkScoreRepository,
    InMemoryDocumentRepository,
    InMemorySnapshotRepository,
)
from sentiment_system.application.use_cases.aggregate_snapshots import AggregateSnapshots
from sentiment_system.domain.documents import DocumentChunk, SourceDocument
from sentiment_system.domain.scoring import ChunkScoreRecord
from sentiment_system.domain.sentiment import SentimentScore


def test_aggregate_snapshots_uses_importance_confidence_and_recency_weights() -> None:
    first = _document("document-1", date(2025, 1, 1))
    second = _document("document-2", date(2025, 1, 31))
    chunks = (_chunk("chunk-1", first), _chunk("chunk-2", second))
    scores = (
        _score("chunk-1", 0.2, importance=0.5, confidence=0.8),
        _score("chunk-2", 0.8, importance=1.0, confidence=0.6),
    )
    snapshots = InMemorySnapshotRepository()

    count = AggregateSnapshots(
        InMemoryDocumentRepository((first, second)),
        InMemoryChunkRepository(chunks),
        InMemoryChunkScoreRepository(scores),
        snapshots,
    ).execute(company="AAPL", as_of=date(2025, 2, 1), run_id="run-1")

    assert count == 3
    snapshot = snapshots.list_for_company("AAPL")[1]
    first_weight = 0.5 * 0.8 * exp(-log(2) * 31 / 90)
    second_weight = 1.0 * 0.6 * exp(-log(2) * 1 / 90)
    expected = (0.2 * first_weight + 0.8 * second_weight) / (first_weight + second_weight)
    assert snapshot.sentiment.score == expected
    assert [item.chunk_id for item in snapshot.evidence] == ["chunk-1", "chunk-2"]
    assert snapshot.rule_version == "aggregation-personalization-v1"


def test_aggregate_snapshots_excludes_future_and_soft_excluded_chunks() -> None:
    current = _document("document-1", date(2025, 2, 1))
    future = _document("document-2", date(2025, 2, 2))
    chunks = (_chunk("chunk-1", current), _chunk("chunk-2", future))
    scores = (
        _score("chunk-1", 0.9, importance=0.9, confidence=0.9),
        _score("chunk-2", 0.1, importance=0.9, confidence=0.9, excluded=True),
    )
    snapshots = InMemorySnapshotRepository()

    AggregateSnapshots(
        InMemoryDocumentRepository((current, future)),
        InMemoryChunkRepository(chunks),
        InMemoryChunkScoreRepository(scores),
        snapshots,
    ).execute(company="AAPL", as_of=date(2025, 2, 1), run_id="run-1")

    assert all(snapshot.sentiment.score == 0.9 for snapshot in snapshots.list_for_company("AAPL"))
    assert all(len(snapshot.evidence) == 1 for snapshot in snapshots.list_for_company("AAPL"))


def _document(document_id: str, published_at: date) -> SourceDocument:
    return SourceDocument(
        document_id=document_id,
        source_id=document_id,
        company="AAPL",
        source="fixture",
        published_at=published_at,
        document_type="company_communication",
        raw_content="Raw content.",
        cleaned_content="Cleaned content.",
    )


def _chunk(chunk_id: str, document: SourceDocument) -> DocumentChunk:
    return DocumentChunk(chunk_id=chunk_id, document_id=document.document_id, ordinal=0, content="Content.")


def _score(
    chunk_id: str,
    score: float,
    *,
    importance: float,
    confidence: float,
    excluded: bool = False,
) -> ChunkScoreRecord:
    return ChunkScoreRecord(
        chunk_id=chunk_id,
        run_id="run-1",
        sentiment=SentimentScore(score=score, confidence=confidence),
        importance_score=importance,
        excluded=excluded,
        prompt="Score.",
        raw_response="{}",
        parsed_output={"score": score},
        token_usage={},
    )
