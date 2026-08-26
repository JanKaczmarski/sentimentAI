"""Integration coverage for fixture ingestion across source and repositories."""

from sentiment_system.adapters.outbound.persistence.in_memory import (
    InMemoryChunkRepository,
    InMemoryDocumentRepository,
)
from sentiment_system.adapters.outbound.sources.fixtures import FixtureDocumentSource
from sentiment_system.application.use_cases.ingest_documents import IngestDocuments


def test_fixture_communications_are_ingested_into_auditable_repositories() -> None:
    source = FixtureDocumentSource(
        (
            {
                "document_id": "communication-1",
                "source_id": "email-1",
                "company": "MSFT",
                "source": "fixture-email",
                "published_at": "2025-02-01",
                "document_type": "company_communication",
                "raw_content": "Revenue improved. Outlook is stable. Hiring continues.",
            },
        )
    )
    documents = InMemoryDocumentRepository()
    chunks = InMemoryChunkRepository()
    ingest = IngestDocuments(
        source,
        documents,
        chunks,
        processing_config_version="fixture-ingestion-v1",
        token_counter=lambda value: len(value.split()),
    )

    result = ingest.run(company="MSFT")

    assert documents.get("communication-1") == result.documents[0]
    assert chunks.list_for_document("communication-1") == result.chunks
    assert result.documents[0].raw_content == "Revenue improved. Outlook is stable. Hiring continues."
    assert result.chunks[0].processing_config_version == "fixture-ingestion-v1"


def test_html_communication_is_cleaned_before_persistence() -> None:
    raw_content = "<html><body><h1>Results</h1><p>Revenue &amp; outlook improved.</p></body></html>"
    source = FixtureDocumentSource(
        (
            {
                "document_id": "communication-html",
                "source_id": "html-1",
                "company": "MSFT",
                "source": "investor_relations",
                "published_at": "2025-02-01",
                "document_type": "earnings_release",
                "raw_content": raw_content,
            },
        )
    )
    documents = InMemoryDocumentRepository()
    chunks = InMemoryChunkRepository()
    ingest = IngestDocuments(
        source,
        documents,
        chunks,
        processing_config_version="fixture-ingestion-v1",
        token_counter=lambda value: len(value.split()),
    )

    result = ingest.run(company="MSFT")

    assert result.documents[0].raw_content == raw_content
    assert result.documents[0].cleaned_content == "Results\nRevenue & outlook improved."
    assert chunks.list_for_document("communication-html") == result.chunks
