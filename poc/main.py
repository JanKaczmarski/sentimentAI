"""
Main entry point for the Sentiment Analysis POC.

Usage:
    # Start the server (with optional batch scheduler):
    cd /Users/jkaczmarski/private/sentimentAI
    .venv/bin/python -m poc.main

    # Run a one-shot demo (no server):
    .venv/bin/python -m poc.main --demo
"""

import argparse
import logging
import sys
from datetime import date

import uvicorn
from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI

from poc.api import init_api, router
from poc.batch import run_batch
from poc.config import BATCH_SCHEDULE_HOUR, BATCH_SCHEDULE_MINUTE, POC_TICKERS
from poc.database import Database
from poc.ingestion import get_available_tickers
from poc.models import InvestmentHorizon, InvestmentStyle, RiskTolerance, UserProfileCreate
from poc.vector_store import VectorStore

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="Sentiment Analysis POC",
        description="End-to-end POC: SEC filings -> chunking -> embeddings -> RAG -> LLM -> sentiment",
        version="0.1.0",
    )

    # Initialize shared resources
    db = Database()
    vs = VectorStore()

    # Inject into API
    init_api(db, vs)
    app.include_router(router)

    # Store on app.state for scheduler access
    app.state.db = db
    app.state.vs = vs

    return app


def start_scheduler(db: Database, vs: VectorStore) -> BackgroundScheduler:
    """Start APScheduler for daily batch processing."""
    scheduler = BackgroundScheduler()
    scheduler.add_job(
        func=lambda: run_batch(db, vs),
        trigger="cron",
        hour=BATCH_SCHEDULE_HOUR,
        minute=BATCH_SCHEDULE_MINUTE,
        id="daily_sentiment_batch",
        name="Daily sentiment batch computation",
        misfire_grace_time=3600,
    )
    scheduler.start()
    logger.info(
        f"Scheduler started. Batch runs daily at "
        f"{BATCH_SCHEDULE_HOUR:02d}:{BATCH_SCHEDULE_MINUTE:02d}"
    )
    return scheduler


def run_demo():
    """Run a one-shot demo: create user, run batch, print results."""
    logger.info("=" * 60)
    logger.info("  SENTIMENT ANALYSIS POC — DEMO MODE")
    logger.info("=" * 60)

    # Check available data
    available = get_available_tickers()
    logger.info(f"Available tickers in data: {len(available)}")

    demo_tickers = [t for t in POC_TICKERS if t in available]
    if not demo_tickers:
        logger.error(
            f"None of the POC tickers {POC_TICKERS} found in data. "
            f"Available: {available[:10]}..."
        )
        sys.exit(1)

    logger.info(f"Demo tickers: {demo_tickers}")

    # Initialize
    db = Database()
    vs = VectorStore()

    # Create a demo user
    user = db.create_user(
        UserProfileCreate(
            name="Demo Investor",
            risk_tolerance=RiskTolerance.MEDIUM,
            investment_horizon=InvestmentHorizon.LONG_TERM,
            investment_style=InvestmentStyle.PASSIVE,
            watchlist=demo_tickers,
        )
    )
    logger.info(f"Created demo user: {user.name} (id={user.user_id})")
    logger.info(f"  Watchlist: {user.watchlist}")
    logger.info(f"  Profile: {user.risk_tolerance.value} risk, {user.investment_horizon.value}, {user.investment_style.value}")

    # Run batch
    logger.info("\n--- Running batch sentiment computation ---\n")
    batch_run = run_batch(db, vs, max_files_per_ticker=3, top_k_chunks=5)

    # Print results
    logger.info("\n" + "=" * 60)
    logger.info("  RESULTS")
    logger.info("=" * 60)

    results = db.get_sentiments_for_user(user.user_id)
    if not results:
        logger.warning("No results generated!")
    else:
        for r in results:
            logger.info(f"\n  {r.company_ticker}:")
            logger.info(f"    Sentiment:  {r.sentiment.value}")
            logger.info(f"    Confidence: {r.confidence:.1%}")
            logger.info(f"    Reasoning:  {r.reasoning}")
            logger.info(f"    Batch date: {r.batch_date}")
            logger.info(f"    Chunks used: {len(r.source_chunks)}")

    # Vector store stats
    info = vs.get_collection_info()
    logger.info(f"\nVector store: {info['points_count']} chunks indexed")

    logger.info("\n" + "=" * 60)
    logger.info("  DEMO COMPLETE")
    logger.info("=" * 60)
    logger.info(
        "\nTo start the API server, run:\n"
        "  .venv/bin/python -m poc.main\n"
        "\nThen open http://localhost:8000/docs for the Swagger UI."
    )


def main():
    parser = argparse.ArgumentParser(description="Sentiment Analysis POC")
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Run a one-shot demo (no server)",
    )
    parser.add_argument(
        "--host", default="0.0.0.0", help="Server host (default: 0.0.0.0)"
    )
    parser.add_argument(
        "--port", type=int, default=8000, help="Server port (default: 8000)"
    )
    parser.add_argument(
        "--no-scheduler",
        action="store_true",
        help="Disable the daily batch scheduler",
    )
    args = parser.parse_args()

    if args.demo:
        run_demo()
        return

    # Server mode
    app = create_app()

    if not args.no_scheduler:
        scheduler = start_scheduler(app.state.db, app.state.vs)

    logger.info(f"Starting server at http://{args.host}:{args.port}")
    logger.info("API docs: http://localhost:8000/docs")
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
