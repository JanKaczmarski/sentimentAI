"""PostgreSQL persistence for auditable research records."""

from collections.abc import Mapping
from datetime import date, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from sentiment_system.application.ports.repositories import (
    ChunkRepository,
    ChunkScoreRepository,
    DocumentRepository,
    ExperimentProvenanceRepository,
    ExperimentRunRepository,
    InvestmentThesisRepository,
    SnapshotRepository,
    UserAccountRepository,
)
from sentiment_system.domain.accounts import UserAccount
from sentiment_system.domain.documents import DocumentChunk, SourceDocument
from sentiment_system.domain.investment_thesis import (
    InvestmentHorizon,
    InvestmentStyle,
    InvestmentThesis,
    RiskTolerance,
)
from sentiment_system.domain.predictions import (
    CompanySentimentSnapshot,
    ExperimentProvenance,
    ExperimentRun,
    PredictionEvidence,
    SnapshotWindow,
)
from sentiment_system.domain.scoring import ChunkScoreRecord
from sentiment_system.domain.sentiment import SentimentScore


class PostgresDatabase:
    """Open PostgreSQL connections and apply repository-owned migrations."""

    def __init__(self, dsn: str, migrations_dir: Path | None = None) -> None:
        if not dsn.strip():
            raise ValueError("dsn is required")
        self._dsn = dsn
        self._migrations_dir = migrations_dir or Path(__file__).resolve().parent / "migrations"

    def connect(self) -> Any:
        """Return a row-dict connection managed by the caller."""
        return psycopg.connect(self._dsn, row_factory=dict_row)

    def migrate(self) -> None:
        """Apply each unapplied SQL migration exactly once."""
        migration_files = sorted(self._migrations_dir.glob("*.sql"))
        if not migration_files:
            raise ValueError(f"no migrations found in {self._migrations_dir}")

        with self.connect() as connection:
            connection.execute("""
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version text PRIMARY KEY,
                    applied_at timestamptz NOT NULL DEFAULT now()
                )
                """)
            applied = {row["version"] for row in connection.execute("SELECT version FROM schema_migrations")}
            for migration_file in migration_files:
                version = migration_file.name
                if version in applied:
                    continue
                connection.execute(migration_file.read_text(encoding="utf-8"))
                connection.execute("INSERT INTO schema_migrations (version) VALUES (%s)", (version,))


class _PostgresRepository:
    """Shared connection access for concrete PostgreSQL repositories."""

    def __init__(self, database: PostgresDatabase) -> None:
        self._database = database


class PostgresUserAccountRepository(_PostgresRepository, UserAccountRepository):
    """Persist accounts without storing raw API keys."""

    def save(self, account: UserAccount) -> None:
        with self._database.connect() as connection:
            connection.execute(
                """
                INSERT INTO user_accounts (user_id, email, username, api_key_digest)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (user_id) DO UPDATE SET
                    email = EXCLUDED.email,
                    username = EXCLUDED.username,
                    api_key_digest = EXCLUDED.api_key_digest
                """,
                (account.user_id, account.email, account.username, account.api_key_digest),
            )

    def get_by_email(self, email: str) -> UserAccount | None:
        return self._get_one("email", email)

    def get_by_username(self, username: str) -> UserAccount | None:
        return self._get_one("username", username)

    def get_by_api_key_digest(self, api_key_digest: str) -> UserAccount | None:
        return self._get_one("api_key_digest", api_key_digest)

    def _get_one(self, column: str, value: str) -> UserAccount | None:
        with self._database.connect() as connection:
            row = connection.execute(f"SELECT * FROM user_accounts WHERE {column} = %s", (value,)).fetchone()
        return None if row is None else _account_from_row(row)


