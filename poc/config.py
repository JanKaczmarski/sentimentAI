"""
Centralized configuration for the Sentiment Analysis POC.
"""

from pathlib import Path

# --- Paths ---
PROJECT_ROOT = Path(__file__).parent.parent
POC_DIR = PROJECT_ROOT / "poc"
DATA_DIR = PROJECT_ROOT / "data"
SQLITE_DB_PATH = DATA_DIR / "poc.db"

# Colleague's data (raw SEC filings)
COLLEAGUE_REPO = PROJECT_ROOT.parent / "llm-sentiment-analysis"
RAW_FILINGS_DIR = COLLEAGUE_REPO / "data" / "raw"

# --- Embedding model ---
EMBEDDING_MODEL = "BAAI/bge-small-en-v1.5"
EMBEDDING_DIM = 384  # bge-small-en-v1.5 output dimension

# --- Chunking ---
SENTENCES_PER_CHUNK = 3
MIN_SENTENCES_PER_CHUNK = 2
MAX_TOKENS_PER_CHUNK = 2000

# --- Qdrant (in-memory for POC) ---
QDRANT_COLLECTION_NAME = "sec_filings"

# --- Batch processing ---
BATCH_SCHEDULE_HOUR = 2  # Run batch at 02:00 daily
BATCH_SCHEDULE_MINUTE = 0

# --- LLM ---
LLM_BACKEND = "mock"  # "mock" | "cyfronet"
CYFRONET_MODEL_ID = "meta-llama/Llama-3.3-70B-Instruct"

# --- Prompt template (adapted from colleague's prompt_template.md) ---
SENTIMENT_PROMPT_TEMPLATE = """You are a financial sentiment classifier analyzing documents \
for a {investment_style} investor with {risk_tolerance} risk tolerance \
and a {investment_horizon} investment horizon.

Your task is to classify the overall sentiment of the following financial document excerpts \
about {company_ticker}.

Documents:
{context}

Rules:
1. Consider the investor profile when assessing sentiment. A risk-averse, long-term passive \
investor may view the same information differently than an aggressive short-term trader.
2. If documents contain negative outlook, declining metrics, or analyst concerns, lean NEGATIVE.
3. If documents show strong growth, beat expectations, or positive guidance, lean POSITIVE.
4. If information is mixed or inconclusive, classify as NEUTRAL.
5. "reasoning" must be brief and concrete, referencing specific facts from the documents.
6. Return valid JSON only. No markdown fences. No extra text.

Return exactly this schema:
{{"reasoning": "<brief explanation>", "sentiment": "POSITIVE|NEGATIVE|NEUTRAL", "confidence": <float 0-1>}}"""

# --- POC demo tickers (subset for fast demo) ---
POC_TICKERS = ["NVDA", "AAPL", "MSFT"]
