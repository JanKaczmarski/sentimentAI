"""Use case for embedding and indexing normalized document chunks."""

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from hashlib import sha256

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


@dataclass(frozen=True, slots=True)
class IndexingResult:
    """Confirmed indexed totals, distinguishing model work from compatible reuse."""

    indexed_chunk_count: int = 0
    embedded_chunk_count: int = 0
    reused_chunk_count: int = 0


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
        embedding_configuration: Mapping[str, object] | None = None,
    ) -> None:
        self._documents = documents
        self._embeddings = embeddings
        self._vector_store = vector_store
        if (scores is None) != (runs is None):
            raise ValueError("scores and runs must be supplied together")
        self._scores = scores
        self._runs = runs
        self.embedding_fingerprint = (
            sha256(
                json.dumps(dict(embedding_configuration), sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest()
            if embedding_configuration
            else None
        )

    def execute(self, chunks: Sequence[DocumentChunk]) -> int:
        """Return the total indexed count, retaining the existing batch contract."""
        return self.execute_with_counts(chunks).indexed_chunk_count

    def execute_with_counts(
        self, chunks: Sequence[DocumentChunk], *, on_progress: Callable[[IndexingResult], None] | None = None
    ) -> IndexingResult:
        """Reuse verified compatible points and repair missing/legacy points in bounded batches."""
        completed_runs = (
            {
                run.run_id: run
                for run in self._runs.list_runs()
                if run.status == "completed" and run.run_type in {"batch", "scoring"}
            }
            if self._runs
            else {}
        )
        result = IndexingResult()
        unique_chunks = tuple({chunk.chunk_id: chunk for chunk in chunks}.values())
        for offset in range(0, len(unique_chunks), 128):
            batch = unique_chunks[offset : offset + 128]
            existing = (
                self._vector_store.get_indexed(tuple(chunk.chunk_id for chunk in batch))
                if self.embedding_fingerprint
                else {}
            )
            embedded_chunks = []
            exclusions = {}
            reused = 0
            for chunk in batch:
                document = self._documents.get(chunk.document_id)
                if document is None:
                    raise MissingSourceDocumentError(f"source document not found: {chunk.document_id}")
                previous = (
                    max(
                        (
                            score
                            for score in self._scores.list_for_chunk(chunk.chunk_id)
                            if score.run_id in completed_runs
                        ),
                        key=lambda score: (completed_runs[score.run_id].started_at, score.run_id),
                        default=None,
                    )
                    if self._scores
                    else None
                )
                excluded = previous.excluded if previous else False
                point = existing.get(chunk.chunk_id)
                if (
                    point is not None
                    and point.chunk == chunk
                    and point.company == document.company
                    and point.published_at == document.published_at
                    and point.dimension > 0
                    and point.embedding_fingerprint == self.embedding_fingerprint
                ):
                    reused += 1
                    if point.excluded != excluded:
                        exclusions[chunk.chunk_id] = excluded
                    continue
                embedded_chunks.append(
                    EmbeddedChunk(
                        chunk=chunk,
                        company=document.company,
                        published_at=document.published_at,
                        embedding=self._embeddings.embed(chunk.content),
                        excluded=excluded,
                        embedding_fingerprint=self.embedding_fingerprint,
                    )
                )
            self._vector_store.upsert(tuple(embedded_chunks))
            self._vector_store.set_excluded(exclusions)
            result = IndexingResult(
                result.indexed_chunk_count + len(batch),
                result.embedded_chunk_count + len(embedded_chunks),
                result.reused_chunk_count + reused,
            )
            if on_progress:
                on_progress(result)
        return result
