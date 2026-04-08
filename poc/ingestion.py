"""
Data ingestion — loads raw SEC filings from colleague's data/raw/ directory.

For the POC we read pre-downloaded text files. In production this would be
replaced by live SEC API polling + email ingestion (IMAP).
"""

import logging
import re
from datetime import date
from pathlib import Path

from poc.config import RAW_FILINGS_DIR
from poc.models import Document

logger = logging.getLogger(__name__)

# Filename pattern: 2025-02-26_0001045810-25-000021_8-K.txt
_FILENAME_RE = re.compile(
    r"^(?P<date>\d{4}-\d{2}-\d{2})_(?P<accession>[\d-]+)_(?P<form>.+)\.txt$"
)


def _normalize_text(text: str) -> str:
    """Basic text normalization (adapted from colleague's sec_api_client.normalize_text)."""
    # Collapse multiple whitespace
    text = re.sub(r"\s+", " ", text)
    # Remove null bytes
    text = text.replace("\x00", "")
    return text.strip()


def load_filings_for_ticker(
    ticker: str,
    raw_dir: Path = RAW_FILINGS_DIR,
    max_files: int | None = None,
) -> list[Document]:
    """Load raw SEC filings for a single ticker from the data directory."""
    ticker_dir = raw_dir / ticker
    if not ticker_dir.exists():
        logger.warning(f"No data directory for ticker {ticker}: {ticker_dir}")
        return []

    documents = []
    txt_files = sorted(ticker_dir.glob("*.txt"))

    if max_files:
        txt_files = txt_files[:max_files]

    for filepath in txt_files:
        match = _FILENAME_RE.match(filepath.name)
        filing_date = None
        doc_type = ""

        if match:
            try:
                filing_date = date.fromisoformat(match.group("date"))
            except ValueError:
                pass
            doc_type = match.group("form")

        raw_content = filepath.read_text(encoding="utf-8", errors="replace")
        raw_content = _normalize_text(raw_content)

        if len(raw_content) < 50:
            logger.debug(f"Skipping too-short file: {filepath.name}")
            continue

        doc = Document(
            company_ticker=ticker,
            filename=filepath.name,
            filing_date=filing_date,
            doc_type=doc_type,
            raw_content=raw_content,
        )
        documents.append(doc)

    logger.info(f"Loaded {len(documents)} filings for {ticker}")
    return documents


def load_filings_for_tickers(
    tickers: list[str],
    raw_dir: Path = RAW_FILINGS_DIR,
    max_files_per_ticker: int | None = None,
) -> dict[str, list[Document]]:
    """Load filings for multiple tickers. Returns {ticker: [Document, ...]}."""
    result = {}
    for ticker in tickers:
        docs = load_filings_for_ticker(ticker, raw_dir, max_files_per_ticker)
        if docs:
            result[ticker] = docs
    return result


def get_available_tickers(raw_dir: Path = RAW_FILINGS_DIR) -> list[str]:
    """List all tickers that have data available."""
    if not raw_dir.exists():
        return []
    return sorted(
        d.name for d in raw_dir.iterdir() if d.is_dir() and any(d.glob("*.txt"))
    )
