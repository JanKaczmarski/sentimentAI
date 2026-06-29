"""
Document processing — chunking and embedding generation.

Chunking logic adapted from colleague's llm_sentiment_analysis/stage3_embeddings.py.

Embedding: tries to load real SentenceTransformer model (BAAI/bge-small-en-v1.5).
If unavailable (SSL issues, no internet), falls back to a deterministic hash-based
mock embedding that preserves basic similarity properties for POC testing.
"""

import hashlib
import logging
import re
import struct

from poc.config import (
    EMBEDDING_DIM,
    EMBEDDING_MODEL,
    MAX_TOKENS_PER_CHUNK,
    MIN_SENTENCES_PER_CHUNK,
    SENTENCES_PER_CHUNK,
)
from poc.models import Document, DocumentChunk

logger = logging.getLogger(__name__)

# --- Chunking (from colleague's code) ---

_ABBREVIATIONS = {
    "e.g.", "i.e.", "etc.", "vs.", "mr.", "mrs.", "ms.", "dr.", "prof.",
    "inc.", "ltd.", "co.", "corp.", "st.", "jr.", "sr.", "u.s.", "u.k.",
}

_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")


def split_into_sentences(text: str) -> list[str]:
    text = text.strip()
    if not text:
        return []

    parts = _SENTENCE_SPLIT_RE.split(text)
    sentences: list[str] = []
    i = 0

    while i < len(parts):
        s = parts[i].strip()
        if not s:
            i += 1
            continue

        s_lower = s.lower()
        if any(s_lower.endswith(abbr) for abbr in _ABBREVIATIONS) and i + 1 < len(parts):
            s = (s + " " + parts[i + 1].strip()).strip()
            i += 2
        else:
            i += 1

        sentences.append(s)

    return sentences


def chunk_text_by_sentences(
    text: str,
    sentences_per_chunk: int = SENTENCES_PER_CHUNK,
    min_sentences_per_chunk: int = MIN_SENTENCES_PER_CHUNK,
    max_tokens: int = MAX_TOKENS_PER_CHUNK,
) -> list[str]:
    sentences = split_into_sentences(text)
    if not sentences:
        return []

    max_chars = (max_tokens * 4) if max_tokens else None

    chunks: list[str] = []
    buf: list[str] = []

    def buf_len_chars() -> int:
        return sum(len(x) for x in buf) + max(0, len(buf) - 1)

    for sent in sentences:
        if max_chars and buf and (buf_len_chars() + 1 + len(sent) > max_chars):
            chunks.append(" ".join(buf).strip())
            buf = []

        buf.append(sent)

        if len(buf) >= sentences_per_chunk:
            chunks.append(" ".join(buf).strip())
            buf = []

    if buf:
        if len(buf) == 1 and chunks and min_sentences_per_chunk >= 2:
            prev = chunks.pop()
            prev_sents = split_into_sentences(prev)
            if len(prev_sents) >= 3:
                new_prev = " ".join(prev_sents[:-1]).strip()
                new_last = (prev_sents[-1] + " " + buf[0]).strip()
                chunks.append(new_prev)
                chunks.append(new_last)
            else:
                chunks.append(prev)
                chunks.append(" ".join(buf).strip())
        else:
            chunks.append(" ".join(buf).strip())

    return chunks


# --- Embedding ---

_embedder = None  # Will be a SentenceTransformer or "mock" sentinel
_USE_MOCK_EMBEDDINGS = False


def _mock_embed(text: str) -> list[float]:
    """Deterministic hash-based embedding for POC fallback.

    Uses the text hash as a seed for a pseudo-random but deterministic
    vector. Produces clean floats (no NaN/Inf) with unit norm.
    """
    import random as _rng

    seed = int(hashlib.sha256(text.lower().encode()).hexdigest(), 16) % (2**32)
    gen = _rng.Random(seed)
    vec = [gen.gauss(0, 1) for _ in range(EMBEDDING_DIM)]

    # Normalize to unit length
    norm = sum(x * x for x in vec) ** 0.5
    if norm > 0:
        vec = [x / norm for x in vec]
    return vec


def _init_embedder():
    """Try loading the real model; fall back to mock if it fails.

    If ``POC_FORCE_MOCK_EMBEDDINGS=1`` is set, skip the network attempt
    entirely. This avoids ~30s of SSL retries on networks where
    huggingface.co is blocked (e.g. corporate Cisco Umbrella).
    """
    global _embedder, _USE_MOCK_EMBEDDINGS

    if _embedder is not None:
        return

    import os
    if os.environ.get("POC_FORCE_MOCK_EMBEDDINGS") == "1":
        logger.warning(
            "POC_FORCE_MOCK_EMBEDDINGS=1 — skipping SentenceTransformer load, "
            "using deterministic hash-based mock embeddings."
        )
        _embedder = "mock"
        _USE_MOCK_EMBEDDINGS = True
        return

    try:
        from sentence_transformers import SentenceTransformer

        logger.info(f"Loading embedding model: {EMBEDDING_MODEL}")
        _embedder = SentenceTransformer(EMBEDDING_MODEL)
        _USE_MOCK_EMBEDDINGS = False
        logger.info("Embedding model loaded successfully.")
    except Exception as e:
        logger.warning(
            f"Could not load SentenceTransformer ({e}). "
            f"Falling back to mock embeddings for POC."
        )
        _embedder = "mock"
        _USE_MOCK_EMBEDDINGS = True


def chunk_document(doc: Document) -> list[DocumentChunk]:
    """Split a document into chunks."""
    raw_chunks = chunk_text_by_sentences(doc.raw_content)
    return [
        DocumentChunk(
            doc_id=doc.doc_id,
            company_ticker=doc.company_ticker,
            chunk_index=i,
            content=text,
            filing_date=doc.filing_date,
        )
        for i, text in enumerate(raw_chunks)
    ]


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Generate embeddings for a list of texts.

    Uses real SentenceTransformer if available, otherwise deterministic mock.
    """
    _init_embedder()

    if _USE_MOCK_EMBEDDINGS:
        return [_mock_embed(t) for t in texts]

    embeddings = _embedder.encode(texts, convert_to_numpy=True, show_progress_bar=False)
    return embeddings.tolist()
