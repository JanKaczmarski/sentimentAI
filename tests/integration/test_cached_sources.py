"""Integration coverage for the external local research-data repository."""

import hashlib
import json
import os
from datetime import date
from pathlib import Path

import pytest

from sentiment_system.adapters.outbound.persistence.in_memory import (
    InMemoryChunkRepository,
    InMemoryDocumentRepository,
)
from sentiment_system.adapters.outbound.sources.cached import CachedCorpusDocumentSource
from sentiment_system.adapters.outbound.sources.fixtures import FixtureDocumentSource
from sentiment_system.application.use_cases.ingest_documents import IngestDocuments
from sentiment_system.domain.research import FINAL_CORPUS_VERSION, RESEARCH_SELECTION_VERSION

_FUNCTIONAL_TICKERS = {"AAPL", "MSFT", "NVDA", "JPM", "XOM", "JNJ"}
_FINAL_MANIFEST_VERSION = FINAL_CORPUS_VERSION


@pytest.fixture(scope="module")
def cached_source() -> CachedCorpusDocumentSource:
    root = os.getenv("SENTIMENT_DATA_ROOT")
    if not root:
        pytest.skip("SENTIMENT_DATA_ROOT is not configured")
    return CachedCorpusDocumentSource(Path(root))


@pytest.mark.integration
def test_external_research_snapshot_loads_sec_and_ir_documents(cached_source: CachedCorpusDocumentSource) -> None:
    root_value = os.getenv("SENTIMENT_DATA_ROOT")
    if not root_value:
        pytest.skip("SENTIMENT_DATA_ROOT is not configured")

    source = cached_source
    documents = source.fetch_documents()

    assert documents
    assert {document.source for document in documents} == {"sec", "investor_relations"}
    assert all(document.raw_content.strip() for document in documents)
    assert all(document.manifest_version.strip() for document in documents)


@pytest.mark.integration
def test_external_research_snapshot_contains_all_functional_tickers(cached_source: CachedCorpusDocumentSource) -> None:
    root_value = os.getenv("SENTIMENT_DATA_ROOT")
    if not root_value:
        pytest.skip("SENTIMENT_DATA_ROOT is not configured")

    source = cached_source
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
def test_external_cached_corpus_exposes_amat_as_a_normal_company(cached_source: CachedCorpusDocumentSource) -> None:
    root_value = os.getenv("SENTIMENT_DATA_ROOT")
    if not root_value:
        pytest.skip("SENTIMENT_DATA_ROOT is not configured")

    documents = cached_source.fetch_documents(
        company="AMAT",
        published_before=date(2026, 5, 15),
    )

    assert len(documents) > 2
    assert {document.source for document in documents} == {"sec", "investor_relations"}
    assert all(document.raw_content.strip() for document in documents)


@pytest.mark.integration
def test_external_research_documents_are_cleaned_before_chunking(cached_source: CachedCorpusDocumentSource) -> None:
    root_value = os.getenv("SENTIMENT_DATA_ROOT")
    if not root_value:
        pytest.skip("SENTIMENT_DATA_ROOT is not configured")

    # This verifies cleaning/chunking boundaries, not a full research batch.
    # Keep it bounded as the immutable corpus grows; integrity is checked separately.
    candidates = cached_source.fetch_documents()
    source = FixtureDocumentSource(
        min(
            (document for document in candidates if document.source == kind and document.provenance is None),
            key=lambda document: len(document.raw_content),
        )
        for kind in ("sec", "investor_relations")
    )
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


@pytest.mark.integration
def test_external_final_corpus_is_hash_verified_complete_and_canonical(
    cached_source: CachedCorpusDocumentSource,
) -> None:
    root_value = os.getenv("SENTIMENT_DATA_ROOT")
    if not root_value:
        pytest.skip("SENTIMENT_DATA_ROOT is not configured")
    manifest_path = Path(root_value) / "data" / "corpora" / _FINAL_MANIFEST_VERSION / "manifest.json"
    if not manifest_path.is_file():
        pytest.skip("final thesis corpus is not acquired")

    documents = cached_source.fetch_evaluation_documents()

    assert {document.company for document in documents} == {"META", "CRM", "V", "DIS", "WHR", "T"}
    assert {document.source for document in documents} == {"sec", "investor_relations"}
    assert all(document.manifest_version == _FINAL_MANIFEST_VERSION for document in documents)
    assert all(document.provenance is not None for document in documents)
    assert all(document.provenance.raw_sha256 for document in documents if document.provenance is not None)
    assert all(document.provenance.cleaned_sha256 for document in documents if document.provenance is not None)
    groups: dict[str, list[object]] = {}
    for document in documents:
        assert document.provenance is not None
        groups.setdefault(document.provenance.content_group_id, []).append(document.provenance)
    assert all(sum(provenance.canonical_for_scoring for provenance in group) == 1 for group in groups.values())
    selection_path = Path(root_value) / f"data/research_selection/{RESEARCH_SELECTION_VERSION}.json"
    selection = json.loads(selection_path.read_bytes())
    assert {
        (document.company, document.source, document.source_id, document.provenance.raw_sha256)
        for document in documents
        if document.provenance is not None
    } == {
        (record["company"], record["source"], record["source_id"], record["raw_sha256"])
        for record in selection["records"]
    }
    assert any(
        document.published_at < date.fromisoformat(selection["corpus_window"]["start"])
        for document in cached_source.fetch_documents(company="META")
    )
    assert all(document.company != "AMAT" for document in documents)


