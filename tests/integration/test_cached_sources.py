"""Integration coverage for the external local research-data repository."""

import hashlib
import json
import os
from pathlib import Path

import pytest

from sentiment_system.adapters.outbound.persistence.in_memory import (
    InMemoryChunkRepository,
    InMemoryDocumentRepository,
)
from sentiment_system.adapters.outbound.sources.cached import CachedCorpusDocumentSource
from sentiment_system.application.use_cases.ingest_documents import IngestDocuments

_FUNCTIONAL_TICKERS = {"AAPL", "MSFT", "NVDA", "JPM", "XOM", "JNJ"}


@pytest.mark.integration
def test_external_research_snapshot_loads_sec_and_ir_documents() -> None:
    root_value = os.getenv("SENTIMENT_DATA_ROOT")
    if not root_value:
        pytest.skip("SENTIMENT_DATA_ROOT is not configured")

    source = CachedCorpusDocumentSource(Path(root_value))
    documents = source.fetch_documents()

    assert documents
    assert {document.source for document in documents} == {"sec", "investor_relations"}
    assert all(document.raw_content.strip() for document in documents)
    assert all(document.manifest_version.strip() for document in documents)


@pytest.mark.integration
def test_external_research_snapshot_contains_all_functional_tickers() -> None:
    root_value = os.getenv("SENTIMENT_DATA_ROOT")
    if not root_value:
        pytest.skip("SENTIMENT_DATA_ROOT is not configured")

    source = CachedCorpusDocumentSource(Path(root_value))
    documents = source.fetch_documents()
    manifest_path = Path(root_value) / "data" / "sec" / "manifests" / "previous_calendar_quarter_earnings_releases.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    records = {record["ticker"]: record for record in manifest["releases"]}

    assert _FUNCTIONAL_TICKERS <= {document.company for document in documents}
    assert all(source.fetch_documents(company=ticker) for ticker in _FUNCTIONAL_TICKERS)
    for ticker in _FUNCTIONAL_TICKERS:
        record = records[ticker]
        path = Path(root_value) / "data" / "sec" / "earnings_releases" / f"{ticker}_{record['accession_number']}.txt"
        assert record["raw_sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()


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
