"""Integration coverage for the external local research-data repository."""

import os
from pathlib import Path

import pytest

from sentiment_system.adapters.outbound.sources.cached import CachedCorpusDocumentSource


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
