"""Tests for embedding and indexing document chunks."""

from dataclasses import replace
from datetime import date

import pytest

from sentiment_system.adapters.outbound.embeddings.mock import DeterministicEmbeddings
from sentiment_system.adapters.outbound.persistence.in_memory import InMemoryDocumentRepository
from sentiment_system.adapters.outbound.vector.in_memory import InMemoryVectorStore
from sentiment_system.application.ports.vector_store import VectorQuery
from sentiment_system.application.use_cases.index_chunks import IndexChunks, MissingSourceDocumentError
from sentiment_system.domain.documents import DocumentChunk, SourceDocument


class CountingEmbeddings(DeterministicEmbeddings):
    def __init__(self):
        super().__init__()
        self.calls = 0

    def embed(self, text):
        self.calls += 1
        return super().embed(text)


def test_index_chunks_reuses_only_compatible_vectors_and_repairs_missing_points():
    document = SourceDocument("doc", "source", "META", "fixture", date(2025, 1, 1), "release", "Raw.", "Clean.")
    chunk = DocumentChunk("chunk", "doc", 0, "Clean.", "processing-v2")
    vectors = InMemoryVectorStore()
    embeddings = CountingEmbeddings()
    documents = InMemoryDocumentRepository((document,))

    def index(model="model-a", store=vectors):
        return IndexChunks(documents, embeddings, store, embedding_configuration={"backend": "mock", "model": model})

    first = index().execute_with_counts((chunk,))
    assert (first.indexed_chunk_count, first.embedded_chunk_count, first.reused_chunk_count) == (1, 1, 0)
    second = index().execute_with_counts((chunk,))
    assert (second.indexed_chunk_count, second.embedded_chunk_count, second.reused_chunk_count) == (1, 0, 1)
    assert embeddings.calls == 1

    extra = DocumentChunk("extra", "doc", 1, "Additional content.", "processing-v2")
    assert index().execute_with_counts((chunk, extra)).embedded_chunk_count == 1
    assert embeddings.calls == 2
    assert index("model-b").execute_with_counts((chunk,)).embedded_chunk_count == 1
    assert index("model-b").execute_with_counts((replace(chunk, content="Changed."),)).embedded_chunk_count == 1
    assert index(store=InMemoryVectorStore()).execute_with_counts((chunk,)).embedded_chunk_count == 1


def test_index_chunks_upgrades_legacy_points_without_assuming_model_compatibility():
    document = SourceDocument("doc", "source", "META", "fixture", date(2025, 1, 1), "release", "Raw.", "Clean.")
    chunk = DocumentChunk("chunk", "doc", 0, "Clean.")
    documents, vectors, embeddings = (
        InMemoryDocumentRepository((document,)),
        InMemoryVectorStore(),
        CountingEmbeddings(),
    )
    IndexChunks(documents, embeddings, vectors).execute((chunk,))
    upgraded = IndexChunks(documents, embeddings, vectors, embedding_configuration={"model": "explicit-model"})
    assert upgraded.execute_with_counts((chunk,)).embedded_chunk_count == 1
    assert upgraded.execute_with_counts((chunk,)).reused_chunk_count == 1
    assert embeddings.calls == 2


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
