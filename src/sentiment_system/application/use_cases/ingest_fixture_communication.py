"""Use case for ingesting one API-supplied fixture communication."""

from datetime import date

from sentiment_system.adapters.outbound.sources.fixtures import FixtureDocumentSource
from sentiment_system.application.ports.repositories import ChunkRepository, DocumentRepository
from sentiment_system.application.use_cases.ingest_documents import IngestDocuments, IngestionResult


class IngestFixtureCommunication:
    """Adapt one HTTP fixture payload into the standard ingestion pipeline."""

    def __init__(self, documents: DocumentRepository, chunks: ChunkRepository) -> None:
        self._documents = documents
        self._chunks = chunks

    def execute(
        self,
        *,
        document_id: str,
        source_id: str,
        company: str,
        source: str,
        published_at: date,
        document_type: str,
        raw_content: str,
    ) -> IngestionResult:
        source_adapter = FixtureDocumentSource(
            (
                {
                    "document_id": document_id,
                    "source_id": source_id,
                    "company": company,
                    "source": source,
                    "published_at": published_at,
                    "document_type": document_type,
                    "raw_content": raw_content,
                },
            )
        )
        return IngestDocuments(
            source_adapter,
            self._documents,
            self._chunks,
            processing_config_version="processing-v2",
            token_counter=lambda value: len(value.split()),
        ).run()
