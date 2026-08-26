"""Integration coverage for Qdrant-backed chunk indexing and retrieval."""

import os
from datetime import date
from uuid import uuid4

import pytest
from qdrant_client import QdrantClient

from sentiment_system.adapters.outbound.embeddings.mock import DeterministicEmbeddings
from sentiment_system.adapters.outbound.persistence.in_memory import InMemoryDocumentRepository
from sentiment_system.adapters.outbound.vector.qdrant import QdrantVectorStore
from sentiment_system.application.ports.vector_store import VectorQuery
from sentiment_system.application.use_cases.index_chunks import IndexChunks
from sentiment_system.domain.documents import DocumentChunk, SourceDocument


@pytest.mark.integration
def test_qdrant_indexing_preserves_lineage_and_applies_filters() -> None:
    url = os.getenv("QDRANT_TEST_URL")
    if not url:
        pytest.skip("QDRANT_TEST_URL is not configured")

    collection = f"test_chunks_{uuid4().hex}"
    client = QdrantClient(url=url)
    store = QdrantVectorStore(client=client, collection_name=collection)
    document = SourceDocument(
        document_id=f"document-{uuid4().hex}",
        source_id="source-1",
        company="AAPL",
        source="fixture",
        published_at=date(2025, 1, 30),
        document_type="company_communication",
        raw_content="Raw source.",
        cleaned_content="Clean source.",
    )
    chunk = DocumentChunk(
        chunk_id=f"chunk-{uuid4().hex}",
        document_id=document.document_id,
        ordinal=0,
        content="Clean source.",
    )

    try:
        assert (
            IndexChunks(InMemoryDocumentRepository((document,)), DeterministicEmbeddings(2), store).execute((chunk,))
            == 1
        )
        matches = store.search(
            VectorQuery(
                embedding=DeterministicEmbeddings(2).embed(chunk.content),
                company="AAPL",
                as_of=date(2025, 1, 31),
            )
        )
    finally:
        client.delete_collection(collection)

    assert len(matches) == 1
    assert matches[0].chunk == chunk
    assert matches[0].published_at == document.published_at
