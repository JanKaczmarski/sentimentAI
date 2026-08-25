"""Contract tests for fake port implementations."""

from datetime import date, datetime, timezone
from hashlib import sha256
from uuid import UUID

import pytest

from sentiment_system.adapters.outbound.embeddings.mock import DeterministicEmbeddings
from sentiment_system.adapters.outbound.llm.mock import DeterministicLLMScorer
from sentiment_system.adapters.outbound.market_data.fake import InMemoryMarketData
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
from sentiment_system.application.ports.document_sources import DocumentSource
from sentiment_system.application.ports.embeddings import EmbeddingProvider
from sentiment_system.application.ports.llm import LLMScorer
from sentiment_system.application.ports.market_data import MarketData, PricePoint
from sentiment_system.application.ports.repositories import (
    ChunkRepository,
    ChunkScoreRepository,
    DocumentRepository,
    ExperimentProvenanceRepository,
    ExperimentRunRepository,
    InvestmentThesisRepository,
    PredictionRepository,
    SnapshotRepository,
    UserAccountRepository,
)
from sentiment_system.application.ports.vector_store import EmbeddedChunk, VectorQuery, VectorStore
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
    Prediction,
    SnapshotWindow,
)
from sentiment_system.domain.scoring import ChunkScoreRecord
from sentiment_system.domain.sentiment import SentimentScore


def _document(
    document_id: str = "document-1", company: str = "AAPL", published_at: date = date(2025, 1, 30)
) -> SourceDocument:
    return SourceDocument(
        document_id=document_id,
        source_id=f"source-{document_id}",
        company=company,
        source="fixture",
        published_at=published_at,
        document_type="company_communication",
        raw_content=f"Raw content for {document_id}.",
        cleaned_content=f"Cleaned content for {document_id}.",
    )


def _chunk(document_id: str = "document-1", chunk_id: str = "chunk-1", ordinal: int = 0) -> DocumentChunk:
    return DocumentChunk(
        chunk_id=chunk_id,
        document_id=document_id,
        ordinal=ordinal,
        content=f"Content for {chunk_id}.",
    )


def _snapshot(company: str = "AAPL", as_of: date = date(2025, 2, 1)) -> CompanySentimentSnapshot:
    return CompanySentimentSnapshot(
        company=company,
        as_of=as_of,
        window_days=SnapshotWindow.NINETY_DAYS,
        sentiment=SentimentScore(score=0.7, confidence=0.8),
        evidence=(),
        run_id=f"run-{company}-{as_of.isoformat()}",
    )


def _prediction(company: str = "AAPL", as_of: date = date(2025, 2, 1)) -> Prediction:
    sentiment = SentimentScore(score=0.7, confidence=0.8)
    return Prediction(
        company=company,
        as_of=as_of,
        lookback_days=SnapshotWindow.NINETY_DAYS,
        forecast_horizon_days=20,
        base_sentiment=sentiment,
        personalized_sentiment=sentiment,
        confidence=0.8,
        evidence=(),
        run_id=f"run-{company}-{as_of.isoformat()}",
    )


def _thesis(thesis_id: str = "thesis-1", user_id: str = "user-1") -> InvestmentThesis:
    return InvestmentThesis(
        thesis_id=thesis_id,
        user_id=user_id,
        companies=("AAPL",),
        risk_tolerance=RiskTolerance.MEDIUM,
        investment_horizon=InvestmentHorizon.LONG_TERM,
        investment_style=InvestmentStyle.PASSIVE,
    )


def _provenance(run_id: str = "run-1") -> ExperimentProvenance:
    return ExperimentProvenance(
        run_id=run_id,
        input_source="fixtures",
        input_version="v1",
        processing_config={"chunking": "fixed"},
        model_provider="fake",
        model_name="deterministic",
        prompt="Score the chunk.",
        raw_response='{"score": 0.7}',
        parsed_output={"score": 0.7},
        thesis_parameters={},
        created_at=datetime(2025, 2, 1, tzinfo=timezone.utc),
    )


