"""Integration coverage for the PostgreSQL research-record adapter."""

import os
from dataclasses import replace
from datetime import date, datetime, timezone
from hashlib import sha256
from uuid import uuid4

import pytest

from sentiment_system.adapters.outbound.persistence.postgres import (
    PostgresChunkRepository,
    PostgresChunkScoreRepository,
    PostgresDatabase,
    PostgresDocumentRepository,
    PostgresEvaluationReportRepository,
    PostgresExperimentRunRepository,
    PostgresInvestmentThesisRepository,
    PostgresPredictionRepository,
    PostgresProvenanceRepository,
    PostgresSnapshotRepository,
    PostgresUserAccountRepository,
)
from sentiment_system.domain.accounts import UserAccount
from sentiment_system.domain.documents import DocumentChunk, SourceDocument, SourceProvenance
from sentiment_system.domain.evaluation import (
    EvaluationMetric,
    EvaluationObservation,
    EvaluationReport,
    EvaluationVariant,
)
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
    Prediction,
    PredictionEvidence,
    SnapshotWindow,
)
from sentiment_system.domain.research import FINAL_CORPUS_VERSION
from sentiment_system.domain.scoring import ChunkScoreRecord
from sentiment_system.domain.sentiment import PersonalizedSentiment, SentimentScore


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
        manifest_version="fixture-v1",
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
                sentiment=score.sentiment,
                importance_score=0.9,
                excerpt="Cleaned source text.",
            ),
            PredictionEvidence(
                chunk_id=f"{chunk.chunk_id}-older",
                published_at=date(2025, 1, 1),
                sentiment=historical_score.sentiment,
                importance_score=0.5,
                excerpt="Older source text.",
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
    predictions = PostgresPredictionRepository(database)
    evaluation_reports = PostgresEvaluationReportRepository(database)

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
    prediction = Prediction(
        company="AAPL",
        as_of=date(2025, 2, 1),
        lookback_days=SnapshotWindow.NINETY_DAYS,
        forecast_horizon_days=20,
        base_sentiment=SentimentScore(score=0.6, confidence=0.7),
        personalized_sentiment=PersonalizedSentiment(
            score=0.65,
            confidence=0.75,
            label=SentimentScore(score=0.65, confidence=0.75).label,
        ),
        confidence=0.75,
        evidence=(
            PredictionEvidence(
                chunk_id=chunk.chunk_id,
                published_at=document.published_at,
                sentiment=score.sentiment,
                importance_score=0.9,
                excerpt=chunk.content,
            ),
            PredictionEvidence(
                chunk_id=f"{chunk.chunk_id}-older",
                published_at=date(2025, 1, 1),
                sentiment=historical_score.sentiment,
                importance_score=0.5,
                excerpt="Older source text.",
            ),
        ),
        run_id=first_run.run_id,
        user_id=str(account.user_id),
    )
    predictions.save(prediction)
    report = EvaluationReport(
        report_id=f"evaluation-{suffix}",
        created_at=datetime(2025, 2, 2, tzinfo=timezone.utc),
        corpus_manifest_version="fixture-corpus-v1",
        market_snapshot_version="fixture-prices-v1",
        observations=(
            EvaluationObservation(
                company="AAPL",
                prediction_as_of=date(2025, 2, 1),
                entry_date=date(2025, 2, 3),
                exit_date=date(2025, 2, 4),
                forecast_horizon_days=1,
                variant=EvaluationVariant.BASE,
                benchmark_mode="sector",
                benchmark_symbol="XLK",
                used_spy_fallback=False,
                predicted_score=0.7,
                subject_return=0.1,
                benchmark_return=0.05,
                excess_return=0.05,
            ),
        ),
        exclusions=(),
        metrics=(
            EvaluationMetric(
                variant=EvaluationVariant.BASE,
                benchmark_mode="sector",
                forecast_horizon_days=1,
                observation_count=1,
                directional_sample_size=1,
                directional_hit_rate=1.0,
                spearman_correlation=None,
            ),
        ),
    )
    evaluation_reports.save(report)

    assert documents.get(document.document_id) == document
    assert chunks.list_for_document(document.document_id) == (chunk,)
    assert runs.get(first_run.run_id) == first_run
    assert provenance_repository.get(first_run.run_id) == provenance
    assert scores.list_for_chunk(chunk.chunk_id) == (score, historical_score)
    stored_snapshot = next(item for item in snapshots.list_for_company("AAPL") if item.run_id == first_run.run_id)
    assert stored_snapshot == snapshot
    assert [item.chunk_id for item in stored_snapshot.evidence] == [chunk.chunk_id, f"{chunk.chunk_id}-older"]
    assert accounts.get_by_email(account.email) == account
    assert accounts.get_by_username(account.username) == account
    assert accounts.get_by_api_key_digest(account.api_key_digest) == account
    assert theses.get(thesis.thesis_id) == thesis
    assert theses.list_for_user(str(account.user_id)) == (thesis,)
    stored_prediction = predictions.list_for_user(str(account.user_id))[0]
    assert stored_prediction == prediction
    assert [item.chunk_id for item in stored_prediction.evidence] == [chunk.chunk_id, f"{chunk.chunk_id}-older"]
    assert evaluation_reports.get(report.report_id) == report


@pytest.mark.integration
def test_postgres_preserves_manifest_provenance_and_source_revisions() -> None:
    dsn = os.getenv("POSTGRES_TEST_DSN")
    if not dsn:
        pytest.skip("POSTGRES_TEST_DSN is not configured")

    database = PostgresDatabase(dsn)
    database.migrate()
    repository = PostgresDocumentRepository(database)
    suffix = uuid4().hex

    def document(*, revision: str, raw_content: str, raw_sha256: str) -> SourceDocument:
        return SourceDocument(
            document_id=f"sec:{suffix}:{revision}",
            source_id=f"accession-{suffix}",
            company="AAPL",
            source="sec",
            published_at=date(2025, 1, 30),
            document_type="earnings_release",
            raw_content=raw_content,
            cleaned_content=raw_content,
            manifest_version="thesis-v1-2025-09-24",
            provenance=SourceProvenance(
                manifest_record_id=f"sec:{suffix}:{revision}",
                source_url="https://www.sec.gov/Archives/edgar/data/320193/example.txt",
                retrieved_at=datetime(2025, 1, 31, tzinfo=timezone.utc),
                raw_path=f"raw/sec/AAPL/{revision}.txt",
                raw_sha256=raw_sha256,
                cleaned_path=f"cleaned/sec/AAPL/{revision}.txt",
                cleaned_sha256=raw_sha256,
                parser_version="source-cleaning-v1",
                source_type="sec_filing",
                form="8-K",
                form_items=("2.02",),
                content_group_id=f"AAPL:{suffix}",
                canonical_for_scoring=True,
                evaluation_member=True,
                sector="Information Technology",
                sector_source_url="https://www.nasdaq.com/market-activity/stocks/aapl",
                sector_retrieved_at=datetime(2025, 1, 31, tzinfo=timezone.utc),
            ),
        )

    original = document(revision="original", raw_content="Original release.", raw_sha256="a" * 64)
    revised = document(revision="revised", raw_content="Original release.", raw_sha256="b" * 64)
    repository.save(original)
    repository.save(original)
    repository.save(revised)

    stored = tuple(
        document for document in repository.list_documents(company="AAPL") if document.source_id == original.source_id
    )

    assert stored == (original, revised)

    # Identical original bytes may have multiple immutable cleaning versions.
    assert original.provenance is not None
    recleaned = replace(
        original,
        document_id=f"{FINAL_CORPUS_VERSION}:{original.document_id}",
        cleaned_content="Reviewed release and complete financial supplement.",
        manifest_version=FINAL_CORPUS_VERSION,
        provenance=replace(
            original.provenance,
            parser_version="sec-form-aware-v2",
            cleaned_sha256=sha256(b"Reviewed release and complete financial supplement.").hexdigest(),
        ),
    )
    repository.save(recleaned)
    repository.save(recleaned)
    chunks = PostgresChunkRepository(database)
    for item in (original, recleaned):
        chunks.save(
            DocumentChunk(
                chunk_id=f"{item.document_id}:chunk:0",
                document_id=item.document_id,
                ordinal=0,
                content=item.cleaned_content,
                processing_config_version="processing-v1",
            )
        )
    assert repository.get(original.document_id) == original
    assert repository.get(recleaned.document_id) == recleaned
    assert chunks.list_for_document(original.document_id)[0].content == original.cleaned_content
    assert chunks.list_for_document(recleaned.document_id)[0].content == recleaned.cleaned_content