class PostgresInvestmentThesisRepository(_PostgresRepository, InvestmentThesisRepository):
    """Persist user-owned structured theses and their company assignments."""

    def save(self, thesis: InvestmentThesis) -> None:
        with self._database.connect() as connection:
            connection.execute(
                """
                INSERT INTO investment_theses (
                    thesis_id, user_id, risk_tolerance, investment_horizon, investment_style, description
                ) VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (thesis_id) DO UPDATE SET
                    risk_tolerance = EXCLUDED.risk_tolerance,
                    investment_horizon = EXCLUDED.investment_horizon,
                    investment_style = EXCLUDED.investment_style,
                    description = EXCLUDED.description,
                    updated_at = now()
                """,
                (
                    thesis.thesis_id,
                    thesis.user_id,
                    thesis.risk_tolerance.value,
                    thesis.investment_horizon.value,
                    thesis.investment_style.value,
                    thesis.description,
                ),
            )
            connection.execute("DELETE FROM investment_thesis_companies WHERE thesis_id = %s", (thesis.thesis_id,))
            for ordinal, company in enumerate(thesis.companies):
                connection.execute(
                    """
                    INSERT INTO investment_thesis_companies (thesis_id, ordinal, company)
                    VALUES (%s, %s, %s)
                    """,
                    (thesis.thesis_id, ordinal, company),
                )

    def get(self, thesis_id: str) -> InvestmentThesis | None:
        with self._database.connect() as connection:
            row = connection.execute(
                "SELECT thesis_id::text, user_id::text, risk_tolerance, investment_horizon, investment_style, description "
                "FROM investment_theses WHERE thesis_id = %s",
                (thesis_id,),
            ).fetchone()
            if row is None:
                return None
            company_rows = connection.execute(
                "SELECT company FROM investment_thesis_companies WHERE thesis_id = %s ORDER BY ordinal",
                (thesis_id,),
            ).fetchall()
        return _thesis_from_row(row, company_rows)

    def list_for_user(self, user_id: str) -> tuple[InvestmentThesis, ...]:
        with self._database.connect() as connection:
            rows = connection.execute(
                """
                SELECT thesis_id::text, user_id::text, risk_tolerance, investment_horizon, investment_style, description
                FROM investment_theses WHERE user_id = %s ORDER BY thesis_id
                """,
                (user_id,),
            ).fetchall()
            theses = []
            for row in rows:
                company_rows = connection.execute(
                    "SELECT company FROM investment_thesis_companies WHERE thesis_id = %s ORDER BY ordinal",
                    (row["thesis_id"],),
                ).fetchall()
                theses.append(_thesis_from_row(row, company_rows))
        return tuple(theses)


class PostgresDocumentRepository(_PostgresRepository, DocumentRepository):
    """Persist normalized source documents and their content hashes."""

    def save(self, document: SourceDocument) -> None:
        with self._database.connect() as connection:
            connection.execute(
                """
                INSERT INTO source_documents (
                    document_id, source_id, company, source, published_at,
                    document_type, raw_content, cleaned_content,
                    raw_content_sha256, cleaned_content_sha256
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (document_id) DO UPDATE SET
                    source_id = EXCLUDED.source_id,
                    company = EXCLUDED.company,
                    source = EXCLUDED.source,
                    published_at = EXCLUDED.published_at,
                    document_type = EXCLUDED.document_type,
                    raw_content = EXCLUDED.raw_content,
                    cleaned_content = EXCLUDED.cleaned_content,
                    raw_content_sha256 = EXCLUDED.raw_content_sha256,
                    cleaned_content_sha256 = EXCLUDED.cleaned_content_sha256
                """,
                _document_values(document),
            )

    def get(self, document_id: str) -> SourceDocument | None:
        with self._database.connect() as connection:
            row = connection.execute("SELECT * FROM source_documents WHERE document_id = %s", (document_id,)).fetchone()
        return None if row is None else _document_from_row(row)

    def list_documents(self, *, company: str | None = None) -> tuple[SourceDocument, ...]:
        query = "SELECT * FROM source_documents"
        parameters: tuple[object, ...] = ()
        if company is not None:
            query += " WHERE company = %s"
            parameters = (company,)
        query += " ORDER BY published_at, document_id"
        with self._database.connect() as connection:
            rows = connection.execute(query, parameters).fetchall()
        return tuple(_document_from_row(row) for row in rows)


