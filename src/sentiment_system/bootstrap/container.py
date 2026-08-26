"""Composition root that wires ports to concrete adapters."""

import os
from dataclasses import dataclass

from sentiment_system.adapters.outbound.persistence.in_memory import (
    InMemoryInvestmentThesisRepository,
    InMemoryUserAccountRepository,
)
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
from sentiment_system.adapters.outbound.vector.qdrant import QdrantVectorStore
from sentiment_system.application.ports.embeddings import EmbeddingProvider
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
from sentiment_system.application.ports.vector_store import VectorStore
from sentiment_system.application.use_cases.create_account import CreateAccount
from sentiment_system.application.use_cases.index_chunks import IndexChunks
from sentiment_system.application.use_cases.manage_investment_theses import ManageInvestmentTheses
from sentiment_system.bootstrap.config import EmbeddingConfig, build_embedding_provider


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


def build_container() -> ApplicationContainer:
    """Build the runtime service container.

    Services are added here as their application use cases are implemented.
    """
    account_repository: UserAccountRepository = InMemoryUserAccountRepository()
    investment_thesis_repository: InvestmentThesisRepository = InMemoryInvestmentThesisRepository()
    embedding_provider = build_embedding_provider(EmbeddingConfig.from_env())
    database_url = os.getenv("DATABASE_URL")
    qdrant_url = os.getenv("QDRANT_URL")
    research_database = None
    document_repository = None
    chunk_repository = None
    chunk_score_repository = None
    snapshot_repository = None
    experiment_run_repository = None
    provenance_repository = None
    vector_store = None
    index_chunks = None
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
    if qdrant_url:
        vector_store = QdrantVectorStore(
            url=qdrant_url,
            collection_name=os.getenv("QDRANT_COLLECTION") or "sentiment_chunks",
        )
        if document_repository is not None:
            index_chunks = IndexChunks(document_repository, embedding_provider, vector_store)
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
    )
