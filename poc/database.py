"""
SQLite database layer for user profiles, sentiment results, and batch runs.
"""

import json
import sqlite3
from datetime import date, datetime
from pathlib import Path
from typing import Optional

from poc.config import SQLITE_DB_PATH
from poc.models import (
    BatchRun,
    ComputationType,
    InvestmentHorizon,
    InvestmentStyle,
    RiskTolerance,
    Sentiment,
    SentimentResult,
    UserProfile,
    UserProfileCreate,
)

_CREATE_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS user_profiles (
    user_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    risk_tolerance TEXT NOT NULL DEFAULT 'medium',
    investment_horizon TEXT NOT NULL DEFAULT 'long_term',
    investment_style TEXT NOT NULL DEFAULT 'passive',
    watchlist TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sentiment_results (
    result_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    company_ticker TEXT NOT NULL,
    sentiment TEXT NOT NULL,
    confidence REAL NOT NULL,
    reasoning TEXT NOT NULL,
    source_chunks TEXT NOT NULL DEFAULT '[]',
    computation_type TEXT NOT NULL DEFAULT 'batch',
    batch_date TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES user_profiles(user_id)
);

CREATE TABLE IF NOT EXISTS batch_runs (
    batch_id TEXT PRIMARY KEY,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    tickers_processed INTEGER DEFAULT 0,
    users_processed INTEGER DEFAULT 0,
    results_generated INTEGER DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'running'
);

CREATE INDEX IF NOT EXISTS idx_sentiment_user_ticker_date
    ON sentiment_results(user_id, company_ticker, batch_date);

CREATE INDEX IF NOT EXISTS idx_sentiment_batch_date
    ON sentiment_results(batch_date);
"""


class Database:
    def __init__(self, db_path: Path = SQLITE_DB_PATH):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.db_path = db_path
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self._get_conn() as conn:
            conn.executescript(_CREATE_TABLES_SQL)

    # --- User Profiles ---

    def create_user(self, data: UserProfileCreate) -> UserProfile:
        user = UserProfile(**data.model_dump())
        with self._get_conn() as conn:
            conn.execute(
                """INSERT INTO user_profiles
                   (user_id, name, risk_tolerance, investment_horizon, investment_style, watchlist, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    user.user_id,
                    user.name,
                    user.risk_tolerance.value,
                    user.investment_horizon.value,
                    user.investment_style.value,
                    json.dumps(user.watchlist),
                    user.created_at.isoformat(),
                ),
            )
        return user

    def get_user(self, user_id: str) -> Optional[UserProfile]:
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM user_profiles WHERE user_id = ?", (user_id,)
            ).fetchone()
        if not row:
            return None
        return self._row_to_user(row)

    def get_all_users(self) -> list[UserProfile]:
        with self._get_conn() as conn:
            rows = conn.execute("SELECT * FROM user_profiles").fetchall()
        return [self._row_to_user(r) for r in rows]

    def _row_to_user(self, row: sqlite3.Row) -> UserProfile:
        return UserProfile(
            user_id=row["user_id"],
            name=row["name"],
            risk_tolerance=RiskTolerance(row["risk_tolerance"]),
            investment_horizon=InvestmentHorizon(row["investment_horizon"]),
            investment_style=InvestmentStyle(row["investment_style"]),
            watchlist=json.loads(row["watchlist"]),
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    # --- Sentiment Results ---

    def save_sentiment_result(self, result: SentimentResult):
        with self._get_conn() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO sentiment_results
                   (result_id, user_id, company_ticker, sentiment, confidence,
                    reasoning, source_chunks, computation_type, batch_date, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    result.result_id,
                    result.user_id,
                    result.company_ticker,
                    result.sentiment.value,
                    result.confidence,
                    result.reasoning,
                    json.dumps(result.source_chunks),
                    result.computation_type.value,
                    result.batch_date.isoformat(),
                    result.created_at.isoformat(),
                ),
            )

    def get_latest_sentiment(
        self, user_id: str, ticker: str
    ) -> Optional[SentimentResult]:
        with self._get_conn() as conn:
            row = conn.execute(
                """SELECT * FROM sentiment_results
                   WHERE user_id = ? AND company_ticker = ?
                   ORDER BY batch_date DESC, created_at DESC
                   LIMIT 1""",
                (user_id, ticker),
            ).fetchone()
        if not row:
            return None
        return self._row_to_result(row)

    def get_sentiments_for_user(
        self, user_id: str, batch_date: Optional[date] = None
    ) -> list[SentimentResult]:
        with self._get_conn() as conn:
            if batch_date:
                rows = conn.execute(
                    """SELECT * FROM sentiment_results
                       WHERE user_id = ? AND batch_date = ?
                       ORDER BY company_ticker""",
                    (user_id, batch_date.isoformat()),
                ).fetchall()
            else:
                # Latest result per ticker
                rows = conn.execute(
                    """SELECT sr.* FROM sentiment_results sr
                       INNER JOIN (
                           SELECT company_ticker, MAX(batch_date) as max_date
                           FROM sentiment_results WHERE user_id = ?
                           GROUP BY company_ticker
                       ) latest ON sr.company_ticker = latest.company_ticker
                                AND sr.batch_date = latest.max_date
                       WHERE sr.user_id = ?
                       ORDER BY sr.company_ticker""",
                    (user_id, user_id),
                ).fetchall()
        return [self._row_to_result(r) for r in rows]

    def _row_to_result(self, row: sqlite3.Row) -> SentimentResult:
        return SentimentResult(
            result_id=row["result_id"],
            user_id=row["user_id"],
            company_ticker=row["company_ticker"],
            sentiment=Sentiment(row["sentiment"]),
            confidence=row["confidence"],
            reasoning=row["reasoning"],
            source_chunks=json.loads(row["source_chunks"]),
            computation_type=ComputationType(row["computation_type"]),
            batch_date=date.fromisoformat(row["batch_date"]),
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    # --- Batch Runs ---

    def save_batch_run(self, run: BatchRun):
        with self._get_conn() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO batch_runs
                   (batch_id, started_at, finished_at, tickers_processed,
                    users_processed, results_generated, status)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    run.batch_id,
                    run.started_at.isoformat(),
                    run.finished_at.isoformat() if run.finished_at else None,
                    run.tickers_processed,
                    run.users_processed,
                    run.results_generated,
                    run.status,
                ),
            )

    def get_latest_batch_run(self) -> Optional[BatchRun]:
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM batch_runs ORDER BY started_at DESC LIMIT 1"
            ).fetchone()
        if not row:
            return None
        return BatchRun(
            batch_id=row["batch_id"],
            started_at=datetime.fromisoformat(row["started_at"]),
            finished_at=datetime.fromisoformat(row["finished_at"]) if row["finished_at"] else None,
            tickers_processed=row["tickers_processed"],
            users_processed=row["users_processed"],
            results_generated=row["results_generated"],
            status=row["status"],
        )
