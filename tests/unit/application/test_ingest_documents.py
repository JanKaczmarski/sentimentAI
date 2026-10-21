"""Unit tests for deterministic fixture ingestion."""

from dataclasses import replace
from datetime import date, datetime, timezone
from hashlib import sha256

import pytest

from sentiment_system.adapters.outbound.persistence.in_memory import (
    InMemoryChunkRepository,
    InMemoryDocumentRepository,
)
from sentiment_system.adapters.outbound.sources.fixtures import FixtureDocumentSource
from sentiment_system.application.use_cases.ingest_documents import ContentQualityError, IngestDocuments
from sentiment_system.domain.documents import SourceDocument, SourceProvenance


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
    prefix = f"document-1:chunks:{sha256(b'fixture-ingestion-v1').hexdigest()}:chunk:"
    assert [chunk.chunk_id for chunk in result.chunks] == [prefix + "0", prefix + "1"]
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


def test_ingestion_preserves_manifest_provenance_and_chunks_only_canonical_release_copy() -> None:
    def document(*, document_id: str, canonical_for_scoring: bool) -> SourceDocument:
        return SourceDocument(
            document_id=document_id,
            source_id=document_id,
            company="AAPL",
            source="sec" if canonical_for_scoring else "investor_relations",
            published_at=date(2025, 1, 30),
            document_type="earnings_release",
            raw_content="Revenue improved. Outlook is stable. Costs declined.",
            cleaned_content="Revenue improved. Outlook is stable. Costs declined.",
            manifest_version="thesis-v1-2025-09-24",
            provenance=SourceProvenance(
                manifest_record_id=document_id,
                source_url=(
                    "https://www.sec.gov/Archives/edgar/data/320193/example.txt"
                    if canonical_for_scoring
                    else "https://investor.apple.com/example.html"
                ),
                retrieved_at=datetime(2025, 1, 31, tzinfo=timezone.utc),
                raw_path=f"raw/{document_id}.txt",
                raw_sha256="a" * 64 if canonical_for_scoring else "b" * 64,
                cleaned_path=f"cleaned/{document_id}.txt",
                cleaned_sha256="c" * 64 if canonical_for_scoring else "d" * 64,
                parser_version="source-cleaning-v1",
                source_type="sec_filing" if canonical_for_scoring else "investor_relations_release",
                form="8-K" if canonical_for_scoring else None,
                form_items=("2.02",) if canonical_for_scoring else (),
                content_group_id="AAPL:2025-Q1",
                canonical_for_scoring=canonical_for_scoring,
                evaluation_member=True,
                sector="Information Technology",
                sector_source_url="https://www.nasdaq.com/market-activity/stocks/aapl",
                sector_retrieved_at=datetime(2025, 1, 31, tzinfo=timezone.utc),
            ),
        )

    canonical = document(document_id="sec-record", canonical_for_scoring=True)
    duplicate = document(document_id="ir-record", canonical_for_scoring=False)
    document_repository = InMemoryDocumentRepository()
    chunk_repository = InMemoryChunkRepository()
    ingest = IngestDocuments(
        FixtureDocumentSource((canonical, duplicate)),
        document_repository,
        chunk_repository,
        processing_config_version="source-cleaning-v1",
        token_counter=lambda value: len(value.split()),
    )

    result = ingest.run()

    assert result.documents == (
        replace(duplicate, document_id=duplicate.derivation_id),
        replace(canonical, document_id=canonical.derivation_id),
    )
    assert {document_repository.get(document.document_id).provenance for document in result.documents} == {
        canonical.provenance,
        duplicate.provenance,
    }
    assert [chunk.document_id for chunk in result.chunks] == [canonical.derivation_id]


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
