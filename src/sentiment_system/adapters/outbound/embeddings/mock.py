"""Deterministic mock embedding adapter for isolated tests only."""

import hashlib

from sentiment_system.application.ports.embeddings import Embedding


class DeterministicEmbeddings:
    """Generate stable hash vectors for tests; not for thesis results."""

    def __init__(self, dimension: int = 8) -> None:
        if isinstance(dimension, bool) or not isinstance(dimension, int) or dimension <= 0:
            raise ValueError("dimension must be a positive integer")
        self._dimension = dimension

    @property
    def dimension(self) -> int:
        """Return the configured vector dimension."""
        return self._dimension

    def embed(self, text: str) -> Embedding:
        """Return a deterministic vector derived from the text bytes."""
        if not isinstance(text, str):
            raise ValueError("text must be a string")
        digest = hashlib.sha256(text.encode("utf-8")).digest()
        return tuple((digest[index % len(digest)] / 127.5) - 1 for index in range(self._dimension))
