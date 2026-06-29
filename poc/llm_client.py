"""
LLM client for the Sentiment Analysis POC.

Three backends (selected via ``config.LLM_BACKEND``):

* ``groq``     — production-ish: Groq-hosted Llama-3.3-70B via OpenAI-compatible API.
                  Used for the POC until Cyfronet is online.
* ``mock``     — keyword heuristic. **Dev/test only.** Must be opted into explicitly
                  in config; it is never used as a silent fallback.
* ``cyfronet`` — placeholder for real LLAMA running on AGH cluster (not yet wired).

Why an OpenAI-compatible client for Groq:
    Groq exposes the OpenAI ChatCompletions schema. Cyfronet, when set up, will
    most likely run vLLM which exposes the *same* schema. That means the swap
    from Groq -> Cyfronet should be a base_url + api_key change, not a rewrite.
"""

import json
import logging
import os
import random
import re
import time
from abc import ABC, abstractmethod

from poc import config as _config
from poc.config import (
    GROQ_API_KEY_ENV,
    GROQ_BASE_URL,
    GROQ_MODEL_ID,
    LLM_MAX_RETRIES,
    LLM_MIN_INTERVAL_SECONDS,
    LLM_TIMEOUT_SECONDS,
    SENTIMENT_PROMPT_TEMPLATE,
)
from poc.models import Sentiment, UserProfile

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Base
# ---------------------------------------------------------------------------


