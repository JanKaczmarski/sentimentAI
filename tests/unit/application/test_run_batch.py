"""Tests for the deterministic source-to-prediction batch orchestration."""

from dataclasses import replace
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
from sentiment_system.application.ports.vector_store import VectorQuery
from sentiment_system.application.use_cases.aggregate_snapshots import AggregateSnapshots
from sentiment_system.application.use_cases.index_chunks import IndexChunks
from sentiment_system.application.use_cases.ingest_documents import IngestDocuments
from sentiment_system.application.use_cases.run_batch import BatchExecutionError, RunBatch
from sentiment_system.application.use_cases.score_chunks import ScoreChunks
from sentiment_system.application.use_cases.synchronize_chunk_exclusions import SynchronizeChunkExclusions
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
            _document("document-same-day", date(2025, 1, 2)),
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
    assert runs.get(result.run_id).configuration["publication_rule"] == "published_at < as_of"
    assert provenance.get(result.run_id) is not None
    audit = provenance.get(result.run_id)
    assert audit.processing_config["publication_rule"] == "published_at < as_of"
    assert audit.processing_config["stages"]["aggregation"]["status"] == "completed"
    assert audit.processing_config["source_lineage"][0]["source_id"] == "document-1"
    assert audit.processing_config["source_lineage"][0]["chunk_ids"]
    assert len(snapshots.list_for_company("AAPL")) == 3


def test_run_batch_marks_the_run_failed_when_scoring_raises() -> None:
    runs = InMemoryExperimentRunRepository()
    provenance = InMemoryProvenanceRepository()
    batch = _batch(
        documents=(_document("document-1", date(2025, 1, 1)),),
        document_repository=InMemoryDocumentRepository(),
        chunk_repository=InMemoryChunkRepository(),
        score_repository=InMemoryChunkScoreRepository(),
        runs=runs,
        provenance=provenance,
        snapshots=InMemorySnapshotRepository(),
        scorer=RaisingScorer(),
    )

    with pytest.raises(BatchExecutionError) as error:
        batch.execute(as_of=date(2025, 1, 2))

    failed_run = runs.get(error.value.run_id)
    assert failed_run is not None
    assert failed_run.status == "failed"
    assert failed_run.completed_at is not None
    assert failed_run.configuration["failed_stage"] == "scoring"
    assert failed_run.configuration["stages"]["indexing"]["status"] == "completed"
    audit = provenance.get(error.value.run_id)
    assert audit is not None
    assert audit.processing_config["status"] == "failed"
    assert len(audit.processing_config["source_lineage"]) == 1


def test_failed_scoring_preserves_partial_outputs_and_previous_run_history() -> None:
    runs, provenance, scores, snapshots = (
        InMemoryExperimentRunRepository(),
        InMemoryProvenanceRepository(),
        InMemoryChunkScoreRepository(),
        InMemorySnapshotRepository(),
    )
    scorer = CountingScorer()
    batch = _batch(
        documents=(_document("one", date(2025, 1, 1)), _document("two", date(2025, 1, 1))),
        document_repository=InMemoryDocumentRepository(),
        chunk_repository=InMemoryChunkRepository(),
        score_repository=scores,
        runs=runs,
        provenance=provenance,
        snapshots=snapshots,
        scorer=scorer,
    )
    completed = batch.execute(as_of=date(2025, 1, 2))
    old_audit = provenance.get(completed.run_id)
    old_snapshots = snapshots.list_for_company("AAPL")
    original = scorer.score_chunk
    calls = 0

    def fail_second(chunk, *, context=""):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("provider failed with sensitive details that must not be stored")
        return original(chunk, context=context)

    scorer.score_chunk = fail_second
    with pytest.raises(BatchExecutionError) as error:
        batch.execute(as_of=date(2025, 1, 2))
    audit = provenance.get(error.value.run_id)
    assert audit is not None
    assert len(audit.parsed_output) == 1
    assert audit.raw_response
    assert audit.processing_config["scored_chunk_count"] == 1
    assert "sensitive details" not in str(audit)
    assert provenance.get(completed.run_id) == old_audit
    assert snapshots.list_for_company("AAPL") == old_snapshots


