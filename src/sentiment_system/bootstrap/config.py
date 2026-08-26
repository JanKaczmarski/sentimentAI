"""Runtime configuration loaded by the composition root."""

import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal, cast

from sentiment_system.adapters.outbound.embeddings.local import LocalSentenceTransformerEmbeddings
from sentiment_system.adapters.outbound.embeddings.mock import DeterministicEmbeddings
from sentiment_system.application.ports.embeddings import EmbeddingProvider

EmbeddingBackend = Literal["local", "mock"]


class EmbeddingConfigurationError(ValueError):
    """Raised when embedding settings are unsafe or invalid."""


@dataclass(frozen=True, slots=True)
class EmbeddingConfig:
    """Runtime settings controlling the embedding provider and research guard."""

    backend: EmbeddingBackend
    model_name: str = "BAAI/bge-small-en-v1.5"
    research_mode: bool = False

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> "EmbeddingConfig":
        """Load embedding settings without silently changing the requested backend."""
        values = os.environ if environ is None else environ
        backend_value = values.get("EMBEDDING_BACKEND", "local").strip().casefold()
        if backend_value not in {"local", "mock"}:
            raise EmbeddingConfigurationError("EMBEDDING_BACKEND must be 'local' or 'mock'")
        model_name = values.get("EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5").strip()
        if not model_name:
            raise EmbeddingConfigurationError("EMBEDDING_MODEL is required")
        app_env = values.get("APP_ENV", "development").strip().casefold()
        return cls(
            backend=cast(EmbeddingBackend, backend_value),
            model_name=model_name,
            research_mode=app_env in {"research", "production"},
        )


def build_embedding_provider(config: EmbeddingConfig) -> EmbeddingProvider:
    """Build the configured provider and fail closed for research-mode mocks."""
    if config.backend == "mock":
        if config.research_mode:
            raise EmbeddingConfigurationError("mock embeddings are not allowed in research mode")
        return DeterministicEmbeddings()
    return LocalSentenceTransformerEmbeddings(config.model_name)
