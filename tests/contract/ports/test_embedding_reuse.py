"""Both vector adapters inspect durable point identity and reuse compatible embeddings."""

from dataclasses import replace
from datetime import date, datetime, timedelta, timezone

import pytest
from qdrant_client import QdrantClient

from sentiment_system.adapters.outbound.embeddings.mock import DeterministicEmbeddings
from sentiment_system.adapters.outbound.persistence.in_memory import (
    InMemoryChunkScoreRepository,
    InMemoryDocumentRepository,
    InMemoryExperimentRunRepository,
)
from sentiment_system.adapters.outbound.vector.in_memory import InMemoryVectorStore
from sentiment_system.adapters.outbound.vector.qdrant import QdrantVectorStore
from sentiment_system.application.ports.vector_store import EmbeddedChunk
from sentiment_system.application.use_cases.index_chunks import IndexChunks
from sentiment_system.domain.documents import DocumentChunk, SourceDocument
from sentiment_system.domain.predictions import ExperimentRun
from sentiment_system.domain.scoring import ChunkScoreRecord
from sentiment_system.domain.sentiment import SentimentScore


@pytest.fixture(params=("memory", "qdrant"))
def store(request):
    if request.param == "memory":
        yield InMemoryVectorStore()
    else:
        client = QdrantClient(location=":memory:")
        try:
            yield QdrantVectorStore(client=client)
        finally:
            client.close()


def test_point_lookup_reuse_legacy_upgrade_and_model_change(store, monkeypatch):
    source = SourceDocument("doc", "source", "META", "fixture", date(2025, 1, 1), "release", "Raw.", "Clean.")
    chunk = DocumentChunk("chunk", "doc", 0, "Clean.", "processing-v2")
    assert store.get_indexed(("chunk", "missing")) == {}
    embeddings = DeterministicEmbeddings(2)
    store.upsert((EmbeddedChunk(chunk, "META", source.published_at, embeddings.embed(chunk.content)),))
    legacy = store.get_indexed(("chunk", "missing"))
    assert set(legacy) == {"chunk"}
    assert legacy["chunk"].embedding_fingerprint is None
    assert legacy["chunk"].dimension == 2
    documents = InMemoryDocumentRepository((source,))
    index = IndexChunks(documents, embeddings, store, embedding_configuration={"backend": "mock", "model": "a"})
    assert index.execute_with_counts((chunk,)).embedded_chunk_count == 1
    fingerprint = store.get_indexed(("chunk",))["chunk"].embedding_fingerprint
    assert fingerprint == index.embedding_fingerprint
    assert (
        IndexChunks(documents, embeddings, store, embedding_configuration={"model": "a", "backend": "mock"})
        .execute_with_counts((chunk,))
        .reused_chunk_count
        == 1
    )
    other = IndexChunks(documents, embeddings, store, embedding_configuration={"backend": "mock", "model": "b"})
    assert other.execute_with_counts((chunk,)).embedded_chunk_count == 1
    assert other.execute_with_counts((replace(chunk, content="Changed."),)).embedded_chunk_count == 1
    monkeypatch.setattr(embeddings, "embed", lambda text: pytest.fail("reused points must not invoke embeddings"))
    assert other.execute_with_counts((replace(chunk, content="Changed."),)).reused_chunk_count == 1


def test_reuse_and_upgrade_follow_completed_exclusion_state_without_rescoring(store, monkeypatch):
    now = datetime.now(timezone.utc)
    source = SourceDocument("doc", "source", "META", "fixture", date(2025, 1, 1), "release", "Raw.", "Clean.")
    chunk = DocumentChunk("chunk", "doc", 0, "Clean.")
    runs = InMemoryExperimentRunRepository()
    scores = InMemoryChunkScoreRepository(runs=runs)
    embeddings = DeterministicEmbeddings(2)
    index = IndexChunks(
        InMemoryDocumentRepository((source,)),
        embeddings,
        store,
        scores=scores,
        runs=runs,
        embedding_configuration={"model": "a"},
    )
    for offset, (status, excluded) in enumerate((("completed", True), ("failed", False))):
        run_id = str(offset)
        timestamp = now + timedelta(seconds=offset)
        runs.save(ExperimentRun(run_id, "scoring", status, timestamp, timestamp))
        scores.save(
            ChunkScoreRecord(chunk.chunk_id, run_id, SentimentScore(0.5, 0.8), 0.01, excluded, "Score", "{}", {}, {})
        )
    index.execute((chunk,))
    assert store.get_indexed((chunk.chunk_id,))[chunk.chunk_id].excluded is True
    store.set_excluded({chunk.chunk_id: False})
    monkeypatch.setattr(embeddings, "embed", lambda text: pytest.fail("no embedding call expected"))
    assert index.execute_with_counts((chunk,)).reused_chunk_count == 1
    assert store.get_indexed((chunk.chunk_id,))[chunk.chunk_id].excluded is True
    recovered_at = now + timedelta(seconds=2)
    runs.save(ExperimentRun("recovered", "scoring", "completed", recovered_at, recovered_at))
    scores.save(
        ChunkScoreRecord(chunk.chunk_id, "recovered", SentimentScore(0.5, 0.8), 0.8, False, "Score", "{}", {}, {})
    )
    assert index.execute_with_counts((chunk,)).reused_chunk_count == 1
    assert store.get_indexed((chunk.chunk_id,))[chunk.chunk_id].excluded is False


def test_dimension_change_fails_without_recreating_the_collection(store):
    source = SourceDocument("doc", "source", "META", "fixture", date(2025, 1, 1), "release", "Raw.", "Clean.")
    documents = InMemoryDocumentRepository((source,))
    chunk = DocumentChunk("chunk", "doc", 0, "Clean.")
    IndexChunks(
        documents, DeterministicEmbeddings(2), store, embedding_configuration={"model": "two-dimensional"}
    ).execute((chunk,))
    before = store.get_indexed((chunk.chunk_id,))
    with pytest.raises(ValueError, match="dimension"):
        IndexChunks(
            documents, DeterministicEmbeddings(3), store, embedding_configuration={"model": "three-dimensional"}
        ).execute((chunk,))
    assert store.get_indexed((chunk.chunk_id,)) == before
