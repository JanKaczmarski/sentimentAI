"""Local semantic embedding adapter used for thesis results."""

from collections.abc import Sequence
from typing import Callable, Protocol, cast

from sentence_transformers import SentenceTransformer

from sentiment_system.application.ports.embeddings import Embedding


class _SentenceTransformerModel(Protocol):
    """Small internal view of the provider SDK used by this adapter."""

    def get_sentence_embedding_dimension(self) -> int:
        """Return the model's fixed output dimension."""

    def encode(self, text: str, *, normalize_embeddings: bool, convert_to_numpy: bool) -> Sequence[float]:
        """Encode one text value."""


class LocalSentenceTransformerEmbeddings:
    """Generate semantic vectors with a locally loaded SentenceTransformer model."""

    def __init__(
        self,
        model_name: str,
        *,
        model_factory: Callable[[str], _SentenceTransformerModel] | None = None,
    ) -> None:
        if not isinstance(model_name, str) or not model_name.strip():
            raise ValueError("model_name is required")
        self._model_name = model_name
        self._model_factory = model_factory or _load_sentence_transformer
        self._model: _SentenceTransformerModel | None = None

    @property
    def dimension(self) -> int:
        """Return the model dimension, loading the model on first use."""
        dimension = self._model_or_load().get_sentence_embedding_dimension()
        if isinstance(dimension, bool) or not isinstance(dimension, int) or dimension <= 0:
            raise ValueError("embedding model must expose a positive dimension")
        return dimension

    def embed(self, text: str) -> Embedding:
        """Return one normalized semantic vector without a mock fallback."""
        if not isinstance(text, str):
            raise ValueError("text must be a string")
        values = self._model_or_load().encode(text, normalize_embeddings=True, convert_to_numpy=True)
        embedding = tuple(float(value) for value in values)
        if not embedding or len(embedding) != self.dimension:
            raise ValueError("embedding model returned an unexpected dimension")
        return embedding

    def _model_or_load(self) -> _SentenceTransformerModel:
        if self._model is None:
            self._model = self._model_factory(self._model_name)
        return self._model


def _load_sentence_transformer(model_name: str) -> _SentenceTransformerModel:
    return cast(_SentenceTransformerModel, SentenceTransformer(model_name))
