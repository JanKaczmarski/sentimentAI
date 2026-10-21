"""Synchronize the vector projection from authoritative per-run score records."""

from collections.abc import Sequence

from sentiment_system.application.ports.repositories import ChunkScoreRepository
from sentiment_system.application.ports.vector_store import VectorStore
from sentiment_system.domain.documents import DocumentChunk


class SynchronizeChunkExclusions:
    """Update payloads after scoring without generating new embeddings."""

    def __init__(self, scores: ChunkScoreRepository, vectors: VectorStore) -> None:
        self._scores = scores
        self._vectors = vectors

    def execute(self, chunks: Sequence[DocumentChunk], *, run_id: str) -> int:
        exclusions = {}
        for chunk in chunks:
            score = next(
                (score for score in self._scores.list_for_chunk(chunk.chunk_id) if score.run_id == run_id), None
            )
            if score is None:
                raise ValueError(f"score unavailable for chunk {chunk.chunk_id} in run {run_id}")
            exclusions[chunk.chunk_id] = score.excluded
        self._vectors.set_excluded(exclusions)
        return len(exclusions)