class BaseLLMClient(ABC):
    @abstractmethod
    def analyze_sentiment(
        self,
        company_ticker: str,
        context_chunks: list[str],
        user_profile: UserProfile,
    ) -> dict:
        """Analyze sentiment of context chunks for a given user profile.

        Returns dict with keys: sentiment, confidence, reasoning.
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


# ---------------------------------------------------------------------------
# Shared parsing / validation helpers
# ---------------------------------------------------------------------------


_VALID_SENTIMENTS = {"POSITIVE", "NEGATIVE", "NEUTRAL"}


def _extract_first_json_object(text: str) -> dict:
    """Recover the first JSON object from a model response.

    Llama-3.3 generally honors ``response_format={"type":"json_object"}``, but
    we still defensively strip markdown fences and find the outermost ``{...}``
    block. Adapted from the colleague's predict_sentiment_with_llama.py.
    """
    text = (text or "").strip()
    if not text:
        raise ValueError("Empty model response")

    # Best case: already raw JSON
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Strip ```json ... ``` fences if present
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.DOTALL)
    if fence:
        try:
            return json.loads(fence.group(1))
        except json.JSONDecodeError:
            pass

    # Last resort: greedy {...} from the first { to the last }
    match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if not match:
        raise ValueError(f"No JSON object found in model output: {text[:200]!r}")

    return json.loads(match.group(0))


def _validate_and_normalize(obj: dict, ticker: str) -> dict:
    """Coerce model output into the contract used by the rest of the system.

    Raises ValueError on missing/invalid sentiment so the caller can decide
    whether to retry, fall back, or surface as a NEUTRAL with diagnostic.
    """
    sentiment_raw = str(obj.get("sentiment", "")).strip().upper()
    if sentiment_raw not in _VALID_SENTIMENTS:
        raise ValueError(
            f"Invalid sentiment {sentiment_raw!r} for {ticker}; "
            f"expected one of {_VALID_SENTIMENTS}"
        )

    # Confidence: clamp to [0, 1]; default to 0.5 if missing/garbage
    try:
        confidence = float(obj.get("confidence", 0.5))
    except (TypeError, ValueError):
        confidence = 0.5
    confidence = max(0.0, min(1.0, confidence))

    reasoning = str(obj.get("reasoning", "")).strip()
    if not reasoning:
        reasoning = f"No reasoning provided by model for {ticker}."

    return {
        "sentiment": sentiment_raw,
        "confidence": round(confidence, 3),
        "reasoning": reasoning,
    }


# ---------------------------------------------------------------------------
# Mock (dev-only)
# ---------------------------------------------------------------------------


class MockLLMClient(BaseLLMClient):
    """Keyword-counting heuristic. Must be opted into via LLM_BACKEND='mock'.

    Reasoning fields are tagged with ``[MOCK]`` so callers can spot them in
    logs and DB rows.
    """

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
        # Build prompt for parity with real backend (also exercises the path)
        self._build_prompt(company_ticker, context_chunks, user_profile)

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
                f"[MOCK] Found {pos_count} positive vs {neg_count} negative "
                f"signals in {len(context_chunks)} chunks for {company_ticker}."
            )
        elif neg_count > pos_count:
            sentiment = Sentiment.NEGATIVE
            confidence = min(0.95, 0.5 + (neg_count - pos_count) / total * 0.4)
            reasoning = (
                f"[MOCK] Found {neg_count} negative vs {pos_count} positive "
                f"signals in {len(context_chunks)} chunks for {company_ticker}."
            )
        else:
            sentiment = Sentiment.NEUTRAL
            confidence = 0.45 + random.uniform(0, 0.1)
            reasoning = (
                f"[MOCK] Mixed signals: {pos_count} positive and {neg_count} "
                f"negative in {len(context_chunks)} chunks for {company_ticker}."
            )

        logger.info(
            "[MockLLM] %s -> %s (confidence=%.2f)",
            company_ticker, sentiment.value, confidence,
        )

        return {
            "sentiment": sentiment.value,
            "confidence": round(confidence, 3),
            "reasoning": reasoning,
        }


# ---------------------------------------------------------------------------
# Groq (real backend used for the POC)
# ---------------------------------------------------------------------------


class HostedLLMClient(BaseLLMClient):
    """OpenAI-compatible client. Defaults to Groq, but base_url/model are
    configurable so the same class can target Together / OpenRouter / vLLM
    on Cyfronet without code changes.

    Failure policy:
        * Transient errors (timeout, 5xx, rate limit) -> exponential backoff
          retry up to ``max_retries`` times.
        * Permanent errors after retries -> return a NEUTRAL result with the
          error string in ``reasoning``. This matches the defensive pattern in
          the colleague's predict_sentiment_with_llama.py and keeps the batch
          from aborting on a single bad ticker.
    """

    def __init__(
        self,
        api_key: str,
        base_url: str = GROQ_BASE_URL,
        model: str = GROQ_MODEL_ID,
        timeout_seconds: int = LLM_TIMEOUT_SECONDS,
        max_retries: int = LLM_MAX_RETRIES,
        min_interval_seconds: float = LLM_MIN_INTERVAL_SECONDS,
    ):
        # Local import to keep openai an optional dep at import time of this module
        from openai import OpenAI

        self.model = model
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.min_interval_seconds = min_interval_seconds
        self._last_call_at: float = 0.0  # monotonic timestamp of last attempt
        self._client = OpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=timeout_seconds,
            max_retries=0,  # we do our own retry to control backoff and logging
        )
        logger.info(
            "HostedLLMClient ready: base_url=%s model=%s timeout=%ss min_interval=%.1fs",
            base_url, model, timeout_seconds, min_interval_seconds,
        )

    def _throttle(self) -> None:
        """Sleep so consecutive API calls are spaced by at least
        ``min_interval_seconds``. Free-tier providers (Groq) enforce TPM caps
        and will 429 us if we burst — this is cheaper than retry-with-backoff.
        """
        if self.min_interval_seconds <= 0:
            return
        elapsed = time.monotonic() - self._last_call_at
        wait = self.min_interval_seconds - elapsed
        if wait > 0:
            logger.info("Throttling LLM call: sleeping %.1fs", wait)
            time.sleep(wait)
        self._last_call_at = time.monotonic()

    def analyze_sentiment(
        self,
        company_ticker: str,
        context_chunks: list[str],
        user_profile: UserProfile,
    ) -> dict:
        prompt = self._build_prompt(company_ticker, context_chunks, user_profile)

        messages = [
            {
                "role": "system",
                "content": (
                    "You are a precise financial sentiment classifier. "
                    "Always return valid JSON only. No prose, no markdown fences."
                ),
            },
            {"role": "user", "content": prompt},
        ]

        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                # Space out calls to stay under Groq free-tier TPM cap.
                self._throttle()
                completion = self._client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    temperature=0,
                    response_format={"type": "json_object"},
                    max_tokens=300,
                )
                raw = completion.choices[0].message.content or ""
                parsed = _extract_first_json_object(raw)
                result = _validate_and_normalize(parsed, company_ticker)
                logger.info(
                    "[Groq] %s -> %s (confidence=%.2f)",
                    company_ticker, result["sentiment"], result["confidence"],
                )
                return result
            except Exception as exc:  # noqa: BLE001 — we want to handle everything
                last_error = exc
                if attempt < self.max_retries:
                    backoff = 2 ** attempt
                    logger.warning(
                        "Groq call failed for %s (attempt %d/%d): %s. "
                        "Retrying in %ss",
                        company_ticker, attempt + 1, self.max_retries + 1,
                        exc, backoff,
                    )
                    time.sleep(backoff)
                else:
                    logger.error(
                        "Groq call failed for %s after %d attempts: %s",
                        company_ticker, self.max_retries + 1, exc,
                    )

        # All retries exhausted — return NEUTRAL with diagnostic so batch continues
        return {
            "sentiment": Sentiment.NEUTRAL.value,
            "confidence": 0.0,
            "reasoning": (
                f"LLM call failed for {company_ticker}: "
                f"{type(last_error).__name__}: {last_error}"
            ),
        }


# ---------------------------------------------------------------------------
# Cyfronet placeholder (unchanged shape; will be implemented when endpoint exists)
# ---------------------------------------------------------------------------


class CyfronetLLMClient(BaseLLMClient):
    """Placeholder for AGH Cyfronet LLAMA. When their vLLM/OpenAI-compatible
    endpoint is reachable, this can either:
      (a) subclass HostedLLMClient with the Cyfronet base_url, or
      (b) speak whatever bespoke protocol Cyfronet exposes.
    For now: not implemented; selecting it raises at construction time.
    """

    def __init__(self, *args, **kwargs):
        raise NotImplementedError(
            "CyfronetLLMClient is not yet wired up. Use LLM_BACKEND='groq' "
            "for the POC, or LLM_BACKEND='mock' for offline dev."
        )

    def analyze_sentiment(self, *args, **kwargs):  # pragma: no cover
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Factory — fail loud, never silently fall back to mock
# ---------------------------------------------------------------------------


def get_llm_client() -> BaseLLMClient:
    """Construct the configured LLM client.

    Failure policy:
        * If LLM_BACKEND='groq' but no API key in env -> raise. Do NOT fall
          back to mock silently; the user explicitly asked for a real model.
        * Mock is only returned when LLM_BACKEND='mock' is set explicitly.
    """
    backend = _config.LLM_BACKEND.lower()

    if backend == "mock":
        logger.warning(
            "LLM_BACKEND='mock' — using keyword heuristic. "
            "Sentiment results will be tagged [MOCK] and are NOT real LLM output."
        )
        return MockLLMClient()

    if backend == "groq":
        api_key = os.environ.get(GROQ_API_KEY_ENV)
        if not api_key:
            raise RuntimeError(
                f"LLM_BACKEND='groq' requires {GROQ_API_KEY_ENV} in environment. "
                f"Get a free key from https://console.groq.com and set it in .env, "
                f"or set LLM_BACKEND='mock' in poc/config.py for offline dev."
            )
        return HostedLLMClient(api_key=api_key)

    if backend == "cyfronet":
        return CyfronetLLMClient()

    raise ValueError(
        f"Unknown LLM_BACKEND={LLM_BACKEND!r}. "
        f"Valid options: 'groq', 'mock', 'cyfronet'."
    )
