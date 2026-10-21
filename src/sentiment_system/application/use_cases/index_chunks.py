"""Use case for embedding and indexing normalized document chunks."""

from collections.abc import Sequence

from sentiment_system.application.ports.embeddings import EmbeddingProvider
from sentiment_system.application.ports.repositories import (
    ChunkScoreRepository,
    DocumentRepository,
    ExperimentRunRepository,
)
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
        *,
        scores: ChunkScoreRepository | None = None,
        runs: ExperimentRunRepository | None = None,
    ) -> None:
        self._documents = documents
        self._embeddings = embeddings
        self._vector_store = vector_store
        if (scores is None) != (runs is None):
            raise ValueError("scores and runs must be supplied together")
        self._scores = scores
        self._runs = runs

    def execute(self, chunks: Sequence[DocumentChunk]) -> int:
        """Index chunks in one upsert while retaining source lineage metadata."""
        embedded_chunks = []
        completed_runs = (
            {
                run.run_id: run
                for run in self._runs.list_runs()
                if run.status == "completed" and run.run_type in {"batch", "scoring"}
            }
            if self._runs
            else {}
        )
        for chunk in chunks:
            document = self._documents.get(chunk.document_id)
            if document is None:
                raise MissingSourceDocumentError(f"source document not found: {chunk.document_id}")
            previous = (
                max(
                    (score for score in self._scores.list_for_chunk(chunk.chunk_id) if score.run_id in completed_runs),
                    key=lambda score: (completed_runs[score.run_id].started_at, score.run_id),
                    default=None,
                )
                if self._scores
                else None
            )
            embedded_chunks.append(
                EmbeddedChunk(
                    chunk=chunk,
                    company=document.company,
                    published_at=document.published_at,
                    embedding=self._embeddings.embed(chunk.content),
                    excluded=previous.excluded if previous else False,
                )
            )
        self._vector_store.upsert(tuple(embedded_chunks))
        return len(embedded_chunks)
