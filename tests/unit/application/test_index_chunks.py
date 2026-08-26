"""Tests for embedding and indexing document chunks."""

from datetime import date

import pytest

from sentiment_system.adapters.outbound.embeddings.mock import DeterministicEmbeddings
from sentiment_system.adapters.outbound.persistence.in_memory import InMemoryDocumentRepository
from sentiment_system.adapters.outbound.vector.in_memory import InMemoryVectorStore
from sentiment_system.application.ports.vector_store import VectorQuery
from sentiment_system.application.use_cases.index_chunks import IndexChunks, MissingSourceDocumentError
from sentiment_system.domain.documents import DocumentChunk, SourceDocument


def test_index_chunks_embeds_cleaned_content_and_preserves_document_metadata() -> None:
    document = SourceDocument(
        document_id="document-1",
        source_id="source-1",
        company="AAPL",
        source="fixture",
        published_at=date(2025, 1, 30),
        document_type="company_communication",
        raw_content="Raw content.",
        cleaned_content="Clean content.",
    )
    chunk = DocumentChunk(chunk_id="chunk-1", document_id=document.document_id, ordinal=0, content="Clean chunk.")
    vector_store = InMemoryVectorStore()

    indexed = IndexChunks(
        InMemoryDocumentRepository((document,)),
        DeterministicEmbeddings(),
        vector_store,
    ).execute((chunk,))

    assert indexed == 1
    matches = vector_store.search(VectorQuery(embedding=DeterministicEmbeddings().embed(chunk.content), company="AAPL"))
    assert matches[0].chunk == chunk
    assert matches[0].published_at == document.published_at


def test_index_chunks_rejects_chunks_without_source_documents() -> None:
    chunk = DocumentChunk(chunk_id="chunk-1", document_id="missing", ordinal=0, content="Clean chunk.")

    with pytest.raises(MissingSourceDocumentError, match="missing"):
        IndexChunks(InMemoryDocumentRepository(), DeterministicEmbeddings(), InMemoryVectorStore()).execute((chunk,))
