"""Integration coverage for the PostgreSQL research-record adapter."""

import os
from datetime import date, datetime, timezone
from hashlib import sha256
from uuid import uuid4

import pytest

from sentiment_system.adapters.outbound.persistence.postgres import (
    PostgresChunkRepository,
    PostgresChunkScoreRepository,
    PostgresDatabase,
    PostgresDocumentRepository,
    PostgresExperimentRunRepository,
    PostgresInvestmentThesisRepository,
    PostgresProvenanceRepository,
    PostgresSnapshotRepository,
    PostgresUserAccountRepository,
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


@pytest.mark.integration
def test_postgres_migrates_and_preserves_auditable_research_history() -> None:
    dsn = os.getenv("POSTGRES_TEST_DSN")
    if not dsn:
        pytest.skip("POSTGRES_TEST_DSN is not configured")

    database = PostgresDatabase(dsn)
    database.migrate()
    database.migrate()

    suffix = uuid4().hex
    document = SourceDocument(
        document_id=f"document-{suffix}",
        source_id=f"source-{suffix}",
        company="AAPL",
        source="fixture",
        published_at=date(2025, 1, 30),
        document_type="company_communication",
        raw_content="Raw source text.",
        cleaned_content="Cleaned source text.",
    )
    chunk = DocumentChunk(
        chunk_id=f"chunk-{suffix}",
        document_id=document.document_id,
        ordinal=0,
        content="Cleaned source text.",
        processing_config_version="processing-v1",
    )
    first_run = ExperimentRun(
        run_id=f"run-1-{suffix}",
        run_type="scoring",
        status="completed",
        started_at=datetime(2025, 2, 1, tzinfo=timezone.utc),
        completed_at=datetime(2025, 2, 1, 0, 1, tzinfo=timezone.utc),
        configuration={"variant": "standard"},
    )
    second_run = ExperimentRun(
        run_id=f"run-2-{suffix}",
        run_type="scoring",
        status="completed",
        started_at=datetime(2025, 2, 2, tzinfo=timezone.utc),
        completed_at=datetime(2025, 2, 2, 0, 1, tzinfo=timezone.utc),
        configuration={"variant": "contextual"},
    )
    provenance = ExperimentProvenance(
        run_id=first_run.run_id,
        input_source="fixtures",
        input_version="v1",
        processing_config={"chunking": "fixed"},
        model_provider="test-provider",
        model_name="test-model",
        prompt="Score the chunk.",
        raw_response='{"score": 0.7}',
        parsed_output={"score": 0.7},
        thesis_parameters={},
        created_at=datetime(2025, 2, 1, tzinfo=timezone.utc),
    )
    score = ChunkScoreRecord(
        chunk_id=chunk.chunk_id,
        run_id=first_run.run_id,
        sentiment=SentimentScore(score=0.7, confidence=0.8),
        importance_score=0.9,
        excluded=False,
        prompt="Score the chunk.",
        raw_response='{"score": 0.7}',
        parsed_output={"score": 0.7},
        token_usage={"prompt_tokens": 12, "completion_tokens": 3},
    )
    historical_score = ChunkScoreRecord(
        chunk_id=chunk.chunk_id,
        run_id=second_run.run_id,
        sentiment=SentimentScore(score=0.2, confidence=0.6),
        importance_score=0.5,
        excluded=False,
        prompt="Score the chunk.",
        raw_response='{"score": 0.2}',
        parsed_output={"score": 0.2},
        token_usage={},
    )
    snapshot = CompanySentimentSnapshot(
        company="AAPL",
        as_of=date(2025, 2, 1),
        window_days=SnapshotWindow.NINETY_DAYS,
        sentiment=SentimentScore(score=0.7, confidence=0.8),
        evidence=(
            PredictionEvidence(
                chunk_id=chunk.chunk_id,
                published_at=document.published_at,
                importance_score=0.9,
                excerpt="Cleaned source text.",
            ),
        ),
        run_id=first_run.run_id,
    )
    account = UserAccount(
        user_id=uuid4(),
        email=f"investor-{suffix}@example.com",
        username=f"investor-{suffix}",
        api_key_digest=sha256(f"api-key-{suffix}".encode("utf-8")).hexdigest(),
    )
    thesis = InvestmentThesis(
        thesis_id=str(uuid4()),
        user_id=str(account.user_id),
        companies=("AAPL", "MSFT"),
        risk_tolerance=RiskTolerance.MEDIUM,
        investment_horizon=InvestmentHorizon.LONG_TERM,
        investment_style=InvestmentStyle.PASSIVE,
        description="Stored without interpretation.",
    )

    documents = PostgresDocumentRepository(database)
    chunks = PostgresChunkRepository(database)
    runs = PostgresExperimentRunRepository(database)
    provenance_repository = PostgresProvenanceRepository(database)
    scores = PostgresChunkScoreRepository(database)
    snapshots = PostgresSnapshotRepository(database)
    accounts = PostgresUserAccountRepository(database)
    theses = PostgresInvestmentThesisRepository(database)

    documents.save(document)
    chunks.save(chunk)
    runs.save(first_run)
    runs.save(second_run)
    provenance_repository.save(provenance)
    scores.save(score)
    scores.save(historical_score)
    snapshots.save(snapshot)
    accounts.save(account)
    theses.save(thesis)

    assert documents.get(document.document_id) == document
    assert chunks.list_for_document(document.document_id) == (chunk,)
    assert runs.get(first_run.run_id) == first_run
    assert provenance_repository.get(first_run.run_id) == provenance
    assert scores.list_for_chunk(chunk.chunk_id) == (score, historical_score)
    assert snapshot in snapshots.list_for_company("AAPL")
    assert accounts.get_by_email(account.email) == account
    assert accounts.get_by_username(account.username) == account
    assert accounts.get_by_api_key_digest(account.api_key_digest) == account
    assert theses.get(thesis.thesis_id) == thesis
    assert theses.list_for_user(str(account.user_id)) == (thesis,)
