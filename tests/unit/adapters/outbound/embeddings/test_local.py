"""Tests for the local semantic embedding adapter."""

from collections.abc import Sequence

from sentiment_system.adapters.outbound.embeddings.local import LocalSentenceTransformerEmbeddings


class FakeSentenceTransformer:
    """Small model substitute that records the provider contract."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, bool, bool]] = []

    def get_sentence_embedding_dimension(self) -> int:
        return 3

    def encode(self, text: str, *, normalize_embeddings: bool, convert_to_numpy: bool) -> Sequence[float]:
        self.calls.append((text, normalize_embeddings, convert_to_numpy))
        return (0.1, 0.2, 0.3)


def test_local_embeddings_use_sentence_transformer_and_expose_immutable_vectors() -> None:
    model = FakeSentenceTransformer()
    provider = LocalSentenceTransformerEmbeddings("local-model", model_factory=lambda _: model)

    assert provider.dimension == 3
    assert provider.embed("company update") == (0.1, 0.2, 0.3)
    assert model.calls == [("company update", True, True)]
