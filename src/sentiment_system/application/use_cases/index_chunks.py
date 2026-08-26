"""Use case for embedding and indexing normalized document chunks."""

from collections.abc import Sequence

from sentiment_system.application.ports.embeddings import EmbeddingProvider
from sentiment_system.application.ports.repositories import DocumentRepository
from sentiment_system.application.ports.vector_store import EmbeddedChunk, VectorStore
from sentiment_system.domain.documents import DocumentChunk


class MissingSourceDocumentError(ValueError):
    """Raised when a chunk does not have a persisted source document."""


class IndexChunks:
    """Embed cleaned chunks and persist their retrieval metadata."""

    def __init__(
        self,
        documents: DocumentRepository,
        embeddings: EmbeddingProvider,
        vector_store: VectorStore,
    ) -> None:
        self._documents = documents
        self._embeddings = embeddings
        self._vector_store = vector_store

    def execute(self, chunks: Sequence[DocumentChunk]) -> int:
        """Index chunks in one upsert while retaining source lineage metadata."""
        embedded_chunks = []
        for chunk in chunks:
            document = self._documents.get(chunk.document_id)
            if document is None:
                raise MissingSourceDocumentError(f"source document not found: {chunk.document_id}")
            embedded_chunks.append(
                EmbeddedChunk(
                    chunk=chunk,
                    company=document.company,
                    published_at=document.published_at,
                    embedding=self._embeddings.embed(chunk.content),
                )
            )
        self._vector_store.upsert(tuple(embedded_chunks))
        return len(embedded_chunks)
