"""Composition root that wires ports to concrete adapters."""

import os
from dataclasses import dataclass
from datetime import date
from pathlib import Path

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
from sentiment_system.adapters.outbound.sources.cached import CachedCorpusDocumentSource
from sentiment_system.adapters.outbound.sources.demo_manifest import DemoManifestDocumentSource
from sentiment_system.adapters.outbound.sources.fixtures import FixtureDocumentSource
from sentiment_system.adapters.outbound.vector.in_memory import InMemoryVectorStore
from sentiment_system.adapters.outbound.vector.qdrant import QdrantVectorStore
from sentiment_system.application.ports.document_sources import DocumentSource
from sentiment_system.application.ports.embeddings import EmbeddingProvider
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
from sentiment_system.application.ports.vector_store import VectorStore
from sentiment_system.application.use_cases.aggregate_snapshots import AggregateSnapshots
from sentiment_system.application.use_cases.create_account import CreateAccount
from sentiment_system.application.use_cases.generate_prediction import GeneratePrediction, ListPredictionHistory
from sentiment_system.application.use_cases.index_chunks import IndexChunks
from sentiment_system.application.use_cases.ingest_documents import IngestDocuments
from sentiment_system.application.use_cases.ingest_fixture_communication import IngestFixtureCommunication
from sentiment_system.application.use_cases.manage_investment_theses import ManageInvestmentTheses
from sentiment_system.application.use_cases.run_batch import RunBatch
from sentiment_system.application.use_cases.score_chunks import ScoreChunks
from sentiment_system.bootstrap.config import (
    EmbeddingConfig,
    LLMConfig,
    build_embedding_provider,
    build_llm_scorer,
)


@dataclass(frozen=True, slots=True)
class ApplicationContainer:
    """Runtime services supplied to inbound adapters by the composition root."""

    account_repository: UserAccountRepository | None = None
    create_account: CreateAccount | None = None
    investment_thesis_repository: InvestmentThesisRepository | None = None
    manage_investment_theses: ManageInvestmentTheses | None = None
    embedding_provider: EmbeddingProvider | None = None
    vector_store: VectorStore | None = None
    index_chunks: IndexChunks | None = None
    research_database: PostgresDatabase | None = None
    document_repository: DocumentRepository | None = None
    chunk_repository: ChunkRepository | None = None
    chunk_score_repository: ChunkScoreRepository | None = None
    snapshot_repository: SnapshotRepository | None = None
    experiment_run_repository: ExperimentRunRepository | None = None
    provenance_repository: ExperimentProvenanceRepository | None = None
    prediction_repository: PredictionRepository | None = None
    generate_prediction: GeneratePrediction | None = None
    list_prediction_history: ListPredictionHistory | None = None
    ingest_fixture_communication: IngestFixtureCommunication | None = None
    run_batch: RunBatch | None = None


_POC_DOCUMENTS = (
    {
        "document_id": "poc-document-aapl-2025-01-15",
        "source_id": "poc-source-aapl-2025-01-15",
        "company": "AAPL",
        "source": "poc_fixture",
        "published_at": date(2025, 1, 15),
        "document_type": "company_communication",
        "raw_content": "Revenue increased. Operating costs remained controlled.",
    },
)


