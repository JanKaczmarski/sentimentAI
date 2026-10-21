"""Standalone document preparation is reusable, audited and independent of scoring."""

from dataclasses import replace
from datetime import date

import pytest

from sentiment_system.adapters.outbound.embeddings.mock import DeterministicEmbeddings
from sentiment_system.adapters.outbound.persistence.in_memory import (
    InMemoryChunkRepository,
    InMemoryDocumentRepository,
    InMemoryExperimentRunRepository,
    InMemoryProvenanceRepository,
)
from sentiment_system.adapters.outbound.sources.fixtures import FixtureDocumentSource
from sentiment_system.adapters.outbound.vector.in_memory import InMemoryVectorStore
from sentiment_system.application.use_cases.index_chunks import IndexChunks
from sentiment_system.application.use_cases.ingest_company_documents import (
    IngestCompanyDocuments,
    IngestionExecutionError,
)
from sentiment_system.application.use_cases.ingest_documents import IngestDocuments
from sentiment_system.domain.documents import SourceDocument


def document(identity="one", published=date(2025, 1, 1), company="META"):
    return SourceDocument(identity, identity, company, "fixture", published, "release", "Revenue grew. Costs fell.", "")


@pytest.fixture
def setup():
    documents, chunks = InMemoryDocumentRepository(), InMemoryChunkRepository()
    runs, provenance = InMemoryExperimentRunRepository(), InMemoryProvenanceRepository()
    embeddings, vectors = DeterministicEmbeddings(), InMemoryVectorStore()
    config = {"backend": "mock", "model": "deterministic-sha256-v1"}

    def build(sources, frozen=None):
        def ingestion(items):
            return IngestDocuments(
                FixtureDocumentSource(items),
                documents,
                chunks,
                processing_config_version="processing-v2",
                token_counter=lambda text: len(text.split()),
            )

        indexing = IndexChunks(documents, embeddings, vectors, embedding_configuration=config)
        return IngestCompanyDocuments(
            ingestion(sources),
            indexing,
            runs,
            provenance=provenance,
            frozen_ingestion=ingestion(frozen) if frozen is not None else None,
            frozen_manifest={"source_manifest_version": "frozen-v1", "source_manifest_sha256": "a" * 64},
            embedding_configuration=config,
            input_source="fixture",
        )

    return build, documents, chunks, runs, provenance, embeddings, vectors


def test_ingestion_reuses_data_with_fresh_audit_runs_and_strict_company_date_scope(setup, monkeypatch):
    build, documents, chunks, runs, provenance, embeddings, _ = setup
    calls = []
    original = embeddings.embed
    monkeypatch.setattr(embeddings, "embed", lambda text: (calls.append(text), original(text))[1])
    service = build((document(), document("same-day", date(2025, 1, 2)), document("other", company="CRM")))
    first = service.execute(company="meta", as_of=date(2025, 1, 2))
    stored = documents.list_documents()
    second = service.execute(company="META", as_of=date(2025, 1, 2))
    assert first.run_id != second.run_id
    assert first.document_count == second.document_count == 1
    assert first.chunk_count == second.chunk_count == second.indexed_chunk_count == 1
    assert first.embedded_chunk_count == second.reused_chunk_count == len(calls) == 1
    assert second.embedded_chunk_count == 0
    assert documents.list_documents() == stored
    assert len(chunks.list_for_document(stored[0].document_id)) == 1
    run = runs.get(second.run_id)
    assert run.run_type == "ingestion" and run.status == "completed"
    audit = provenance.get(second.run_id)
    assert audit.processing_config["publication_rule"] == "published_at < as_of"
    assert audit.processing_config["source_lineage"][0]["chunk_ids"]
    assert set(audit.processing_config["stages"]) == {"ingestion", "indexing"}
    assert audit.raw_response == "" and audit.parsed_output == {}


def test_ingestion_explicit_frozen_scope_and_empty_selection(setup):
    build, _, _, runs, provenance, _, _ = setup
    service = build((document("broad"),), frozen=(document("frozen"),))
    frozen = service.execute(company="META", as_of=date(2025, 1, 2), source_scope="frozen")
    assert provenance.get(frozen.run_id).processing_config["source_lineage"][0]["source_id"] == "frozen"
    assert runs.get(frozen.run_id).configuration["source_manifest_sha256"] == "a" * 64
    empty = service.execute(company="CRM", as_of=date(2025, 1, 2))
    assert empty.document_count == empty.chunk_count == empty.indexed_chunk_count == 0
    assert empty.embedded_chunk_count == empty.reused_chunk_count == 0
    assert runs.get(empty.run_id).status == "completed"