def test_partial_ingestion_failure_retains_completed_document_lineage():
    runs, provenance = InMemoryExperimentRunRepository(), InMemoryProvenanceRepository()
    batch = _batch(
        documents=(_document("one", date(2025, 1, 1)), replace(_document("two", date(2025, 1, 1)), raw_content="###")),
        document_repository=InMemoryDocumentRepository(),
        chunk_repository=InMemoryChunkRepository(),
        score_repository=InMemoryChunkScoreRepository(),
        runs=runs,
        provenance=provenance,
        snapshots=InMemorySnapshotRepository(),
        scorer=CountingScorer(),
    )
    with pytest.raises(BatchExecutionError) as error:
        batch.execute(as_of=date(2025, 1, 2))
    audit = provenance.get(error.value.run_id)
    assert audit.processing_config["failed_stage"] == "ingestion"
    assert audit.processing_config["document_count"] == 1
    assert audit.processing_config["source_lineage"][0]["source_id"] == "one"


@pytest.mark.parametrize("stage", ("ingestion", "indexing", "aggregation", "exclusion_sync"))
def test_batch_records_failure_at_each_stage(monkeypatch, stage) -> None:
    runs, provenance = InMemoryExperimentRunRepository(), InMemoryProvenanceRepository()
    batch = _batch(
        documents=(_document("one", date(2025, 1, 1)),),
        document_repository=InMemoryDocumentRepository(),
        chunk_repository=InMemoryChunkRepository(),
        score_repository=InMemoryChunkScoreRepository(),
        runs=runs,
        provenance=provenance,
        snapshots=InMemorySnapshotRepository(),
        scorer=CountingScorer(),
    )
    service = getattr(batch, f"_{stage}")

    def fail(*args, **kwargs):
        raise RuntimeError("private connection details")

    monkeypatch.setattr(service, "run" if stage == "ingestion" else "execute", fail)
    with pytest.raises(BatchExecutionError) as error:
        batch.execute(as_of=date(2025, 1, 2))
    run = runs.get(error.value.run_id)
    audit = provenance.get(error.value.run_id)
    assert run.status == "failed"
    assert run.configuration["failed_stage"] == stage
    assert audit.processing_config["stages"][stage]["status"] == "failed"
    assert "private connection details" not in str(audit)


def test_repeated_low_batches_exclude_recover_and_preserve_exclusion_during_failed_rescore(monkeypatch):
    runs, provenance, scores, snapshots = (
        InMemoryExperimentRunRepository(),
        InMemoryProvenanceRepository(),
        InMemoryChunkScoreRepository(),
        InMemorySnapshotRepository(),
    )
    scorer = CountingScorer()
    original = scorer.score_chunk
    importance = 0.01

    def score(chunk, *, context=""):
        result = original(chunk, context=context)
        return replace(result, importance_score=importance)

    monkeypatch.setattr(scorer, "score_chunk", score)
    batch = _batch(
        documents=(_document("one", date(2025, 1, 1)),),
        document_repository=InMemoryDocumentRepository(),
        chunk_repository=InMemoryChunkRepository(),
        score_repository=scores,
        runs=runs,
        provenance=provenance,
        snapshots=snapshots,
        scorer=scorer,
    )
    vectors = batch._indexing._vector_store
    embedding = DeterministicEmbeddings().embed("Revenue increased.")
    query = VectorQuery(embedding=embedding)
    for expected_matches in (1, 1, 0):
        batch.execute(as_of=date(2025, 1, 2))
        assert len(vectors.search(query)) == expected_matches
    monkeypatch.setattr(scorer, "score_chunk", RaisingScorer().score_chunk)
    with pytest.raises(BatchExecutionError):
        batch.execute(as_of=date(2025, 1, 2))
    assert vectors.search(query) == ()
    monkeypatch.setattr(scorer, "score_chunk", score)
    importance = 0.8
    batch.execute(as_of=date(2025, 1, 2))
    assert len(vectors.search(query)) == 1


def _batch(*, documents, document_repository, chunk_repository, score_repository, runs, provenance, snapshots, scorer):
    source = FixtureDocumentSource(documents)
    ingestion = IngestDocuments(
        source,
        document_repository,
        chunk_repository,
        processing_config_version="processing-v1",
        token_counter=lambda value: len(value.split()),
    )
    vectors = InMemoryVectorStore()
    return RunBatch(
        ingestion,
        IndexChunks(document_repository, DeterministicEmbeddings(), vectors, scores=score_repository, runs=runs),
        ScoreChunks(scorer, score_repository, provenance, runs),
        AggregateSnapshots(document_repository, chunk_repository, score_repository, snapshots),
        runs,
        provenance=provenance,
        exclusion_sync=SynchronizeChunkExclusions(score_repository, vectors),
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