class PostgresChunkRepository(_PostgresRepository, ChunkRepository):
    """Persist stable document chunks and their processing configuration."""

    def save(self, chunk: DocumentChunk) -> None:
        with self._database.connect() as connection:
            connection.execute(
                """
                INSERT INTO chunks (
                    chunk_id, document_id, ordinal, content, content_sha256,
                    processing_config_version
                ) VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (chunk_id) DO UPDATE SET
                    document_id = EXCLUDED.document_id,
                    ordinal = EXCLUDED.ordinal,
                    content = EXCLUDED.content,
                    content_sha256 = EXCLUDED.content_sha256,
                    processing_config_version = EXCLUDED.processing_config_version
                """,
                (
                    chunk.chunk_id,
                    chunk.document_id,
                    chunk.ordinal,
                    chunk.content,
                    _content_hash(chunk.content),
                    chunk.processing_config_version,
                ),
            )

    def get(self, chunk_id: str) -> DocumentChunk | None:
        with self._database.connect() as connection:
            row = connection.execute("SELECT * FROM chunks WHERE chunk_id = %s", (chunk_id,)).fetchone()
        return None if row is None else _chunk_from_row(row)

    def list_for_document(self, document_id: str) -> tuple[DocumentChunk, ...]:
        with self._database.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM chunks WHERE document_id = %s ORDER BY ordinal, chunk_id", (document_id,)
            ).fetchall()
        return tuple(_chunk_from_row(row) for row in rows)


class PostgresExperimentRunRepository(_PostgresRepository, ExperimentRunRepository):
    """Persist mutable run state while retaining its configuration."""

    def save(self, run: ExperimentRun) -> None:
        with self._database.connect() as connection:
            connection.execute(
                """
                INSERT INTO experiment_runs (
                    run_id, run_type, status, started_at, completed_at, configuration
                ) VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (run_id) DO UPDATE SET
                    run_type = EXCLUDED.run_type,
                    status = EXCLUDED.status,
                    started_at = EXCLUDED.started_at,
                    completed_at = EXCLUDED.completed_at,
                    configuration = EXCLUDED.configuration
                """,
                (
                    run.run_id,
                    run.run_type,
                    run.status,
                    run.started_at,
                    run.completed_at,
                    _jsonb(run.configuration),
                ),
            )

    def get(self, run_id: str) -> ExperimentRun | None:
        with self._database.connect() as connection:
            row = connection.execute("SELECT * FROM experiment_runs WHERE run_id = %s", (run_id,)).fetchone()
        return None if row is None else _run_from_row(row)


class PostgresProvenanceRepository(_PostgresRepository, ExperimentProvenanceRepository):
    """Persist secret-free provider and processing artifacts by run."""

    def save(self, provenance: ExperimentProvenance) -> None:
        with self._database.connect() as connection:
            connection.execute(
                """
                INSERT INTO experiment_provenance (
                    run_id, input_source, input_version, processing_config,
                    model_provider, model_name, prompt, raw_response,
                    parsed_output, thesis_parameters, created_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (run_id) DO NOTHING
                """,
                (
                    provenance.run_id,
                    provenance.input_source,
                    provenance.input_version,
                    _jsonb(provenance.processing_config),
                    provenance.model_provider,
                    provenance.model_name,
                    provenance.prompt,
                    provenance.raw_response,
                    _jsonb(provenance.parsed_output),
                    _jsonb(provenance.thesis_parameters),
                    provenance.created_at,
                ),
            )

    def get(self, run_id: str) -> ExperimentProvenance | None:
        with self._database.connect() as connection:
            row = connection.execute("SELECT * FROM experiment_provenance WHERE run_id = %s", (run_id,)).fetchone()
        return None if row is None else _provenance_from_row(row)


