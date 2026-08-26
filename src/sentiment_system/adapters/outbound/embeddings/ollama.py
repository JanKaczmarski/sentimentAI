"""OpenAI-compatible Ollama embedding adapter for local semantic vectors."""

from typing import Any

from openai import OpenAI

from sentiment_system.application.ports.embeddings import Embedding


class OllamaEmbeddingProvider:
    """Generate real local embeddings through an Ollama-compatible endpoint."""

    def __init__(self, *, model_name: str, base_url: str, api_key: str, client: Any | None = None) -> None:
        if not model_name.strip():
            raise ValueError("model_name is required")
        if not base_url.strip():
            raise ValueError("base_url is required")
        if not api_key.strip():
            raise ValueError("api_key is required")
        self._model_name = model_name
        self._client = client or OpenAI(api_key=api_key, base_url=base_url)
        self._dimension: int | None = None

    @property
    def dimension(self) -> int:
        """Return the dimension established by the first embedding response."""
        if self._dimension is None:
            raise RuntimeError("embedding dimension is unknown until embed is called")
        return self._dimension

    def embed(self, text: str) -> Embedding:
        """Return one immutable vector and reject malformed provider responses."""
        if not isinstance(text, str) or not text.strip():
            raise ValueError("text must be a non-empty string")
        try:
            response = self._client.embeddings.create(model=self._model_name, input=text)
            values = response.data[0].embedding
        except Exception as error:
            raise RuntimeError("embedding provider request failed") from error
        if (
            not isinstance(values, list)
            or not values
            or any(isinstance(value, bool) or not isinstance(value, (int, float)) for value in values)
        ):
            raise RuntimeError("embedding provider returned an invalid vector")
        embedding = tuple(float(value) for value in values)
        if self._dimension is None:
            self._dimension = len(embedding)
        elif len(embedding) != self._dimension:
            raise RuntimeError("embedding provider returned an inconsistent dimension")
        return embedding
