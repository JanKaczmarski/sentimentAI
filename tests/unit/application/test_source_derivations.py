"""Original sources outlive cleaning and chunking configurations."""

from dataclasses import replace
from datetime import date
from hashlib import sha256

import pytest

from sentiment_system.adapters.outbound.persistence.in_memory import InMemoryChunkRepository, InMemoryDocumentRepository
from sentiment_system.adapters.outbound.sources.fixtures import FixtureDocumentSource
from sentiment_system.application.use_cases.ingest_documents import IngestDocuments
from sentiment_system.domain.documents import SourceArtifact, SourceDocument


def test_pdf_original_hash_survives_normalization_and_derivations_are_versioned():
    original_hash = sha256(b"%PDF original bytes, not extracted text").hexdigest()
    source = SourceDocument(
        document_id="legacy-call",
        source_id="call.pdf",
        company="META",
        source="investor_relations",
        published_at=date(2025, 1, 30),
        document_type="earnings_call_transcript",
        raw_content="One sentence. Two sentences. Three sentences. Four sentences.",
        cleaned_content="",
        artifact=SourceArtifact(sha256=original_hash, path="calls/call.pdf"),
    )
    documents, chunks = InMemoryDocumentRepository(), InMemoryChunkRepository()

    def ingest(document, config):
        return IngestDocuments(
            FixtureDocumentSource((document,)),
            documents,
            chunks,
            processing_config_version=config,
            token_counter=lambda text: len(text.split()),
        ).run()

    first = ingest(source, "chunks-v1")
    assert first.documents[0].original_byte_sha256 == original_hash
    assert first.documents[0].source_revision_id == source.source_revision_id
    assert first == ingest(source, "chunks-v1")
    second = ingest(source, "chunks-v2")
    assert second.documents == first.documents
    assert {c.chunk_id for c in first.chunks}.isdisjoint(c.chunk_id for c in second.chunks)
    changed = ingest(replace(source, raw_content="Changed words. New guidance."), "chunks-v1")
    assert changed.documents[0].source_revision_id == first.documents[0].source_revision_id
    assert changed.documents[0].document_id != first.documents[0].document_id
    assert documents.get(first.documents[0].document_id) == first.documents[0]
    assert all(chunks.get(c.chunk_id) == c for c in (*first.chunks, *second.chunks))
    with pytest.raises(ValueError, match="immutable"):
        chunks.save(replace(first.chunks[0], content="Overwritten history."))


def test_different_bytes_with_identical_extracted_text_are_distinct_revisions():
    a = SourceDocument(
        "a",
        "call.pdf",
        "META",
        "investor_relations",
        date(2025, 1, 30),
        "earnings_call_transcript",
        "Same text.",
        "Same text.",
        artifact=SourceArtifact(sha256="a" * 64, path="a.pdf"),
    )
    b = replace(a, artifact=SourceArtifact(sha256="b" * 64, path="b.pdf"))
    assert a.source_revision_id != b.source_revision_id
    assert a.derivation_id != b.derivation_id
