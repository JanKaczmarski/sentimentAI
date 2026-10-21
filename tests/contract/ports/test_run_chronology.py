"""Shared chronology contracts exercised against memory and real PostgreSQL."""

import os
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
from uuid import uuid4

import pytest

from sentiment_system.adapters.outbound.llm.mock import DeterministicLLMScorer
from sentiment_system.adapters.outbound.persistence.in_memory import (
    InMemoryChunkRepository,
    InMemoryChunkScoreRepository,
    InMemoryDocumentRepository,
    InMemoryExperimentRunRepository,
    InMemoryInvestmentThesisRepository,
    InMemoryPredictionRepository,
    InMemoryProvenanceRepository,
    InMemorySnapshotRepository,
    InMemoryUserAccountRepository,
)
from sentiment_system.adapters.outbound.persistence.postgres import (
    PostgresChunkRepository,
    PostgresChunkScoreRepository,
    PostgresDatabase,
    PostgresDocumentRepository,
    PostgresExperimentRunRepository,
    PostgresInvestmentThesisRepository,
    PostgresPredictionRepository,
    PostgresProvenanceRepository,
    PostgresSnapshotRepository,
    PostgresUserAccountRepository,
)
from sentiment_system.application.ports.llm import ChunkScoringResult
from sentiment_system.application.use_cases.generate_prediction import GeneratePrediction, PredictionUnavailableError
from sentiment_system.application.use_cases.score_chunks import ScoreChunks
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
    ExperimentRun,
    PredictionEvidence,
    SnapshotWindow,
)
from sentiment_system.domain.sentiment import SentimentScore


@pytest.fixture(params=["memory", pytest.param("postgres", marks=pytest.mark.integration)])
def repositories(request):
    if request.param == "memory":
        runs = InMemoryExperimentRunRepository()
        return (
            InMemoryDocumentRepository(),
            InMemoryChunkRepository(),
            runs,
            InMemoryChunkScoreRepository(runs=runs),
            InMemoryProvenanceRepository(),
            InMemorySnapshotRepository(),
            InMemoryUserAccountRepository(),
            InMemoryInvestmentThesisRepository(),
            InMemoryPredictionRepository(),
        )
    dsn = os.getenv("POSTGRES_TEST_DSN")
    if not dsn:
        pytest.skip("POSTGRES_TEST_DSN is not configured")
    database = PostgresDatabase(dsn)
    database.migrate()
    return tuple(
        repository(database)
        for repository in (
            PostgresDocumentRepository,
            PostgresChunkRepository,
            PostgresExperimentRunRepository,
            PostgresChunkScoreRepository,
            PostgresProvenanceRepository,
            PostgresSnapshotRepository,
            PostgresUserAccountRepository,
            PostgresInvestmentThesisRepository,
            PostgresPredictionRepository,
        )
    )


def _document_and_chunk(documents, chunks):
    suffix = uuid4().hex
    document = SourceDocument(
        document_id=f"document-{suffix}",
        source_id=f"source-{suffix}",
        company="AAPL",
        source="fixture",
        published_at=date(2025, 1, 1),
        document_type="company_communication",
        raw_content="Revenue increased.",
        cleaned_content="Revenue increased.",
    )
    documents.save(document)
    chunk = DocumentChunk(
        chunk_id=f"chunk-{suffix}", document_id=document.document_id, ordinal=0, content=document.cleaned_content
    )
    chunks.save(chunk)
    return document, chunk


@pytest.mark.parametrize(
    ("importance", "expected"),
    [
        ((0.01, 0.01, 0.9, 0.01), False),
        ((0.9, 0.01, 0.01, 0.01), True),
        ((0.01, 0.01, 0.01, 0.05), False),
    ],
)
def test_scores_are_chronological_and_history_is_preserved(repositories, importance, expected):
    documents, chunks, runs, scores, provenance, *_ = repositories
    document, chunk = _document_and_chunk(documents, chunks)
    suffix = uuid4().hex
    run_ids = tuple(f"run-{letter}-{suffix}" for letter in ("x", "y", "a", "z"))
    history = []
    for hour, (run_id, value) in enumerate(zip(run_ids, importance)):
        ScoreChunks(
            DeterministicLLMScorer(
                {
                    chunk.chunk_id: ChunkScoringResult(
                        sentiment=SentimentScore(score=0.7, confidence=0.8),
                        importance_score=value,
                        raw_response='{"score": 0.7}',
                        parsed_output={"score": 0.7, "importance_score": value},
                    )
                }
            ),
            scores,
            provenance,
            runs,
            now=lambda hour=hour: datetime(2026, 8, 26, hour, tzinfo=timezone.utc),
        ).execute((chunk,), run_id=run_id, prompt="Score.")
        assert scores.list_for_chunk(chunk.chunk_id)[:-1] == tuple(history)
        history = list(scores.list_for_chunk(chunk.chunk_id))
    assert tuple(score.run_id for score in history) == run_ids
    assert history[-1].excluded is expected
    scores.save(replace(history[0], importance_score=0.99, raw_response="Changed response"))
    assert scores.list_for_chunk(chunk.chunk_id) == tuple(history)
    assert documents.get(document.document_id) == document
    assert chunks.get(chunk.chunk_id) == chunk
    assert all(provenance.get(run_id) is not None for run_id in run_ids)