def test_expanded_cached_selection_only_embeds_additional_chunks(setup):
    build, documents, _, _, _, _, _ = setup
    first = build((document(),)).execute(company="META", as_of=date(2025, 1, 2))
    expanded = build((document(), document("additional"))).execute(company="META", as_of=date(2025, 1, 2))
    assert first.document_count == 1
    assert expanded.document_count == expanded.chunk_count == expanded.indexed_chunk_count == 2
    assert expanded.embedded_chunk_count == expanded.reused_chunk_count == 1
    assert len(documents.list_documents()) == 2


def test_ingestion_records_quality_failure_and_retry_preserves_prior_data(setup):
    build, documents, _, runs, provenance, _, _ = setup
    service = build((document(), replace(document("two"), raw_content="###")))
    with pytest.raises(IngestionExecutionError) as failure:
        service.execute(company="META", as_of=date(2025, 1, 2))
    audit = provenance.get(failure.value.run_id)
    assert runs.get(failure.value.run_id).status == "failed"
    assert audit.processing_config["document_count"] == 1
    assert audit.processing_config["failed_stage"] == "ingestion"
    assert len(documents.list_documents()) == 1
    retried = build((document(), document("two"))).execute(company="META", as_of=date(2025, 1, 2))
    assert retried.document_count == 2
    assert provenance.get(failure.value.run_id) == audit


def test_missing_frozen_manifest_fails_without_operational_fallback(setup):
    build, documents, _, _, provenance, _, _ = setup
    with pytest.raises(IngestionExecutionError) as failure:
        build((document(),)).execute(company="META", as_of=date(2025, 1, 2), source_scope="frozen")
    assert documents.list_documents() == ()
    assert provenance.get(failure.value.run_id).processing_config["failed_stage"] == "ingestion"


def test_ingestion_validates_company_and_scope_before_creating_run(setup):
    build, _, _, runs, _, _, _ = setup
    with pytest.raises(ValueError):
        build(()).execute(company="UNKNOWN", as_of=date(2025, 1, 2))
    with pytest.raises(ValueError):
        build(()).execute(company="META", as_of=date(2025, 1, 2), source_scope="invalid")
    assert runs.list_runs() == ()


def test_failed_embedding_retains_confirmed_index_progress_and_retry_reuses_it(setup, monkeypatch):
    build, _, _, runs, provenance, embeddings, _ = setup
    service = build((replace(document(), raw_content=" ".join(f"Sentence {i}." for i in range(390))),))
    original = embeddings.embed
    calls = 0

    def fail_after_first_batch(text):
        nonlocal calls
        calls += 1
        if calls == 129:
            raise RuntimeError("private provider connection details")
        return original(text)

    monkeypatch.setattr(embeddings, "embed", fail_after_first_batch)
    with pytest.raises(IngestionExecutionError) as failure:
        service.execute(company="META", as_of=date(2025, 1, 2))
    audit = provenance.get(failure.value.run_id)
    assert runs.get(failure.value.run_id).status == "failed"
    assert audit.processing_config["failed_stage"] == "indexing"
    assert audit.processing_config["indexed_chunk_count"] == 128
    assert audit.processing_config["embedded_chunk_count"] == 128
    assert audit.processing_config["chunk_count"] == 130
    assert "private provider" not in str(audit)
    monkeypatch.setattr(embeddings, "embed", original)
    recovered = service.execute(company="META", as_of=date(2025, 1, 2))
    assert recovered.reused_chunk_count == 128
    assert recovered.embedded_chunk_count == 2
    assert recovered.indexed_chunk_count == 130
    assert provenance.get(failure.value.run_id) == audit


@pytest.mark.parametrize("method", ("get_indexed", "upsert"))
def test_vector_failures_are_explicit_and_retries_reuse_safe_data(setup, monkeypatch, method):
    build, documents, _, runs, provenance, _, vectors = setup
    service = build((document(),))
    original = getattr(vectors, method)

    def fail(*args, **kwargs):
        raise RuntimeError("private vector connection details")

    monkeypatch.setattr(vectors, method, fail)
    with pytest.raises(IngestionExecutionError) as failure:
        service.execute(company="META", as_of=date(2025, 1, 2))
    assert runs.get(failure.value.run_id).status == "failed"
    audit = provenance.get(failure.value.run_id)
    assert audit.processing_config["failed_stage"] == "indexing"
    assert "private vector" not in str(audit)
    assert len(documents.list_documents()) == 1
    monkeypatch.setattr(vectors, method, original)
    assert service.execute(company="META", as_of=date(2025, 1, 2)).indexed_chunk_count == 1
