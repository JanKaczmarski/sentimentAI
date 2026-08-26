"""End-to-end batch test using deterministic fixtures and fake external ports."""

from datetime import date

from fastapi.testclient import TestClient

from sentiment_system.adapters.outbound.embeddings.mock import DeterministicEmbeddings
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
from sentiment_system.adapters.outbound.sources.fixtures import FixtureDocumentSource
from sentiment_system.adapters.outbound.vector.in_memory import InMemoryVectorStore
from sentiment_system.application.use_cases.aggregate_snapshots import AggregateSnapshots
from sentiment_system.application.use_cases.create_account import CreateAccount
from sentiment_system.application.use_cases.generate_prediction import GeneratePrediction
from sentiment_system.application.use_cases.index_chunks import IndexChunks
from sentiment_system.application.use_cases.ingest_documents import IngestDocuments
from sentiment_system.application.use_cases.manage_investment_theses import ManageInvestmentTheses
from sentiment_system.application.use_cases.run_batch import RunBatch
from sentiment_system.application.use_cases.score_chunks import ScoreChunks
from sentiment_system.bootstrap.container import ApplicationContainer, build_container
from sentiment_system.bootstrap.main import create_app
from sentiment_system.domain.documents import DocumentChunk, SourceDocument


def test_manual_batch_serves_multiple_theses_from_one_scoring_run() -> None:
    accounts = InMemoryUserAccountRepository()
    theses = InMemoryInvestmentThesisRepository()
    documents = InMemoryDocumentRepository()
    chunks = InMemoryChunkRepository()
    score_repository = InMemoryChunkScoreRepository()
    runs = InMemoryExperimentRunRepository()
    provenance = InMemoryProvenanceRepository()
    snapshots = InMemorySnapshotRepository()
    predictions = InMemoryPredictionRepository()
    scorer = CountingScorer()
    batch = _batch(
        scorer=scorer,
        document_repository=documents,
        chunk_repository=chunks,
        score_repository=score_repository,
        runs=runs,
        provenance=provenance,
        snapshots=snapshots,
    )
    api_keys = iter(("key-one", "key-two"))
    app = create_app(
        container=ApplicationContainer(
            account_repository=accounts,
            create_account=CreateAccount(accounts, api_key_factory=lambda: next(api_keys)),
            investment_thesis_repository=theses,
            manage_investment_theses=ManageInvestmentTheses(accounts, theses),
            snapshot_repository=snapshots,
            prediction_repository=predictions,
            generate_prediction=GeneratePrediction(accounts, theses, snapshots, predictions),
            run_batch=batch,
        )
    )
    client = TestClient(app)

    first_account = client.post("/user/account", json={"email": "one@example.com", "username": "one"}).json()
    second_account = client.post("/user/account", json={"email": "two@example.com", "username": "two"}).json()
    first_thesis = client.post(
        "/user/strategy",
        params={"api_key": first_account["api_key"]},
        json=_thesis_payload("long_term", "passive"),
    )
    second_thesis = client.post(
        "/user/strategy",
        params={"api_key": second_account["api_key"]},
        json=_thesis_payload("short_term", "active"),
    )
    batch_response = client.post(
        "/batch/run",
        json={"company": "AAPL", "as_of": "2025-01-02"},
    )
    first_prediction = client.get(
        "/companies/AAPL/prediction",
        params={"api_key": first_account["api_key"], "as_of": "2025-01-02", "forecast_horizon_days": 20},
    )
    second_prediction = client.get(
        "/companies/AAPL/prediction",
        params={"api_key": second_account["api_key"], "as_of": "2025-01-02", "forecast_horizon_days": 20},
    )

    assert first_thesis.status_code == 201
    assert second_thesis.status_code == 201
    assert batch_response.status_code == 200
    assert batch_response.json()["status"] == "completed"
    assert batch_response.json()["document_count"] == 1
    assert batch_response.json()["snapshot_count"] == 3
    assert first_prediction.status_code == 200
    assert second_prediction.status_code == 200
    assert first_prediction.json()["run_id"] == batch_response.json()["run_id"]
    assert second_prediction.json()["run_id"] == batch_response.json()["run_id"]
    assert scorer.calls == 1


def test_default_container_runs_the_small_development_poc(monkeypatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("QDRANT_URL", raising=False)
    monkeypatch.delenv("SENTIMENT_DATA_ROOT", raising=False)
    monkeypatch.setenv("EMBEDDING_BACKEND", "mock")

    container = build_container()
    assert container.run_batch is not None

    result = container.run_batch.execute(as_of=date(2025, 1, 16), company="AAPL")

    assert result.status == "completed"
    assert result.document_count == 1
    assert result.snapshot_count == 3


def _batch(*, scorer, document_repository, chunk_repository, score_repository, runs, provenance, snapshots) -> RunBatch:
    ingestion = IngestDocuments(
        FixtureDocumentSource((_document(),)),
        document_repository,
        chunk_repository,
        processing_config_version="processing-v1",
        token_counter=lambda value: len(value.split()),
    )
    return RunBatch(
        ingestion,
        IndexChunks(document_repository, DeterministicEmbeddings(), InMemoryVectorStore()),
        ScoreChunks(scorer, score_repository, provenance, runs),
        AggregateSnapshots(document_repository, chunk_repository, score_repository, snapshots),
        runs,
    )


def _document() -> SourceDocument:
    return SourceDocument(
        document_id="poc-document",
        source_id="poc-source",
        company="AAPL",
        source="fixture",
        published_at=date(2025, 1, 1),
        document_type="company_communication",
        raw_content="Revenue increased. Costs declined.",
        cleaned_content="Revenue increased. Costs declined.",
    )


def _thesis_payload(horizon: str, style: str) -> dict[str, object]:
    return {
        "companies": ["AAPL"],
        "risk_tolerance": "medium",
        "investment_horizon": horizon,
        "investment_style": style,
    }


class CountingScorer(DeterministicLLMScorer):
    """Count scoring calls while retaining deterministic results."""

    def __init__(self) -> None:
        super().__init__()
        self.calls = 0

    def score_chunk(self, chunk: DocumentChunk, *, context: str = ""):
        self.calls += 1
        return super().score_chunk(chunk, context=context)