class PostgresChunkScoreRepository(_PostgresRepository, ChunkScoreRepository):
    """Persist chunk scores append-only by chunk and experiment run."""

    def save(self, score: ChunkScoreRecord) -> None:
        with self._database.connect() as connection:
            connection.execute(
                """
                INSERT INTO chunk_scores (
                    chunk_id, run_id, sentiment_score, sentiment_label,
                    importance_score, confidence, excluded, prompt,
                    raw_response, parsed_output, token_usage
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (chunk_id, run_id) DO NOTHING
                """,
                (
                    score.chunk_id,
                    score.run_id,
                    score.sentiment.score,
                    score.sentiment.label.value,
                    score.importance_score,
                    score.sentiment.confidence,
                    score.excluded,
                    score.prompt,
                    score.raw_response,
                    _jsonb(score.parsed_output),
                    _jsonb(score.token_usage),
                ),
            )

    def list_for_chunk(self, chunk_id: str) -> tuple[ChunkScoreRecord, ...]:
        with self._database.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM chunk_scores WHERE chunk_id = %s ORDER BY run_id", (chunk_id,)
            ).fetchall()
        return tuple(_score_from_row(row) for row in rows)


class PostgresSnapshotRepository(_PostgresRepository, SnapshotRepository):
    """Persist append-only company sentiment snapshots and evidence lineage."""

    def save(self, snapshot: CompanySentimentSnapshot) -> None:
        with self._database.connect() as connection:
            connection.execute(
                """
                INSERT INTO company_sentiment_snapshots (
                    company, as_of, window_days, sentiment_score,
                    sentiment_label, confidence, run_id
                ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (company, as_of, window_days, run_id) DO NOTHING
                """,
                (
                    snapshot.company,
                    snapshot.as_of,
                    int(snapshot.window_days),
                    snapshot.sentiment.score,
                    snapshot.sentiment.label.value,
                    snapshot.sentiment.confidence,
                    snapshot.run_id,
                ),
            )
            for rank, evidence in enumerate(snapshot.evidence, start=1):
                connection.execute(
                    """
                    INSERT INTO company_sentiment_snapshot_evidence (
                        company, as_of, window_days, run_id, evidence_rank,
                        chunk_id, published_at, importance_score, excerpt
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT DO NOTHING
                    """,
                    (
                        snapshot.company,
                        snapshot.as_of,
                        int(snapshot.window_days),
                        snapshot.run_id,
                        rank,
                        evidence.chunk_id,
                        evidence.published_at,
                        evidence.importance_score,
                        evidence.excerpt,
                    ),
                )

    def list_for_company(
        self,
        company: str,
        *,
        as_of: date | None = None,
    ) -> tuple[CompanySentimentSnapshot, ...]:
        query = "SELECT * FROM company_sentiment_snapshots WHERE company = %s"
        parameters: tuple[object, ...] = (company,)
        if as_of is not None:
            query += " AND as_of <= %s"
            parameters += (as_of,)
        query += " ORDER BY as_of, window_days, run_id"
        with self._database.connect() as connection:
            rows = connection.execute(query, parameters).fetchall()
            snapshots = []
            for row in rows:
                evidence_rows = connection.execute(
                    """
                    SELECT chunk_id, published_at, importance_score, excerpt
                    FROM company_sentiment_snapshot_evidence
                    WHERE company = %s AND as_of = %s AND window_days = %s AND run_id = %s
                    ORDER BY evidence_rank
                    """,
                    (row["company"], row["as_of"], row["window_days"], row["run_id"]),
                ).fetchall()
                snapshots.append(_snapshot_from_row(row, evidence_rows))
        return tuple(snapshots)


def _document_values(document: SourceDocument) -> tuple[object, ...]:
    return (
        document.document_id,
        document.source_id,
        document.company,
        document.source,
        document.published_at,
        document.document_type,
        document.raw_content,
        document.cleaned_content,
        _content_hash(document.raw_content),
        _content_hash(document.cleaned_content),
    )