@pytest.mark.parametrize("latest_status", ["failed", "started", "completed"])
def test_prediction_uses_latest_start_and_preserves_history_when_unavailable(repositories, latest_status):
    documents, chunks, runs, _, _, snapshots, accounts, theses, predictions = repositories
    document, chunk = _document_and_chunk(documents, chunks)
    suffix = uuid4().hex
    # Reserve an unused date so repeated runs on a shared test database stay isolated.
    used_dates = {run.configuration.get("as_of") for run in runs.list_runs()}
    as_of = date(2040, 1, 1)
    while as_of.isoformat() in used_dates:
        as_of += timedelta(days=1)
    account = UserAccount(
        user_id=uuid4(),
        email=f"{suffix}@example.com",
        username=suffix,
        api_key_digest=sha256(suffix.encode()).hexdigest(),
    )
    accounts.save(account)
    theses.save(
        InvestmentThesis(
            thesis_id=str(uuid4()),
            user_id=str(account.user_id),
            companies=("AAPL",),
            risk_tolerance=RiskTolerance.MEDIUM,
            investment_horizon=InvestmentHorizon.LONG_TERM,
            investment_style=InvestmentStyle.PASSIVE,
        )
    )
    started_at = datetime(2026, 8, 26, tzinfo=timezone.utc)
    older = ExperimentRun(
        run_id=f"run-z-{suffix}",
        run_type="batch",
        status="completed",
        started_at=started_at,
        completed_at=started_at + timedelta(hours=4),
        configuration={"as_of": as_of.isoformat(), "company": "AAPL"},
    )
    newer = replace(
        older,
        run_id=f"run-a-{suffix}",
        started_at=started_at + timedelta(hours=1),
        completed_at=started_at + timedelta(hours=2),
    )
    # Save in reverse execution order to catch reliance on insertion order.
    for run in (newer, older):
        runs.save(run)
        for window in (SnapshotWindow.NINETY_DAYS, SnapshotWindow.YEAR):
            snapshots.save(
                CompanySentimentSnapshot(
                    company="AAPL",
                    as_of=as_of,
                    window_days=window,
                    sentiment=SentimentScore(0.7, 0.8),
                    run_id=run.run_id,
                    evidence=(
                        PredictionEvidence(
                            chunk_id=chunk.chunk_id,
                            published_at=document.published_at,
                            sentiment=SentimentScore(0.7, 0.8),
                            importance_score=0.9,
                            excerpt=chunk.content,
                        ),
                    ),
                )
            )
    selected_runs = [run for run in runs.list_runs() if run.run_id in {older.run_id, newer.run_id}]
    assert selected_runs == [older, newer]
    use_case = GeneratePrediction(accounts, theses, snapshots, predictions, runs)
    result = use_case.execute(api_key=suffix, company="AAPL", as_of=as_of, forecast_horizon_days=20)
    assert result.run_id == newer.run_id
    original_snapshots = snapshots.list_for_company("AAPL")
    original_predictions = predictions.list_for_user(str(account.user_id))
    failed = replace(
        newer,
        run_id=f"run-failed-{suffix}",
        status=latest_status,
        started_at=started_at + timedelta(hours=3),
        completed_at=started_at + timedelta(hours=4),
    )
    runs.save(failed)
    with pytest.raises(PredictionUnavailableError):
        use_case.execute(api_key=suffix, company="AAPL", as_of=as_of, forecast_horizon_days=20)
    assert snapshots.list_for_company("AAPL") == original_snapshots
    assert predictions.list_for_user(str(account.user_id)) == original_predictions


@pytest.mark.parametrize(
    ("status", "run_type"), [("failed", "scoring"), ("started", "scoring"), ("completed", "evaluation")]
)
def test_only_completed_prior_scoring_runs_count_toward_exclusion(repositories, status, run_type):
    documents, chunks, runs, scores, provenance, *_ = repositories
    _, chunk = _document_and_chunk(documents, chunks)
    suffix = uuid4().hex
    scorer = DeterministicLLMScorer(
        {
            chunk.chunk_id: ChunkScoringResult(
                sentiment=SentimentScore(0.7, 0.8),
                importance_score=0.01,
                raw_response='{"importance_score": 0.01}',
                parsed_output={"importance_score": 0.01},
            )
        }
    )
    for hour in range(3):
        run_id = f"run-{hour}-{suffix}"
        ScoreChunks(
            scorer,
            scores,
            provenance,
            runs,
            now=lambda hour=hour: datetime(2026, 8, 26, hour, tzinfo=timezone.utc),
        ).execute((chunk,), run_id=run_id, prompt="Score.")
        if hour == 1:
            runs.save(replace(runs.get(run_id), status=status, run_type=run_type))
    assert len(scores.list_for_chunk(chunk.chunk_id)) == 3
    assert scores.list_for_chunk(chunk.chunk_id)[-1].excluded is False


def test_equal_start_times_use_stable_run_id_ties(repositories):
    documents, chunks, runs, scores, provenance, *_ = repositories
    _, chunk = _document_and_chunk(documents, chunks)
    suffix = uuid4().hex
    now = datetime(2026, 8, 26, tzinfo=timezone.utc)
    ids = [f"run-{letter}-{suffix}" for letter in ("z", "a")]
    for run_id in ids:
        ScoreChunks(DeterministicLLMScorer(), scores, provenance, runs, now=lambda: now).execute(
            (chunk,),
            run_id=run_id,
            prompt="Score.",
        )
    assert [score.run_id for score in scores.list_for_chunk(chunk.chunk_id)] == sorted(ids)
