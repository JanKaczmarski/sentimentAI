"""Tests for embedding runtime configuration."""

import pytest

from sentiment_system.adapters.outbound.embeddings.mock import DeterministicEmbeddings
from sentiment_system.bootstrap.config import (
    EmbeddingConfig,
    EmbeddingConfigurationError,
    LLMConfig,
    LLMConfigurationError,
    RuntimeConfig,
    RuntimeConfigurationError,
    build_embedding_provider,
)


@pytest.mark.parametrize("missing", ("DATABASE_URL", "QDRANT_URL", "SENTIMENT_DATA_ROOT"))
def test_research_runtime_requires_each_durable_dependency(tmp_path, missing) -> None:
    values = {
        "APP_ENV": "research",
        "DATABASE_URL": "postgresql://localhost/research",
        "QDRANT_URL": "http://localhost:6333",
        "SENTIMENT_DATA_ROOT": str(tmp_path),
    }
    values[missing] = "  "
    with pytest.raises(RuntimeConfigurationError, match=missing):
        RuntimeConfig.from_env(values)


@pytest.mark.parametrize(
    ("setting", "value"),
    (("DATABASE_URL", "sqlite:///:memory:"), ("QDRANT_URL", ":memory:"), ("SENTIMENT_DATA_ROOT", "/missing/cache")),
)
def test_research_runtime_rejects_invalid_durable_configuration(tmp_path, setting, value) -> None:
    values = {
        "APP_ENV": "research",
        "DATABASE_URL": "postgresql://localhost/research",
        "QDRANT_URL": "http://localhost:6333",
        "SENTIMENT_DATA_ROOT": str(tmp_path),
    }
    values[setting] = value
    with pytest.raises(RuntimeConfigurationError, match=setting):
        RuntimeConfig.from_env(values)


def test_research_guard_runs_before_building_any_provider(monkeypatch) -> None:
    from sentiment_system.bootstrap import container

    monkeypatch.setenv("APP_ENV", "research")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(container, "build_embedding_provider", lambda _: pytest.fail("guard must run first"))
    with pytest.raises(RuntimeConfigurationError, match="DATABASE_URL"):
        container.build_container()


def test_explicit_development_runtime_allows_in_memory_dependencies() -> None:
    config = RuntimeConfig.from_env({"APP_ENV": "development"})
    assert not config.research_mode
    assert config.database_url is config.qdrant_url is config.data_root is None


def test_research_startup_rejects_an_empty_cache_before_database_access(tmp_path, monkeypatch):
    from sentiment_system.bootstrap import container

    for key, value in {
        "APP_ENV": "research",
        "DATABASE_URL": "postgresql://localhost/research",
        "QDRANT_URL": "http://localhost:6333",
        "SENTIMENT_DATA_ROOT": str(tmp_path),
        "LLM_BACKEND": "ollama",
        "EMBEDDING_BACKEND": "local",
    }.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(container.PostgresDatabase, "migrate", lambda _: pytest.fail("cache guard must run first"))
    with pytest.raises(RuntimeConfigurationError, match="no supported cached source"):
        container.build_container()


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


def test_research_configuration_requires_a_real_llm_backend() -> None:
    with pytest.raises(LLMConfigurationError, match="deterministic LLM scoring is not allowed"):
        LLMConfig.from_env({"APP_ENV": "research", "LLM_BACKEND": "deterministic"})


def test_ollama_configuration_defaults_to_local_compatible_settings() -> None:
    config = LLMConfig.from_env({"APP_ENV": "research", "LLM_BACKEND": "ollama"})

    assert config.backend == "ollama"
    assert config.model_name == "llama3.1:8b"
    assert config.base_url == "http://localhost:11434/v1"
    assert config.api_key == "ollama"
    assert config.research_mode is True