def _account_from_row(row: Mapping[str, Any]) -> UserAccount:
    return UserAccount(
        user_id=row["user_id"],
        email=row["email"],
        username=row["username"],
        api_key_digest=row["api_key_digest"],
    )


def _thesis_from_row(row: Mapping[str, Any], company_rows: list[Mapping[str, Any]]) -> InvestmentThesis:
    return InvestmentThesis(
        thesis_id=row["thesis_id"],
        user_id=row["user_id"],
        companies=tuple(company_row["company"] for company_row in company_rows),
        risk_tolerance=RiskTolerance(row["risk_tolerance"]),
        investment_horizon=InvestmentHorizon(row["investment_horizon"]),
        investment_style=InvestmentStyle(row["investment_style"]),
        description=row["description"],
    )


def _content_hash(content: str) -> str:
    return sha256(content.encode("utf-8")).hexdigest()


def _document_from_row(row: Mapping[str, Any]) -> SourceDocument:
    return SourceDocument(
        document_id=row["document_id"],
        source_id=row["source_id"],
        company=row["company"],
        source=row["source"],
        published_at=row["published_at"],
        document_type=row["document_type"],
        raw_content=row["raw_content"],
        cleaned_content=row["cleaned_content"],
    )


def _chunk_from_row(row: Mapping[str, Any]) -> DocumentChunk:
    return DocumentChunk(
        chunk_id=row["chunk_id"],
        document_id=row["document_id"],
        ordinal=row["ordinal"],
        content=row["content"],
        processing_config_version=row["processing_config_version"],
    )


def _run_from_row(row: Mapping[str, Any]) -> ExperimentRun:
    return ExperimentRun(
        run_id=row["run_id"],
        run_type=row["run_type"],
        status=row["status"],
        started_at=row["started_at"],
        completed_at=row["completed_at"],
        configuration=row["configuration"],
    )


def _provenance_from_row(row: Mapping[str, Any]) -> ExperimentProvenance:
    return ExperimentProvenance(
        run_id=row["run_id"],
        input_source=row["input_source"],
        input_version=row["input_version"],
        processing_config=row["processing_config"],
        model_provider=row["model_provider"],
        model_name=row["model_name"],
        prompt=row["prompt"],
        raw_response=row["raw_response"],
        parsed_output=row["parsed_output"],
        thesis_parameters=row["thesis_parameters"],
        created_at=row["created_at"],
    )


def _score_from_row(row: Mapping[str, Any]) -> ChunkScoreRecord:
    return ChunkScoreRecord(
        chunk_id=row["chunk_id"],
        run_id=row["run_id"],
        sentiment=SentimentScore(score=float(row["sentiment_score"]), confidence=float(row["confidence"])),
        importance_score=float(row["importance_score"]),
        excluded=row["excluded"],
        prompt=row["prompt"],
        raw_response=row["raw_response"],
        parsed_output=row["parsed_output"],
        token_usage=row["token_usage"],
    )


def _snapshot_from_row(row: Mapping[str, Any], evidence_rows: list[Mapping[str, Any]]) -> CompanySentimentSnapshot:
    return CompanySentimentSnapshot(
        company=row["company"],
        as_of=row["as_of"],
        window_days=SnapshotWindow(row["window_days"]),
        sentiment=SentimentScore(score=float(row["sentiment_score"]), confidence=float(row["confidence"])),
        evidence=tuple(
            PredictionEvidence(
                chunk_id=evidence["chunk_id"],
                published_at=evidence["published_at"],
                importance_score=float(evidence["importance_score"]),
                excerpt=evidence["excerpt"],
            )
            for evidence in evidence_rows
        ),
        run_id=row["run_id"],
    )


def _jsonb(value: Mapping[str, object]) -> Jsonb:
    return Jsonb(_jsonable(value))


def _jsonable(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_jsonable(item) for item in value]
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value
