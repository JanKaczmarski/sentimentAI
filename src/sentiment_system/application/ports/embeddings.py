"""Port for generating semantic embeddings."""

from typing import Protocol, runtime_checkable

Embedding = tuple[float, ...]


@runtime_checkable
class EmbeddingProvider(Protocol):
    """Generate vectors without exposing a model or provider SDK."""

    @property
    def dimension(self) -> int:
        """Return the fixed vector dimension produced by this provider."""

    def embed(self, text: str) -> Embedding:
        """Encode one text value as an immutable vector."""
