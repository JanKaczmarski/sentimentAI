"""Tests for the real local Ollama embedding adapter."""

from types import SimpleNamespace

from sentiment_system.adapters.outbound.embeddings.ollama import OllamaEmbeddingProvider


class FakeEmbeddings:
    """Return a provider-shaped embedding response."""

    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def create(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        return SimpleNamespace(data=[SimpleNamespace(embedding=[0.1, 0.2, 0.3])])


def test_ollama_embeddings_use_the_openai_compatible_contract() -> None:
    embeddings = FakeEmbeddings()
    provider = OllamaEmbeddingProvider(
        model_name="nomic-embed-text",
        base_url="http://localhost:11434/v1",
        api_key="ollama",
        client=SimpleNamespace(embeddings=embeddings),
    )

    assert provider.embed("semantic source text") == (0.1, 0.2, 0.3)
    assert provider.dimension == 3
    assert embeddings.calls == [{"model": "nomic-embed-text", "input": "semantic source text"}]
