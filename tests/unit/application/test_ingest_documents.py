"""Unit tests for deterministic fixture ingestion."""

from datetime import date

import pytest

from sentiment_system.adapters.outbound.persistence.in_memory import (
    InMemoryChunkRepository,
    InMemoryDocumentRepository,
)
from sentiment_system.adapters.outbound.sources.fixtures import FixtureDocumentSource
from sentiment_system.application.use_cases.ingest_documents import ContentQualityError, IngestDocuments


def _fixture(*, document_id: str = "document-1", raw_content: str = "First sentence.") -> dict[str, object]:
    return {
        "document_id": document_id,
        "source_id": f"source-{document_id}",
        "company": "AAPL",
        "source": "fixture",
        "published_at": "2025-01-30",
        "document_type": "company_communication",
        "raw_content": raw_content,
    }


def _ingestor(
    *fixtures: dict[str, object]
) -> tuple[IngestDocuments, InMemoryDocumentRepository, InMemoryChunkRepository]:
    document_repository = InMemoryDocumentRepository()
    chunk_repository = InMemoryChunkRepository()
    source = FixtureDocumentSource(fixtures)
    return (
        IngestDocuments(
            source,
            document_repository,
            chunk_repository,
            processing_config_version="fixture-ingestion-v1",
            token_counter=lambda value: len(value.split()),
        ),
        document_repository,
        chunk_repository,
    )


def test_malformed_fixture_input_fails_explicitly() -> None:
    with pytest.raises(ValueError, match="raw_content is required"):
        FixtureDocumentSource(({**_fixture(), "raw_content": ""},))


def test_ingestion_preserves_raw_lineage_and_creates_cleaned_deterministic_chunks() -> None:
    raw_content = (
        "Page 1\n  Revenue   improved. Outlook is stable. Costs declined. Guidance is firm. Growth continues.\nPage 1"
    )
    ingestor, document_repository, chunk_repository = _ingestor(_fixture(raw_content=raw_content))

    result = ingestor.run()

    document = document_repository.get("document-1")
    assert document is not None
    assert document.raw_content == raw_content
    assert (
        document.cleaned_content
        == "Revenue improved. Outlook is stable. Costs declined. Guidance is firm. Growth continues."
    )
    assert document.company == "AAPL"
    assert document.source_id == "source-document-1"
    assert document.published_at == date(2025, 1, 30)
    assert [chunk.ordinal for chunk in result.chunks] == [0, 1]
    assert [chunk.chunk_id for chunk in result.chunks] == ["document-1:chunk:0", "document-1:chunk:1"]
    assert [chunk.content for chunk in result.chunks] == [
        "Revenue improved. Outlook is stable. Costs declined.",
        "Guidance is firm. Growth continues.",
    ]
    assert all(chunk.processing_config_version == "fixture-ingestion-v1" for chunk in result.chunks)
    assert chunk_repository.list_for_document("document-1") == result.chunks


def test_reprocessing_same_fixture_is_idempotent_and_deterministic() -> None:
    ingestor, document_repository, chunk_repository = _ingestor(
        _fixture(raw_content="One sentence. Two sentences. Three sentences."),
    )

    first = ingestor.run()
    second = ingestor.run()

    assert second == first
    assert document_repository.list_documents() == first.documents
    assert chunk_repository.list_for_document("document-1") == first.chunks


def test_ingestion_extracts_sec_exhibit_and_removes_markup_without_changing_raw_content() -> None:
    raw_content = """
    <SEC-DOCUMENT>submission.txt
    <DOCUMENT>
    <TYPE>8-K
    <TEXT><XBRL>encoded filing metadata</XBRL></TEXT>
    </DOCUMENT>
    <DOCUMENT>
    <TYPE>EX-99.1
    <TEXT><html><head><title>Hidden title</title><style>.noise { display: none; }</style></head>
    <body><h1>Quarterly results</h1><p>Revenue &amp; outlook improved.</p>
    <p>Table of Contents</p></body></html></TEXT>
    </DOCUMENT>
    </SEC-DOCUMENT>
    """
    ingestor, document_repository, _ = _ingestor(_fixture(raw_content=raw_content))

    result = ingestor.run()

    document = document_repository.get("document-1")
    assert document is not None
    assert document.raw_content == raw_content
    assert "Quarterly results" in document.cleaned_content
    assert "Revenue & outlook improved." in document.cleaned_content
    assert "encoded filing metadata" not in document.cleaned_content
    assert "Table of Contents" not in document.cleaned_content
    assert "<html" not in document.cleaned_content
    assert "&amp;" not in document.cleaned_content
    assert result.chunks


def test_ingestion_rejects_unreadable_content_before_persistence() -> None:
    ingestor, document_repository, chunk_repository = _ingestor(_fixture(raw_content="☠" * 100))

    with pytest.raises(ContentQualityError, match="readable"):
        ingestor.run()

    assert document_repository.list_documents() == ()
    assert chunk_repository.list_for_document("document-1") == ()
