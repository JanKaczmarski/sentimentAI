"""Deterministic in-memory vector store for unit and contract tests."""

from collections.abc import Iterable, Sequence
from math import sqrt

from sentiment_system.application.ports.vector_store import EmbeddedChunk, VectorMatch, VectorQuery


class InMemoryVectorStore:
    """Perform deterministic cosine-similarity search over embedded chunks."""

    def __init__(self, chunks: Iterable[EmbeddedChunk] = ()) -> None:
        self._chunks: dict[str, EmbeddedChunk] = {}
        self._dimension: int | None = None
        self.upsert(tuple(chunks))

    def upsert(self, chunks: Sequence[EmbeddedChunk]) -> None:
        """Insert or replace chunks and enforce one vector dimension."""
        for embedded in chunks:
            dimension = len(embedded.embedding)
            if self._dimension is None:
                self._dimension = dimension
            elif self._dimension != dimension:
                raise ValueError("all embeddings must have the same dimension")
            self._chunks[embedded.chunk.chunk_id] = embedded

    def search(self, query: VectorQuery) -> tuple[VectorMatch, ...]:
        """Filter candidates before returning stable descending similarity."""
        if self._dimension is not None and len(query.embedding) != self._dimension:
            raise ValueError("query embedding has a different dimension")

        matches = []
        for embedded in self._chunks.values():
            if query.company is not None and embedded.company != query.company:
                continue
            if query.as_of is not None and embedded.published_at > query.as_of:
                continue
            if embedded.excluded and not query.include_excluded:
                continue
            matches.append(
                VectorMatch(
                    chunk=embedded.chunk,
                    company=embedded.company,
                    published_at=embedded.published_at,
                    score=_cosine_similarity(query.embedding, embedded.embedding),
                    excluded=embedded.excluded,
                )
            )

        matches.sort(key=lambda match: (-match.score, match.chunk.chunk_id))
        return tuple(matches[: query.limit])


def _cosine_similarity(left: tuple[float, ...], right: tuple[float, ...]) -> float:
    if len(left) != len(right):
        raise ValueError("vectors must have the same dimension")
    left_norm = sqrt(sum(value * value for value in left))
    right_norm = sqrt(sum(value * value for value in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return sum(left_value * right_value for left_value, right_value in zip(left, right, strict=True)) / (
        left_norm * right_norm
    )
