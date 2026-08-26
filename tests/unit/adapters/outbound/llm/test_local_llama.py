"""Tests for the OpenAI-compatible local Llama scoring adapter."""

import json
from types import SimpleNamespace

import pytest

from sentiment_system.adapters.outbound.llm.local_llama import LLMProviderError, LocalLlamaLLMScorer
from sentiment_system.application.ports.llm import TokenUsage
from sentiment_system.domain.documents import DocumentChunk


class FakeCompletions:
    """Capture one structured completion request and return a provider-shaped response."""

    def __init__(self, content: str) -> None:
        self.content = content
        self.kwargs: dict[str, object] = {}

    def create(self, **kwargs: object) -> object:
        self.kwargs = kwargs
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=self.content))],
            usage=SimpleNamespace(prompt_tokens=17, completion_tokens=9),
        )


class FakeClient:
    """Minimal OpenAI client surface used by the adapter test."""

    def __init__(self, completions: FakeCompletions) -> None:
        self.chat = SimpleNamespace(completions=completions)


def _chunk() -> DocumentChunk:
    return DocumentChunk(
        chunk_id="chunk-1",
        document_id="document-1",
        ordinal=0,
        content="Revenue increased while operating costs declined.",
    )


def test_local_llama_returns_validated_structured_scores_and_usage() -> None:
    completions = FakeCompletions(json.dumps({"score": 0.72, "confidence": 0.81, "importance_score": 0.93}))
    scorer = LocalLlamaLLMScorer(
        model_name="llama3.1:8b",
        base_url="http://localhost:11434/v1",
        api_key="ollama",
        client=FakeClient(completions),
    )

    result = scorer.score_chunk(_chunk())

    assert result.sentiment.score == 0.72
    assert result.sentiment.confidence == 0.81
    assert result.importance_score == 0.93
    assert result.parsed_output == {"score": 0.72, "confidence": 0.81, "importance_score": 0.93}
    assert result.token_usage == TokenUsage(prompt_tokens=17, completion_tokens=9)
    assert completions.kwargs["model"] == "llama3.1:8b"
    assert completions.kwargs["response_format"] == {"type": "json_object"}


@pytest.mark.parametrize(
    "content",
    [
        "not json",
        json.dumps({"score": 0.7, "confidence": 0.8}),
        json.dumps({"score": 1.2, "confidence": 0.8, "importance_score": 0.9}),
    ],
)
def test_local_llama_rejects_invalid_provider_output_without_fallback(content: str) -> None:
    completions = FakeCompletions(content)
    scorer = LocalLlamaLLMScorer(
        model_name="llama3.1:8b",
        base_url="http://localhost:11434/v1",
        api_key="ollama",
        client=FakeClient(completions),
    )

    with pytest.raises(LLMProviderError):
        scorer.score_chunk(_chunk())