@pytest.mark.integration
def test_external_cleaning_revision_preserves_frozen_evidence_and_ingests_reviewed_text(
    cached_source: CachedCorpusDocumentSource,
) -> None:
    root_value = os.getenv("SENTIMENT_DATA_ROOT")
    if not root_value:
        pytest.skip("SENTIMENT_DATA_ROOT is not configured")
    root = Path(root_value)
    current = root / "data/corpora" / FINAL_CORPUS_VERSION
    if not (current / "manifest.json").is_file():
        pytest.skip("reviewed cleaned corpus is not published")
    predecessor = root / "data/corpora" / RESEARCH_SELECTION_VERSION
    old = json.loads((predecessor / "manifest.json").read_bytes())
    new = json.loads((current / "manifest.json").read_bytes())
    inventory = json.loads((current / "provenance/predecessor-inventory.json").read_bytes())
    actual_inventory = {
        path.relative_to(predecessor).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in predecessor.rglob("*")
        if path.is_file()
    }
    assert actual_inventory == inventory
    assert (current / "provenance/predecessor-manifest.json").read_bytes() == (
        predecessor / "manifest.json"
    ).read_bytes()
    assert (current / "provenance/selection.json").read_bytes() == (
        root / f"data/research_selection/{RESEARCH_SELECTION_VERSION}.json"
    ).read_bytes()
    assert len(new["records"]) == len(old["records"]) == 363
    for field in ("corpus_window", "development_ends", "held_out_starts", "companies", "sector_review_sha256"):
        assert new[field] == old[field]
    assert sum(item["source"] == "sec" for item in new["records"]) == 243
    for previous, revised in zip(old["records"], new["records"], strict=True):
        mutable = {"cleaned_sha256", "parser_version"} if revised["source"] == "sec" else set()
        assert {k: v for k, v in previous.items() if k not in mutable} == {
            k: v for k, v in revised.items() if k not in mutable
        }
        if revised["source"] == "sec":
            assert revised["parser_version"] == "sec-form-aware-v2"
        else:
            assert (current / revised["cleaned_path"]).read_bytes() == (
                predecessor / previous["cleaned_path"]
            ).read_bytes()

    accession = "0000732717-22-000038"
    documents = [d for d in cached_source.fetch_documents(company="T") if d.source_id == accession]
    assert len(documents) == 1
    assert documents[0].manifest_version == FINAL_CORPUS_VERSION
    result = IngestDocuments(
        FixtureDocumentSource(documents),
        InMemoryDocumentRepository(),
        InMemoryChunkRepository(),
        processing_config_version="reviewed-corpus-regression",
        token_counter=lambda text: len(text.split()),
    ).run()
    assert result.chunks
    assert hashlib.sha256(result.documents[0].cleaned_content.encode()).hexdigest() == (
        "8fe4ec4d504f58ee9cc509debb5a00996ff22935b018e1b8efc66bc2da3dd605"
    )


@pytest.mark.integration
def test_external_sec_history_is_available_operationally_without_expanding_evaluation(cached_source):
    root = Path(os.environ["SENTIMENT_DATA_ROOT"])
    documents = cached_source.fetch_documents()
    revisions = {(d.company, d.source, d.source_id, d.original_byte_sha256): d for d in documents}
    assert len(revisions) == len(documents)
    for manifest_path in (root / "data/sec/history").glob("*/manifest.json"):
        manifest = json.loads(manifest_path.read_bytes())
        for record in manifest["documents"]:
            if record["status"] not in {"downloaded", "existing"} or record["form"] not in {"10-K", "10-Q", "8-K"}:
                continue
            document = revisions[(manifest["ticker"], "sec", record["accession_number"], record["raw_sha256"])]
            assert document.published_at.isoformat() == record["published_at"]
    assert len(cached_source.fetch_evaluation_documents()) == 363
    # This acquired, non-earnings filing is outside the frozen evaluation cutoff.
    candidates = [
        d
        for d in cached_source.fetch_documents(company="T")
        if d.published_at == date(2026, 10, 16) and d.document_type == "8-K"
    ]
    assert candidates
    result = IngestDocuments(
        FixtureDocumentSource((min(candidates, key=lambda d: len(d.raw_content)),)),
        InMemoryDocumentRepository(),
        InMemoryChunkRepository(),
        processing_config_version="history-regression-v1",
        token_counter=lambda text: len(text.split()),
    ).run()
    assert result.documents[0].artifact.form == "8-K"
    assert result.chunks