def _run(run_id: str = "run-1") -> ExperimentRun:
    return ExperimentRun(
        run_id=run_id,
        run_type="scoring",
        status="completed",
        started_at=datetime(2025, 2, 1, tzinfo=timezone.utc),
        completed_at=datetime(2025, 2, 1, 0, 1, tzinfo=timezone.utc),
        configuration={"variant": "standard"},
    )


def _score(chunk_id: str = "chunk-1", run_id: str = "run-1") -> ChunkScoreRecord:
    return ChunkScoreRecord(
        chunk_id=chunk_id,
        run_id=run_id,
        sentiment=SentimentScore(score=0.7, confidence=0.8),
        importance_score=0.9,
        excluded=False,
        prompt="Score this chunk.",
        raw_response='{"score": 0.7}',
        parsed_output={"score": 0.7},
        token_usage={"prompt_tokens": 12, "completion_tokens": 3},
    )


def _account(
    user_id: UUID = UUID("a66b7cd0-e219-4e17-8729-4c49b0a65624"),
    email: str = "investor@example.com",
    username: str = "investor",
    api_key: str = "api-key",
) -> UserAccount:
    return UserAccount(
        user_id=user_id,
        email=email,
        username=username,
        api_key_digest=sha256(api_key.encode("utf-8")).hexdigest(),
    )


def test_port_fakes_are_structurally_typed() -> None:
    assert isinstance(FixtureDocumentSource(), DocumentSource)
    assert isinstance(InMemoryDocumentRepository(), DocumentRepository)
    assert isinstance(InMemoryChunkRepository(), ChunkRepository)
    assert isinstance(InMemoryChunkScoreRepository(), ChunkScoreRepository)
    assert isinstance(InMemoryInvestmentThesisRepository(), InvestmentThesisRepository)
    assert isinstance(InMemorySnapshotRepository(), SnapshotRepository)
    assert isinstance(InMemoryPredictionRepository(), PredictionRepository)
    assert isinstance(InMemoryProvenanceRepository(), ExperimentProvenanceRepository)
    assert isinstance(InMemoryExperimentRunRepository(), ExperimentRunRepository)
    assert isinstance(InMemoryUserAccountRepository(), UserAccountRepository)
    assert isinstance(DeterministicLLMScorer(), LLMScorer)
    assert isinstance(DeterministicEmbeddings(), EmbeddingProvider)
    assert isinstance(InMemoryVectorStore(), VectorStore)
    assert isinstance(InMemoryMarketData(), MarketData)


def test_fixture_source_filters_and_sorts_documents() -> None:
    source = FixtureDocumentSource(
        (
            _document("document-2", published_at=date(2025, 2, 1)),
            _document("document-1", published_at=date(2025, 1, 1)),
            _document("document-3", company="MSFT", published_at=date(2025, 1, 15)),
        )
    )

    documents = source.fetch_documents(company="AAPL", published_after=date(2025, 1, 1))

    assert [document.document_id for document in documents] == ["document-2"]


def test_fixture_source_normalizes_mapping_payloads_and_rejects_missing_fields() -> None:
    source = FixtureDocumentSource(
        (
            {
                "document_id": "document-1",
                "source_id": "source-1",
                "company": "AAPL",
                "source": "fixture",
                "published_at": "2025-01-30",
                "document_type": "company_communication",
                "raw_content": "Fixture content.",
            },
        )
    )

    assert source.fetch_documents()[0].raw_content == "Fixture content."

    with pytest.raises(ValueError, match="source_id is required"):
        FixtureDocumentSource(({"document_id": "document-1"},))


def test_repositories_round_trip_domain_values_deterministically() -> None:
    document_repository = InMemoryDocumentRepository([_document()])
    chunk_repository = InMemoryChunkRepository([_chunk()])
    thesis_repository = InMemoryInvestmentThesisRepository([_thesis()])
    snapshot_repository = InMemorySnapshotRepository([_snapshot()])
    prediction_repository = InMemoryPredictionRepository([_prediction()])
    provenance_repository = InMemoryProvenanceRepository([_provenance()])
    score_repository = InMemoryChunkScoreRepository([_score()])
    run_repository = InMemoryExperimentRunRepository([_run()])

    assert document_repository.get("document-1") == _document()
    assert chunk_repository.list_for_document("document-1") == (_chunk(),)
    assert thesis_repository.list_for_user("user-1") == (_thesis(),)
    assert snapshot_repository.list_for_company("AAPL") == (_snapshot(),)
    assert prediction_repository.list_for_company("AAPL") == (_prediction(),)
    assert provenance_repository.get("run-1") == _provenance()
    assert score_repository.list_for_chunk("chunk-1") == (_score(),)
    assert run_repository.get("run-1") == _run()