def build_container() -> ApplicationContainer:
    """Build the runtime service container.

    Services are added here as their application use cases are implemented.
    """
    account_repository: UserAccountRepository = InMemoryUserAccountRepository()
    investment_thesis_repository: InvestmentThesisRepository = InMemoryInvestmentThesisRepository()
    document_repository: DocumentRepository = InMemoryDocumentRepository()
    chunk_repository: ChunkRepository = InMemoryChunkRepository()
    chunk_score_repository: ChunkScoreRepository = InMemoryChunkScoreRepository()
    snapshot_repository: SnapshotRepository = InMemorySnapshotRepository()
    experiment_run_repository: ExperimentRunRepository = InMemoryExperimentRunRepository()
    provenance_repository: ExperimentProvenanceRepository = InMemoryProvenanceRepository()
    prediction_repository: PredictionRepository = InMemoryPredictionRepository()
    embedding_config = EmbeddingConfig.from_env()
    embedding_provider = build_embedding_provider(embedding_config)
    data_root = os.getenv("SENTIMENT_DATA_ROOT")
    manifest_path = os.getenv("DEMO_MANIFEST_PATH")
    document_source: DocumentSource
    if manifest_path:
        if not data_root:
            raise ValueError("SENTIMENT_DATA_ROOT is required when DEMO_MANIFEST_PATH is configured")
        document_source = DemoManifestDocumentSource(root=Path(data_root), manifest_path=Path(manifest_path))
    else:
        document_source = (
            CachedCorpusDocumentSource(Path(data_root)) if data_root else FixtureDocumentSource(_POC_DOCUMENTS)
        )
    llm_config = LLMConfig.from_env()
    llm_scorer = build_llm_scorer(llm_config)
    database_url = os.getenv("DATABASE_URL")
    qdrant_url = os.getenv("QDRANT_URL")
    research_database = None
    if database_url:
        research_database = PostgresDatabase(database_url)
        research_database.migrate()
        account_repository = PostgresUserAccountRepository(research_database)
        investment_thesis_repository = PostgresInvestmentThesisRepository(research_database)
        document_repository = PostgresDocumentRepository(research_database)
        chunk_repository = PostgresChunkRepository(research_database)
        chunk_score_repository = PostgresChunkScoreRepository(research_database)
        snapshot_repository = PostgresSnapshotRepository(research_database)
        experiment_run_repository = PostgresExperimentRunRepository(research_database)
        provenance_repository = PostgresProvenanceRepository(research_database)
        prediction_repository = PostgresPredictionRepository(research_database)
    vector_store: VectorStore = InMemoryVectorStore()
    index_chunks = IndexChunks(document_repository, embedding_provider, vector_store)
    if qdrant_url:
        vector_store = QdrantVectorStore(
            url=qdrant_url,
            collection_name=os.getenv("QDRANT_COLLECTION") or "sentiment_chunks",
        )
        index_chunks = IndexChunks(document_repository, embedding_provider, vector_store)
    ingest_documents = IngestDocuments(
        document_source,
        document_repository,
        chunk_repository,
        processing_config_version="processing-v2",
        token_counter=lambda value: len(value.split()),
    )
    score_chunks = ScoreChunks(
        llm_scorer,
        chunk_score_repository,
        provenance_repository,
        experiment_run_repository,
        provider=llm_config.backend,
        model_name=llm_config.model_name,
    )
    aggregate_snapshots = AggregateSnapshots(
        document_repository,
        chunk_repository,
        chunk_score_repository,
        snapshot_repository,
    )
    return ApplicationContainer(
        account_repository=account_repository,
        create_account=CreateAccount(account_repository),
        investment_thesis_repository=investment_thesis_repository,
        manage_investment_theses=ManageInvestmentTheses(account_repository, investment_thesis_repository),
        embedding_provider=embedding_provider,
        vector_store=vector_store,
        index_chunks=index_chunks,
        research_database=research_database,
        document_repository=document_repository,
        chunk_repository=chunk_repository,
        chunk_score_repository=chunk_score_repository,
        snapshot_repository=snapshot_repository,
        experiment_run_repository=experiment_run_repository,
        provenance_repository=provenance_repository,
        prediction_repository=prediction_repository,
        generate_prediction=GeneratePrediction(
            account_repository,
            investment_thesis_repository,
            snapshot_repository,
            prediction_repository,
        ),
        list_prediction_history=ListPredictionHistory(account_repository, prediction_repository),
        ingest_fixture_communication=IngestFixtureCommunication(document_repository, chunk_repository),
        run_batch=RunBatch(
            ingest_documents,
            index_chunks,
            score_chunks,
            aggregate_snapshots,
            experiment_run_repository,
            scoring_prompt=getattr(llm_scorer, "prompt", None),
            scoring_provider=llm_config.backend,
            scoring_model=llm_config.model_name,
        ),
    )
