"""
Batch sentiment processor — the core business logic.

Runs daily (or on-demand), computes sentiment for every ticker in every user's
watchlist, and stores results in SQLite.

Flow:
  1. Load all user profiles
  2. Collect unique tickers across all watchlists
  3. For each ticker:
     a. Ingest latest filings (from colleague's data/)
     b. Chunk & embed documents
     c. Index chunks in vector store
  4. For each (user, ticker) pair:
     a. Build a RAG query based on user profile
     b. Retrieve top-K relevant chunks from Qdrant
     c. Call LLM (mock or real) with context + user profile
     d. Save SentimentResult to SQLite
"""

import logging
from datetime import datetime

from poc.database import Database
from poc.ingestion import load_filings_for_ticker
from poc.llm_client import get_llm_client
from poc.models import BatchRun, ComputationType, Sentiment, SentimentResult
from poc.processing import chunk_document
from poc.vector_store import VectorStore

logger = logging.getLogger(__name__)


def run_batch(
    db: Database,
    vector_store: VectorStore,
    max_files_per_ticker: int | None = 5,
    top_k_chunks: int = 5,
) -> BatchRun:
    """Execute a full batch sentiment computation.

    Args:
        db: Database instance
        vector_store: VectorStore instance (should be pre-populated or will be populated here)
        max_files_per_ticker: Limit filings per ticker for POC speed
        top_k_chunks: Number of chunks to retrieve per RAG query
    """
    batch_run = BatchRun()
    db.save_batch_run(batch_run)

    logger.info(f"=== Starting batch run {batch_run.batch_id} ===")

    # 1. Load all users
    users = db.get_all_users()
    if not users:
        logger.warning("No users found. Create a user profile first.")
        batch_run.status = "completed"
        batch_run.finished_at = datetime.utcnow()
        db.save_batch_run(batch_run)
        return batch_run

    batch_run.users_processed = len(users)

    # 2. Collect unique tickers
    all_tickers: set[str] = set()
    for user in users:
        all_tickers.update(user.watchlist)

    if not all_tickers:
        logger.warning("No tickers in any user's watchlist.")
        batch_run.status = "completed"
        batch_run.finished_at = datetime.utcnow()
        db.save_batch_run(batch_run)
        return batch_run

    logger.info(f"Processing {len(all_tickers)} tickers for {len(users)} users")

    # 3. Ingest & index documents for each ticker
    for ticker in sorted(all_tickers):
        logger.info(f"--- Ingesting {ticker} ---")
        documents = load_filings_for_ticker(ticker, max_files=max_files_per_ticker)

        if not documents:
            logger.warning(f"No documents found for {ticker}, skipping")
            continue

        # Chunk all documents
        all_chunks = []
        for doc in documents:
            chunks = chunk_document(doc)
            all_chunks.extend(chunks)

        logger.info(f"{ticker}: {len(documents)} docs -> {len(all_chunks)} chunks")

        # Index in vector store
        vector_store.index_chunks(all_chunks)
        batch_run.tickers_processed += 1

    # 4. For each (user, ticker), compute sentiment via RAG + LLM
    llm = get_llm_client()

    for user in users:
        for ticker in user.watchlist:
            logger.info(
                f"Computing sentiment: user={user.name}, ticker={ticker}"
            )

            # RAG query tailored to user profile
            query = (
                f"Latest financial performance and outlook for {ticker}. "
                f"Key metrics, guidance, and analyst sentiment from recent filings."
            )

            # Retrieve relevant chunks
            search_results = vector_store.search(
                query_text=query,
                ticker=ticker,
                top_k=top_k_chunks,
            )

            if not search_results:
                logger.warning(f"No chunks found for {ticker}, skipping")
                continue

            context_chunks = [r["content"] for r in search_results]
            chunk_ids = [r["chunk_id"] for r in search_results]

            # Call LLM
            try:
                llm_result = llm.analyze_sentiment(
                    company_ticker=ticker,
                    context_chunks=context_chunks,
                    user_profile=user,
                )
            except Exception as e:
                logger.error(f"LLM error for {ticker}/{user.name}: {e}")
                continue

            # Save result
            result = SentimentResult(
                user_id=user.user_id,
                company_ticker=ticker,
                sentiment=Sentiment(llm_result["sentiment"]),
                confidence=llm_result["confidence"],
                reasoning=llm_result["reasoning"],
                source_chunks=chunk_ids,
                computation_type=ComputationType.BATCH,
            )
            db.save_sentiment_result(result)
            batch_run.results_generated += 1

            logger.info(
                f"  -> {result.sentiment.value} (confidence={result.confidence:.2f})"
            )

    # 5. Finalize
    batch_run.status = "completed"
    batch_run.finished_at = datetime.utcnow()
    db.save_batch_run(batch_run)

    logger.info(
        f"=== Batch run completed: {batch_run.results_generated} results "
        f"for {batch_run.tickers_processed} tickers, "
        f"{batch_run.users_processed} users ==="
    )

    return batch_run
