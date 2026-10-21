"""Payload-only exclusion updates must preserve vectors and source evidence."""

from datetime import date

import pytest
from qdrant_client import QdrantClient

from sentiment_system.adapters.outbound.persistence.in_memory import InMemoryChunkScoreRepository
from sentiment_system.adapters.outbound.vector.in_memory import InMemoryVectorStore
from sentiment_system.adapters.outbound.vector.qdrant import QdrantVectorStore
from sentiment_system.application.ports.vector_store import EmbeddedChunk, VectorQuery
from sentiment_system.application.use_cases.synchronize_chunk_exclusions import SynchronizeChunkExclusions
from sentiment_system.domain.documents import DocumentChunk
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


def test_exclusion_and_recovery_only_update_payload_and_keep_auditable_matches(store):
    chunk = DocumentChunk(chunk_id="chunk", document_id="document", ordinal=0, content="Evidence.")
    store.upsert((EmbeddedChunk(chunk=chunk, company="META", published_at=date(2025, 1, 1), embedding=(1.0, 0.0)),))
    query = VectorQuery(embedding=(1.0, 0.0), company="META", as_of=date(2025, 1, 2))
    original = store.search(query)[0]
    scores = InMemoryChunkScoreRepository()
    sync = SynchronizeChunkExclusions(scores, store)
    for run_id, excluded in (("low-third", True), ("recovered", False)):
        scores.save(
            ChunkScoreRecord(
                chunk_id=chunk.chunk_id,
                run_id=run_id,
                sentiment=SentimentScore(score=0.5, confidence=0.8),
                importance_score=0.01 if excluded else 0.8,
                excluded=excluded,
                prompt="Score",
                raw_response="{}",
                parsed_output={},
                token_usage={},
            )
        )
        assert sync.execute((chunk,), run_id=run_id) == 1
        assert len(store.search(query)) == (0 if excluded else 1)
        audit = store.search(VectorQuery(embedding=(1.0, 0.0), include_excluded=True))[0]
        assert audit.chunk == original.chunk
        assert audit.published_at == original.published_at
        assert audit.score == original.score
        assert audit.excluded is excluded


def test_sync_rejects_missing_current_run_scores(store):
    chunk = DocumentChunk(chunk_id="chunk", document_id="document", ordinal=0, content="Evidence.")
    with pytest.raises(ValueError, match="score unavailable"):
        SynchronizeChunkExclusions(InMemoryChunkScoreRepository(), store).execute((chunk,), run_id="missing")


def test_missing_vector_identifiers_fail_before_updating_other_payloads(store):
    chunk = DocumentChunk(chunk_id="known", document_id="document", ordinal=0, content="Evidence.")
    store.upsert((EmbeddedChunk(chunk=chunk, company="META", published_at=date(2025, 1, 1), embedding=(1.0, 0.0)),))
    with pytest.raises(ValueError, match="indexed chunk unavailable"):
        store.set_excluded({"known": True, "missing": True})
    assert len(store.search(VectorQuery(embedding=(1.0, 0.0)))) == 1
