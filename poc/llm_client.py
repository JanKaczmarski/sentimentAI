"""
LLM client — mock implementation for POC + interface for real Cyfronet LLAMA.

The mock returns plausible-looking sentiment results based on simple heuristics.
When ready, switch LLM_BACKEND in config to "cyfronet" and provide the real
model endpoint.
"""

import json
import logging
import random
from abc import ABC, abstractmethod

from poc.config import LLM_BACKEND, SENTIMENT_PROMPT_TEMPLATE
from poc.models import Sentiment, UserProfile

logger = logging.getLogger(__name__)


class BaseLLMClient(ABC):
    @abstractmethod
    def analyze_sentiment(
        self,
        company_ticker: str,
        context_chunks: list[str],
        user_profile: UserProfile,
    ) -> dict:
        """Analyze sentiment of context chunks for a given user profile.

        Returns dict with keys: sentiment, confidence, reasoning
        """
        ...

    def _build_prompt(
        self,
        company_ticker: str,
        context_chunks: list[str],
        user_profile: UserProfile,
    ) -> str:
        context = "\n\n---\n\n".join(
            f"[Document {i+1}]\n{chunk}" for i, chunk in enumerate(context_chunks)
        )
        return SENTIMENT_PROMPT_TEMPLATE.format(
            investment_style=user_profile.investment_style.value,
            risk_tolerance=user_profile.risk_tolerance.value,
            investment_horizon=user_profile.investment_horizon.value,
            company_ticker=company_ticker,
            context=context,
        )


class MockLLMClient(BaseLLMClient):
    """Mock LLM that returns heuristic-based sentiment for POC testing."""

    # Simple keyword-based heuristic
    _POSITIVE_KEYWORDS = [
        "growth", "exceeded", "beat", "strong", "record", "increased",
        "raised guidance", "momentum", "outperformed", "expansion",
        "revenue growth", "profit", "upside", "optimistic",
    ]
    _NEGATIVE_KEYWORDS = [
        "decline", "missed", "below", "weak", "loss", "decreased",
        "lowered guidance", "headwinds", "underperformed", "contraction",
        "revenue decline", "impairment", "downside", "concerns", "risk",
    ]

    def analyze_sentiment(
        self,
        company_ticker: str,
        context_chunks: list[str],
        user_profile: UserProfile,
    ) -> dict:
        prompt = self._build_prompt(company_ticker, context_chunks, user_profile)

        combined_text = " ".join(context_chunks).lower()

        pos_count = sum(1 for kw in self._POSITIVE_KEYWORDS if kw in combined_text)
        neg_count = sum(1 for kw in self._NEGATIVE_KEYWORDS if kw in combined_text)

        total = pos_count + neg_count
        if total == 0:
            sentiment = Sentiment.NEUTRAL
            confidence = 0.4 + random.uniform(0, 0.15)
            reasoning = (
                f"[MOCK] No strong positive or negative signals found in "
                f"{len(context_chunks)} document chunks for {company_ticker}."
            )
        elif pos_count > neg_count:
            sentiment = Sentiment.POSITIVE
            confidence = min(0.95, 0.5 + (pos_count - neg_count) / total * 0.4)
            reasoning = (
                f"[MOCK] Found {pos_count} positive vs {neg_count} negative signals "
                f"in {len(context_chunks)} chunks for {company_ticker}. "
                f"Key positive indicators detected in recent filings."
            )
        elif neg_count > pos_count:
            sentiment = Sentiment.NEGATIVE
            confidence = min(0.95, 0.5 + (neg_count - pos_count) / total * 0.4)
            reasoning = (
                f"[MOCK] Found {neg_count} negative vs {pos_count} positive signals "
                f"in {len(context_chunks)} chunks for {company_ticker}. "
                f"Concerns identified in recent filings."
            )
        else:
            sentiment = Sentiment.NEUTRAL
            confidence = 0.45 + random.uniform(0, 0.1)
            reasoning = (
                f"[MOCK] Mixed signals: {pos_count} positive and {neg_count} negative "
                f"indicators in {len(context_chunks)} chunks for {company_ticker}."
            )

        logger.info(
            f"[MockLLM] {company_ticker} -> {sentiment.value} "
            f"(confidence={confidence:.2f})"
        )

        return {
            "sentiment": sentiment.value,
            "confidence": round(confidence, 3),
            "reasoning": reasoning,
        }


class CyfronetLLMClient(BaseLLMClient):
    """
    Placeholder for real LLAMA integration on Cyfronet.

    Two possible approaches:
    1. vLLM server with OpenAI-compatible API (if Cyfronet exposes it)
    2. Direct HuggingFace transformers load (like colleague's code) via SLURM job

    For batch processing, option 2 (SLURM) is more practical.
    This class implements option 1 (API) as a placeholder.
    """

    def __init__(self, api_url: str = "http://localhost:8000/v1"):
        self.api_url = api_url
        logger.warning(
            "CyfronetLLMClient initialized — requires a running vLLM server "
            "or equivalent OpenAI-compatible endpoint."
        )

    def analyze_sentiment(
        self,
        company_ticker: str,
        context_chunks: list[str],
        user_profile: UserProfile,
    ) -> dict:
        prompt = self._build_prompt(company_ticker, context_chunks, user_profile)

        # TODO: implement actual API call when Cyfronet endpoint is available
        # import httpx
        # response = httpx.post(
        #     f"{self.api_url}/chat/completions",
        #     json={
        #         "model": CYFRONET_MODEL_ID,
        #         "messages": [
        #             {"role": "system", "content": "You are a financial sentiment classifier."},
        #             {"role": "user", "content": prompt},
        #         ],
        #         "temperature": 0,
        #         "max_tokens": 200,
        #     },
        #     timeout=120,
        # )
        # result_text = response.json()["choices"][0]["message"]["content"]
        # return json.loads(result_text)

        raise NotImplementedError(
            "CyfronetLLMClient requires a running LLM endpoint. "
            "Set LLM_BACKEND='mock' in config for POC testing."
        )


def get_llm_client() -> BaseLLMClient:
    """Factory function — returns the configured LLM client."""
    if LLM_BACKEND == "mock":
        return MockLLMClient()
    elif LLM_BACKEND == "cyfronet":
        return CyfronetLLMClient()
    else:
        raise ValueError(f"Unknown LLM_BACKEND: {LLM_BACKEND}")
