"""Tests for the deterministic source-to-prediction batch orchestration."""

from datetime import date

import pytest

from sentiment_system.adapters.outbound.embeddings.mock import DeterministicEmbeddings
from sentiment_system.adapters.outbound.llm.mock import DeterministicLLMScorer
from sentiment_system.adapters.outbound.persistence.in_memory import (
    InMemoryChunkRepository,
    InMemoryChunkScoreRepository,
    InMemoryDocumentRepository,
    InMemoryExperimentRunRepository,
    InMemoryProvenanceRepository,
    InMemorySnapshotRepository,
)
from sentiment_system.adapters.outbound.sources.fixtures import FixtureDocumentSource
from sentiment_system.adapters.outbound.vector.in_memory import InMemoryVectorStore
from sentiment_system.application.ports.llm import ChunkScoringResult
from sentiment_system.application.use_cases.aggregate_snapshots import AggregateSnapshots
from sentiment_system.application.use_cases.index_chunks import IndexChunks
from sentiment_system.application.use_cases.ingest_documents import IngestDocuments
from sentiment_system.application.use_cases.run_batch import BatchExecutionError, RunBatch
from sentiment_system.application.use_cases.score_chunks import ScoreChunks
from sentiment_system.domain.documents import SourceDocument


def test_run_batch_ingests_indexes_scores_and_aggregates_only_available_documents() -> None:
    document_repository = InMemoryDocumentRepository()
    chunk_repository = InMemoryChunkRepository()
    score_repository = InMemoryChunkScoreRepository()
    runs = InMemoryExperimentRunRepository()
    provenance = InMemoryProvenanceRepository()
    snapshots = InMemorySnapshotRepository()
    scorer = CountingScorer()
    batch = _batch(
        documents=(
            _document("document-1", date(2025, 1, 1)),
            _document("document-future", date(2025, 1, 3)),
        ),
        document_repository=document_repository,
        chunk_repository=chunk_repository,
        score_repository=score_repository,
        runs=runs,
        provenance=provenance,
        snapshots=snapshots,
        scorer=scorer,
    )

    result = batch.execute(as_of=date(2025, 1, 2))

    assert result.status == "completed"
    assert result.document_count == 1
    assert result.chunk_count == result.indexed_chunk_count == result.scored_chunk_count == 1
    assert result.snapshot_count == 3
    assert result.companies == ("AAPL",)
    assert scorer.calls == 1
    assert runs.get(result.run_id) is not None
    assert runs.get(result.run_id).status == "completed"
    assert runs.get(result.run_id).configuration["provider"] == "deterministic"
    assert runs.get(result.run_id).configuration["model"] == "deterministic-sha256-v1"
    assert provenance.get(result.run_id) is not None
    assert len(snapshots.list_for_company("AAPL")) == 3


def test_run_batch_marks_the_run_failed_when_scoring_raises() -> None:
    runs = InMemoryExperimentRunRepository()
    batch = _batch(
        documents=(_document("document-1", date(2025, 1, 1)),),
        document_repository=InMemoryDocumentRepository(),
        chunk_repository=InMemoryChunkRepository(),
        score_repository=InMemoryChunkScoreRepository(),
        runs=runs,
        provenance=InMemoryProvenanceRepository(),
        snapshots=InMemorySnapshotRepository(),
        scorer=RaisingScorer(),
    )

    with pytest.raises(BatchExecutionError) as error:
        batch.execute(as_of=date(2025, 1, 2))

    failed_run = runs.get(error.value.run_id)
    assert failed_run is not None
    assert failed_run.status == "failed"
    assert failed_run.completed_at is not None


def _batch(*, documents, document_repository, chunk_repository, score_repository, runs, provenance, snapshots, scorer):
    source = FixtureDocumentSource(documents)
    ingestion = IngestDocuments(
        source,
        document_repository,
        chunk_repository,
        processing_config_version="processing-v1",
        token_counter=lambda value: len(value.split()),
    )
    return RunBatch(
        ingestion,
        IndexChunks(document_repository, DeterministicEmbeddings(), InMemoryVectorStore()),
        ScoreChunks(scorer, score_repository, provenance, runs),
        AggregateSnapshots(document_repository, chunk_repository, score_repository, snapshots),
        runs,
    )


def _document(document_id: str, published_at: date) -> SourceDocument:
    return SourceDocument(
        document_id=document_id,
        source_id=document_id,
        company="AAPL",
        source="fixture",
        published_at=published_at,
        document_type="company_communication",
        raw_content="Revenue increased.",
        cleaned_content="Revenue increased.",
    )


class CountingScorer(DeterministicLLMScorer):
    """Count scoring calls while retaining deterministic result behavior."""

    def __init__(self) -> None:
        super().__init__()
        self.calls = 0

    def score_chunk(self, chunk, *, context: str = "") -> ChunkScoringResult:
        self.calls += 1
        return super().score_chunk(chunk, context=context)


class RaisingScorer:
    """Fail deterministically to exercise batch failure persistence."""

    def score_chunk(self, chunk, *, context: str = "") -> ChunkScoringResult:
        del chunk, context
        raise RuntimeError("scorer unavailable")
