"""Port for indexing and retrieving embedded document chunks."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from math import isfinite
from typing import Protocol, runtime_checkable

from sentiment_system.application.ports.embeddings import Embedding
from sentiment_system.domain.documents import DocumentChunk


@dataclass(frozen=True, slots=True)
class EmbeddedChunk:
    """A chunk and the metadata required for leakage-safe retrieval."""

    chunk: DocumentChunk
    company: str
    published_at: date
    embedding: Embedding
    excluded: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.chunk, DocumentChunk):
            raise ValueError("chunk must be a DocumentChunk")
        if not isinstance(self.company, str) or not self.company.strip():
            raise ValueError("company is required")
        if not isinstance(self.published_at, date):
            raise ValueError("published_at must be a date")
        _validate_embedding(self.embedding)
        if not isinstance(self.excluded, bool):
            raise ValueError("excluded must be a boolean")


@dataclass(frozen=True, slots=True)
class VectorQuery:
    """Provider-neutral vector search filters."""

    embedding: Embedding
    company: str | None = None
    as_of: date | None = None
    include_excluded: bool = False
    limit: int = 10

    def __post_init__(self) -> None:
        _validate_embedding(self.embedding)
        if self.company is not None and (not isinstance(self.company, str) or not self.company.strip()):
            raise ValueError("company must be a non-empty string when provided")
        if self.as_of is not None and not isinstance(self.as_of, date):
            raise ValueError("as_of must be a date when provided")
        if not isinstance(self.include_excluded, bool):
            raise ValueError("include_excluded must be a boolean")
        if isinstance(self.limit, bool) or not isinstance(self.limit, int) or self.limit <= 0:
            raise ValueError("limit must be a positive integer")


@dataclass(frozen=True, slots=True)
class VectorMatch:
    """One retrieved chunk and its similarity score."""

    chunk: DocumentChunk
    company: str
    published_at: date
    score: float
    excluded: bool


@runtime_checkable
class VectorStore(Protocol):
    """Index and search chunks without exposing a vector database client."""

    def upsert(self, chunks: Sequence[EmbeddedChunk]) -> None:
        """Insert or replace embedded chunks by chunk identifier."""

    def search(self, query: VectorQuery) -> tuple[VectorMatch, ...]:
        """Return the highest-scoring matching chunks first."""


def _validate_embedding(embedding: Embedding) -> None:
    if not isinstance(embedding, tuple) or not embedding:
        raise ValueError("embedding must be a non-empty tuple")
    if any(
        not isinstance(value, (int, float)) or isinstance(value, bool) or not isfinite(value) for value in embedding
    ):
        raise ValueError("embedding values must be finite numbers")
