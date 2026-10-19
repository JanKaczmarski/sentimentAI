"""Tests for auditable source-document and chunk domain entities."""

from dataclasses import FrozenInstanceError
from datetime import date, datetime, timezone

import pytest

from sentiment_system.domain.documents import DocumentChunk, SourceDocument, SourceProvenance


def _document(**overrides: object) -> SourceDocument:
    values: dict[str, object] = {
        "document_id": "document-1",
        "source_id": "fixture-1",
        "company": "AAPL",
        "source": "fixture",
        "published_at": date(2025, 1, 30),
        "document_type": "company_communication",
        "raw_content": "Raw source text.",
        "cleaned_content": "Cleaned source text.",
    }
    values.update(overrides)
    return SourceDocument(**values)


def test_source_document_preserves_distinct_raw_and_cleaned_content() -> None:
    document = _document(raw_content="Raw source text.", cleaned_content="Cleaned source text.")

    assert document.raw_content == "Raw source text."
    assert document.cleaned_content == "Cleaned source text."
    with pytest.raises(FrozenInstanceError):
        document.raw_content = "Modified source text."  # type: ignore[misc]


def test_source_document_preserves_immutable_manifest_provenance() -> None:
    provenance = SourceProvenance(
        manifest_record_id="sec:acc-1",
        source_url="https://www.sec.gov/Archives/edgar/data/320193/example.txt",
        retrieved_at=datetime(2025, 1, 31, 12, tzinfo=timezone.utc),
        raw_path="raw/sec/AAPL/example.txt",
        raw_sha256="a" * 64,
        cleaned_path="cleaned/sec/AAPL/example.txt",
        cleaned_sha256="b" * 64,
        parser_version="sec-filing-v1",
        source_type="sec_filing",
        form="8-K",
        form_items=("2.02",),
        content_group_id="AAPL:2025-Q1",
        canonical_for_scoring=True,
        evaluation_member=True,
        sector="Information Technology",
        sector_source_url="https://www.nasdaq.com/market-activity/stocks/aapl",
        sector_retrieved_at=datetime(2025, 1, 31, 12, tzinfo=timezone.utc),
    )

    document = _document(manifest_version="thesis-v1-2025-09-24", provenance=provenance)

    assert document.provenance == provenance
    assert document.provenance.content_group_id == "AAPL:2025-Q1"
    assert document.provenance.canonical_for_scoring is True


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("document_id", "", "document_id is required"),
        ("source_id", "   ", "source_id is required"),
        ("company", "", "company is required"),
        ("source", "", "source is required"),
        ("published_at", None, "published_at must be a date"),
        ("document_type", "", "document_type is required"),
        ("raw_content", "   ", "raw_content is required"),
        ("cleaned_content", None, "cleaned_content must be a string"),
    ],
)
def test_source_document_rejects_missing_or_invalid_metadata(field: str, value: object, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        _document(**{field: value})


def test_document_chunk_preserves_document_lineage_and_ordinal() -> None:
    chunk = DocumentChunk(
        chunk_id="document-1-0",
        document_id="document-1",
        ordinal=0,
        content="Material source excerpt.",
    )

    assert chunk.document_id == "document-1"
    assert chunk.ordinal == 0
    assert chunk.content == "Material source excerpt."


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("chunk_id", "", "chunk_id is required"),
        ("document_id", "", "document_id is required"),
        ("ordinal", -1, "ordinal must be a non-negative integer"),
        ("ordinal", True, "ordinal must be a non-negative integer"),
        ("ordinal", 0.5, "ordinal must be a non-negative integer"),
        ("content", "   ", "content is required"),
    ],
)
def test_document_chunk_rejects_invalid_lineage_or_content(field: str, value: object, message: str) -> None:
    values: dict[str, object] = {
        "chunk_id": "document-1-0",
        "document_id": "document-1",
        "ordinal": 0,
        "content": "Material source excerpt.",
    }
    values[field] = value

    with pytest.raises(ValueError, match=message):
        DocumentChunk(**values)