def test_chunk_scores_are_append_only_by_chunk_and_run() -> None:
    repository = InMemoryChunkScoreRepository([_score()])
    replacement = _score()
    repository.save(replacement)

    assert repository.list_for_chunk("chunk-1") == (replacement,)
    repository.save(_score(run_id="run-2"))
    assert [score.run_id for score in repository.list_for_chunk("chunk-1")] == ["run-1", "run-2"]


def test_repositories_replace_by_stable_identity_and_filter_history() -> None:
    repository = InMemoryDocumentRepository([_document()])
    replacement = _document("document-1", company="MSFT")

    repository.save(replacement)

    assert repository.get("document-1") == replacement
    assert repository.list_documents(company="AAPL") == ()
    assert repository.list_documents(company="MSFT") == (replacement,)


def test_user_account_repository_replaces_stable_identity_and_looks_up_all_unique_values() -> None:
    repository = InMemoryUserAccountRepository((_account(),))
    replacement = _account(email="different@example.com", username="different", api_key="different-key")

    repository.save(replacement)

    assert repository.get_by_email("investor@example.com") is None
    assert repository.get_by_username("investor") is None
    assert repository.get_by_api_key_digest(sha256(b"api-key").hexdigest()) is None
    assert repository.get_by_email("different@example.com") == replacement
    assert repository.get_by_username("different") == replacement
    assert repository.get_by_api_key_digest(sha256(b"different-key").hexdigest()) == replacement


def test_deterministic_scorer_returns_repeatable_results() -> None:
    scorer = DeterministicLLMScorer()
    chunk = _chunk()

    first = scorer.score_chunk(chunk)
    second = scorer.score_chunk(chunk, context="Context is ignored by this deterministic fake.")

    assert first == second
    assert 0 <= first.importance_score <= 1
    assert first.token_usage is not None


def test_deterministic_embeddings_return_repeatable_fixed_dimension_vectors() -> None:
    embeddings = DeterministicEmbeddings(dimension=4)

    assert embeddings.embed("same text") == embeddings.embed("same text")
    assert len(embeddings.embed("same text")) == 4
    assert embeddings.embed("same text") != embeddings.embed("different text")


def test_vector_store_filters_and_orders_matches() -> None:
    embeddings = DeterministicEmbeddings(dimension=4)
    first_chunk = _chunk(chunk_id="chunk-1")
    second_chunk = _chunk(chunk_id="chunk-2", ordinal=1)
    store = InMemoryVectorStore()
    store.upsert(
        (
            EmbeddedChunk(
                chunk=first_chunk,
                company="AAPL",
                published_at=date(2025, 1, 30),
                embedding=embeddings.embed(first_chunk.content),
            ),
            EmbeddedChunk(
                chunk=second_chunk,
                company="MSFT",
                published_at=date(2025, 2, 2),
                embedding=embeddings.embed(second_chunk.content),
                excluded=True,
            ),
        )
    )

    matches = store.search(
        VectorQuery(
            embedding=embeddings.embed(first_chunk.content),
            company="AAPL",
            as_of=date(2025, 2, 1),
        )
    )

    assert [match.chunk.chunk_id for match in matches] == ["chunk-1"]
    assert matches[0].score >= 0


def test_market_data_filters_and_sorts_prices() -> None:
    market_data = InMemoryMarketData(
        (
            PricePoint("AAPL", date(2025, 2, 2), 102.0),
            PricePoint("AAPL", date(2025, 1, 30), 100.0),
            PricePoint("MSFT", date(2025, 1, 30), 400.0),
        )
    )

    prices = market_data.get_prices("AAPL", start=date(2025, 1, 31))

    assert prices == (PricePoint("AAPL", date(2025, 2, 2), 102.0),)
