"""Integration coverage for the external local research-data repository."""

import os
from pathlib import Path

import pytest

from sentiment_system.adapters.outbound.persistence.in_memory import (
    InMemoryChunkRepository,
    InMemoryDocumentRepository,
)
from sentiment_system.adapters.outbound.sources.cached import CachedCorpusDocumentSource
from sentiment_system.application.use_cases.ingest_documents import IngestDocuments


@pytest.mark.integration
def test_external_research_snapshot_loads_sec_and_ir_documents() -> None:
    root_value = os.getenv("SENTIMENT_DATA_ROOT")
    if not root_value:
        pytest.skip("SENTIMENT_DATA_ROOT is not configured")

    documents = CachedCorpusDocumentSource(Path(root_value)).fetch_documents()

    assert documents
    assert {document.source for document in documents} == {"sec", "investor_relations"}
    assert all(document.raw_content.strip() for document in documents)
    assert all(document.manifest_version.strip() for document in documents)


@pytest.mark.integration
def test_external_research_documents_are_cleaned_before_chunking() -> None:
    root_value = os.getenv("SENTIMENT_DATA_ROOT")
    if not root_value:
        pytest.skip("SENTIMENT_DATA_ROOT is not configured")

    source = CachedCorpusDocumentSource(Path(root_value))
    documents = InMemoryDocumentRepository()
    chunks = InMemoryChunkRepository()
    ingest = IngestDocuments(
        source,
        documents,
        chunks,
        processing_config_version="processing-v2",
        token_counter=lambda value: len(value.split()),
    )

    result = ingest.run()

    assert result.documents
    assert result.chunks
    assert all("<html" not in document.cleaned_content.casefold() for document in result.documents)
    assert all("<document" not in document.cleaned_content.casefold() for document in result.documents)
    assert all("<html" not in chunk.content.casefold() for chunk in result.chunks)
    assert all(
        document.raw_content != document.cleaned_content for document in result.documents if document.source == "sec"
    )
