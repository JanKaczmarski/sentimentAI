"""Runtime configuration loaded by the composition root."""

import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal, cast

from sentiment_system.adapters.outbound.embeddings.local import LocalSentenceTransformerEmbeddings
from sentiment_system.adapters.outbound.embeddings.mock import DeterministicEmbeddings
from sentiment_system.adapters.outbound.embeddings.ollama import OllamaEmbeddingProvider
from sentiment_system.adapters.outbound.llm.local_llama import LocalLlamaLLMScorer
from sentiment_system.adapters.outbound.llm.mock import DeterministicLLMScorer
from sentiment_system.application.ports.embeddings import EmbeddingProvider
from sentiment_system.application.ports.llm import LLMScorer

EmbeddingBackend = Literal["local", "mock", "ollama"]
LLMBackend = Literal["deterministic", "ollama"]


class EmbeddingConfigurationError(ValueError):
    """Raised when embedding settings are unsafe or invalid."""


@dataclass(frozen=True, slots=True)
class EmbeddingConfig:
    """Runtime settings controlling the embedding provider and research guard."""

    backend: EmbeddingBackend
    model_name: str = "BAAI/bge-small-en-v1.5"
    base_url: str = "http://localhost:11434/v1"
    api_key: str = "ollama"
    research_mode: bool = False

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> "EmbeddingConfig":
        """Load embedding settings without silently changing the requested backend."""
        values = os.environ if environ is None else environ
        backend_value = values.get("EMBEDDING_BACKEND", "local").strip().casefold()
        if backend_value not in {"local", "mock", "ollama"}:
            raise EmbeddingConfigurationError("EMBEDDING_BACKEND must be 'local', 'mock', or 'ollama'")
        model_name = values.get("EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5").strip()
        base_url = values.get("EMBEDDING_BASE_URL", "http://localhost:11434/v1").strip()
        api_key = values.get("EMBEDDING_API_KEY", "ollama").strip()
        if not model_name:
            raise EmbeddingConfigurationError("EMBEDDING_MODEL is required")
        if not base_url or not api_key:
            raise EmbeddingConfigurationError("EMBEDDING_BASE_URL and EMBEDDING_API_KEY are required")
        app_env = values.get("APP_ENV", "development").strip().casefold()
        return cls(
            backend=cast(EmbeddingBackend, backend_value),
            model_name=model_name,
            base_url=base_url,
            api_key=api_key,
            research_mode=app_env in {"research", "production"},
        )


def build_embedding_provider(config: EmbeddingConfig) -> EmbeddingProvider:
    """Build the configured provider and fail closed for research-mode mocks."""
    if config.backend == "mock":
        if config.research_mode:
            raise EmbeddingConfigurationError("mock embeddings are not allowed in research mode")
        return DeterministicEmbeddings()
    if config.backend == "ollama":
        return OllamaEmbeddingProvider(model_name=config.model_name, base_url=config.base_url, api_key=config.api_key)
    return LocalSentenceTransformerEmbeddings(config.model_name)


class LLMConfigurationError(ValueError):
    """Raised when LLM settings are invalid or unsafe for the selected mode."""


@dataclass(frozen=True, slots=True)
class LLMConfig:
    """Runtime settings for deterministic tests or an explicit real provider."""

    backend: LLMBackend
    model_name: str = "llama3.1:8b"
    base_url: str = "http://localhost:11434/v1"
    api_key: str = "ollama"
    research_mode: bool = False

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> "LLMConfig":
        """Load provider settings and reject deterministic scoring in research mode."""
        values = os.environ if environ is None else environ
        backend_value = values.get("LLM_BACKEND", "deterministic").strip().casefold()
        if backend_value not in {"deterministic", "ollama"}:
            raise LLMConfigurationError("LLM_BACKEND must be 'deterministic' or 'ollama'")
        app_env = values.get("APP_ENV", "development").strip().casefold()
        research_mode = app_env in {"research", "production"}
        if backend_value == "deterministic" and research_mode:
            raise LLMConfigurationError("deterministic LLM scoring is not allowed in research mode")
        model_name = values.get("LLM_MODEL", "llama3.1:8b").strip()
        base_url = values.get("LLM_BASE_URL", "http://localhost:11434/v1").strip()
        api_key = values.get("LLM_API_KEY", "ollama").strip()
        if not model_name or not base_url or not api_key:
            raise LLMConfigurationError("LLM_MODEL, LLM_BASE_URL, and LLM_API_KEY are required")
        return cls(
            backend=cast(LLMBackend, backend_value),
            model_name=model_name,
            base_url=base_url,
            api_key=api_key,
            research_mode=research_mode,
        )


def build_llm_scorer(config: LLMConfig) -> LLMScorer:
    """Build exactly the configured scorer; real-provider failures never become mocks."""
    if config.backend == "deterministic":
        return DeterministicLLMScorer()
    return LocalLlamaLLMScorer(model_name=config.model_name, base_url=config.base_url, api_key=config.api_key)
