"""OpenAI-compatible adapter for a local or self-hosted Llama model."""

import json
from collections.abc import Mapping
from typing import Any

from openai import OpenAI

from sentiment_system.application.ports.llm import ChunkScoringResult, TokenUsage
from sentiment_system.domain.documents import DocumentChunk
from sentiment_system.domain.sentiment import SentimentScore


class LLMProviderError(RuntimeError):
    """Raised when a configured provider cannot return valid structured output."""


class LocalLlamaLLMScorer:
    """Score chunks through an OpenAI-compatible Ollama endpoint without fallback."""

    prompt = (
        "Score the source text independently of any investor thesis. Return only a JSON object with exactly these "
        "numeric fields: score, confidence, importance_score. Each value must be between 0 and 1. "
        "score is polarity where 0 is negative, 0.5 is neutral, and 1 is positive. "
        "importance_score is general evidence value."
    )

    def __init__(self, *, model_name: str, base_url: str, api_key: str, client: Any | None = None) -> None:
        if not model_name.strip():
            raise ValueError("model_name is required")
        if not base_url.strip():
            raise ValueError("base_url is required")
        if not api_key.strip():
            raise ValueError("api_key is required")
        self._model_name = model_name
        self._client = client or OpenAI(api_key=api_key, base_url=base_url)

    def score_chunk(self, chunk: DocumentChunk, *, context: str = "") -> ChunkScoringResult:
        """Call the provider and reject transport, parsing, or schema failures explicitly."""
        user_content = f"Source chunk:\n{chunk.content}"
        if context.strip():
            user_content = f"Context:\n{context}\n\n{user_content}"
        try:
            response = self._client.chat.completions.create(
                model=self._model_name,
                messages=[
                    {"role": "system", "content": self.prompt},
                    {"role": "user", "content": user_content},
                ],
                temperature=0,
                response_format={"type": "json_object"},
            )
            raw_response = response.choices[0].message.content
        except Exception as error:
            raise LLMProviderError("LLM provider request failed") from error

        if not isinstance(raw_response, str) or not raw_response.strip():
            raise LLMProviderError("LLM provider returned an empty response")
        parsed_output = _parse_output(raw_response)
        return ChunkScoringResult(
            sentiment=SentimentScore(
                score=_number(parsed_output, "score"),
                confidence=_number(parsed_output, "confidence"),
            ),
            importance_score=_number(parsed_output, "importance_score"),
            raw_response=raw_response,
            parsed_output=parsed_output,
            token_usage=_token_usage(response),
        )


def _parse_output(raw_response: str) -> dict[str, object]:
    try:
        payload = json.loads(raw_response)
    except json.JSONDecodeError as error:
        raise LLMProviderError("LLM provider returned invalid JSON") from error
    if not isinstance(payload, dict) or set(payload) != {"score", "confidence", "importance_score"}:
        raise LLMProviderError("LLM provider returned an unexpected scoring schema")
    for key in payload:
        _number(payload, key)
    return payload


def _number(payload: Mapping[str, object], key: str) -> float:
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= 1:
        raise LLMProviderError(f"LLM provider field {key} must be between 0 and 1")
    return float(value)


def _token_usage(response: Any) -> TokenUsage | None:
    usage = getattr(response, "usage", None)
    if usage is None:
        return None
    prompt_tokens = getattr(usage, "prompt_tokens", None)
    completion_tokens = getattr(usage, "completion_tokens", None)
    if (
        isinstance(prompt_tokens, bool)
        or not isinstance(prompt_tokens, int)
        or prompt_tokens < 0
        or isinstance(completion_tokens, bool)
        or not isinstance(completion_tokens, int)
        or completion_tokens < 0
    ):
        raise LLMProviderError("LLM provider returned invalid token usage")
    return TokenUsage(prompt_tokens=prompt_tokens, completion_tokens=completion_tokens)
