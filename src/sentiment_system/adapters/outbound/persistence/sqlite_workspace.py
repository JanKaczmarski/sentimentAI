"""Disposable SQLite adapter for local ingestion-development state."""

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path

from sentiment_system.application.ports.ingestion_workspace import (
    IngestionCursor,
    WorkspaceDocument,
)
from sentiment_system.domain.companies import APPROVED_COMPANY_REGISTRY, Company, CompanyRegistry
from sentiment_system.domain.documents import SourceDocument


class SQLiteIngestionWorkspace:
    """Persist disposable ingestion state without exposing SQLite types."""

    def __init__(self, path: str | Path, registry: CompanyRegistry = APPROVED_COMPANY_REGISTRY) -> None:
        self._path = ":memory:" if str(path) == ":memory:" else str(Path(path).expanduser())
        self._registry = registry
        self.initialize()

    def initialize(self) -> None:
        """Create tables and seed companies without replacing existing state."""
        if self._path != ":memory:":
            Path(self._path).expanduser().parent.mkdir(parents=True, exist_ok=True)
        with self._connection() as connection:
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS companies (
                    ticker TEXT PRIMARY KEY,
                    display_name TEXT NOT NULL,
                    market_routing TEXT NOT NULL,
                    currency TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS development_documents (
                    document_id TEXT PRIMARY KEY,
                    source_id TEXT NOT NULL,
                    company TEXT NOT NULL REFERENCES companies(ticker),
                    source TEXT NOT NULL,
                    published_at TEXT NOT NULL,
                    document_type TEXT NOT NULL,
                    raw_content TEXT NOT NULL,
                    cleaned_content TEXT NOT NULL,
                    request_key TEXT NOT NULL,
                    raw_payload TEXT NOT NULL,
                    fetched_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS ingestion_cursors (
                    company TEXT NOT NULL REFERENCES companies(ticker),
                    source TEXT NOT NULL,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (company, source)
                );
                """)
            connection.executemany(
                """
                INSERT OR IGNORE INTO companies (ticker, display_name, market_routing, currency)
                VALUES (?, ?, ?, ?)
                """,
                (
                    (company.ticker, company.display_name, company.market_routing, company.currency)
                    for company in self._registry.companies
                ),
            )

    def list_companies(self) -> tuple[Company, ...]:
        """Return seeded companies in canonical registry order."""
        with self._connection() as connection:
            rows = connection.execute("SELECT ticker, display_name, market_routing, currency FROM companies").fetchall()
        companies = {
            row["ticker"]: Company(
                ticker=row["ticker"],
                display_name=row["display_name"],
                market_routing=row["market_routing"],
                currency=row["currency"],
            )
            for row in rows
        }
        return tuple(companies[ticker] for ticker in self._registry.tickers)

    def get_company(self, ticker: str) -> Company | None:
        """Return one seeded company, or ``None`` for an unknown ticker."""
        normalized = ticker.strip().upper() if isinstance(ticker, str) else ""
        with self._connection() as connection:
            row = connection.execute(
                "SELECT ticker, display_name, market_routing, currency FROM companies WHERE ticker = ?",
                (normalized,),
            ).fetchone()
        if row is None:
            return None
        return Company(
            ticker=row["ticker"],
            display_name=row["display_name"],
            market_routing=row["market_routing"],
            currency=row["currency"],
        )

    def record_document(self, record: WorkspaceDocument) -> None:
        """Insert or replace one development document and its raw payload."""
        if self.get_company(record.document.company) is None:
            raise ValueError(f"unsupported company ticker: {record.document.company}")
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO development_documents (
                    document_id, source_id, company, source, published_at,
                    document_type, raw_content, cleaned_content, request_key,
                    raw_payload, fetched_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(document_id) DO UPDATE SET
                    source_id = excluded.source_id,
                    company = excluded.company,
                    source = excluded.source,
                    published_at = excluded.published_at,
                    document_type = excluded.document_type,
                    raw_content = excluded.raw_content,
                    cleaned_content = excluded.cleaned_content,
                    request_key = excluded.request_key,
                    raw_payload = excluded.raw_payload,
                    fetched_at = excluded.fetched_at
                """,
                (
                    record.document.document_id,
                    record.document.source_id,
                    record.document.company,
                    record.document.source,
                    record.document.published_at.isoformat(),
                    record.document.document_type,
                    record.document.raw_content,
                    record.document.cleaned_content,
                    record.request_key,
                    record.raw_payload,
                    record.fetched_at.isoformat(),
                ),
            )

    def get_document(self, document_id: str) -> WorkspaceDocument | None:
        """Return one development document with its request metadata."""
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM development_documents WHERE document_id = ?",
                (document_id,),
            ).fetchone()
        if row is None:
            return None
        return WorkspaceDocument(
            document=SourceDocument(
                document_id=row["document_id"],
                source_id=row["source_id"],
                company=row["company"],
                source=row["source"],
                published_at=date.fromisoformat(row["published_at"]),
                document_type=row["document_type"],
                raw_content=row["raw_content"],
                cleaned_content=row["cleaned_content"],
            ),
            request_key=row["request_key"],
            raw_payload=row["raw_payload"],
            fetched_at=datetime.fromisoformat(row["fetched_at"]),
        )

    def update_cursor(self, cursor: IngestionCursor) -> None:
        """Insert or replace a source cursor without touching documents."""
        if self.get_company(cursor.company) is None:
            raise ValueError(f"unsupported company ticker: {cursor.company}")
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO ingestion_cursors (company, source, value, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(company, source) DO UPDATE SET
                    value = excluded.value,
                    updated_at = excluded.updated_at
                """,
                (cursor.company, cursor.source, cursor.value, cursor.updated_at.isoformat()),
            )

    def get_cursor(self, company: str, source: str) -> IngestionCursor | None:
        """Return one source cursor."""
        with self._connection() as connection:
            row = connection.execute(
                """
                SELECT company, source, value, updated_at
                FROM ingestion_cursors
                WHERE company = ? AND source = ?
                """,
                (company.strip().upper(), source),
            ).fetchone()
        if row is None:
            return None
        return IngestionCursor(
            company=row["company"],
            source=row["source"],
            value=row["value"],
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self._path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
