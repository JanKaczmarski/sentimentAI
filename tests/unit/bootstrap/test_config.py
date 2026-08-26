"""Tests for embedding runtime configuration."""

import pytest

from sentiment_system.adapters.outbound.embeddings.mock import DeterministicEmbeddings
from sentiment_system.bootstrap.config import EmbeddingConfig, EmbeddingConfigurationError, build_embedding_provider


def test_research_configuration_rejects_mock_embeddings() -> None:
    config = EmbeddingConfig.from_env({"APP_ENV": "research", "EMBEDDING_BACKEND": "mock"})

    with pytest.raises(EmbeddingConfigurationError, match="mock embeddings are not allowed"):
        build_embedding_provider(config)


def test_development_configuration_can_explicitly_use_deterministic_embeddings() -> None:
    config = EmbeddingConfig.from_env({"APP_ENV": "development", "EMBEDDING_BACKEND": "mock"})

    provider = build_embedding_provider(config)

    assert isinstance(provider, DeterministicEmbeddings)


def test_embedding_configuration_defaults_to_local_backend() -> None:
    config = EmbeddingConfig.from_env({})

    assert config.backend == "local"
    assert config.model_name == "BAAI/bge-small-en-v1.5"
    assert config.research_mode is False
