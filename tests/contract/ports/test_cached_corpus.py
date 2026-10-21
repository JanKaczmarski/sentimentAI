"""Contract coverage for the final offline corpus document source."""

import hashlib
import json
from dataclasses import replace
from datetime import date
from pathlib import Path

import httpx
import pytest

from sentiment_system.adapters.outbound.sources.cached import CachedCorpusDocumentSource
from sentiment_system.application.ports.document_sources import DocumentSource
from sentiment_system.domain.research import FINAL_CORPUS_VERSION


def test_all_supported_frozen_source_types_preserve_lineage_and_exclusive_scope(tmp_path, sector_bundle, monkeypatch):
    from scripts.acquire_corpus import write_corpus
    from tests.unit.scripts.test_acquire_corpus import _record

    monkeypatch.delenv("SEC_USER_AGENT", raising=False)
    monkeypatch.setattr(httpx.Client, "request", lambda *a, **kw: pytest.fail("cache loading must remain offline"))
    base = _record()
    records = tuple(
        replace(
            base,
            source_id=form,
            form=form,
            form_items=("2.02",) if form == "8-K" else (),
            document_type="earnings_release" if form == "8-K" else form,
            content_group_id=f"META:{form}",
            published_at=date(2025, 1, index),
        )
        for index, form in enumerate(("10-K", "10-Q", "8-K"), start=1)
    )
    records += tuple(
        replace(
            base,
            source="investor_relations",
            source_id=document_type,
            source_type=source_type,
            source_url="https://investor.atmeta.com/communication.txt",
            form=None,
            form_items=(),
            document_type=document_type,
            raw_content=f"Original {document_type}.".encode(),
            cleaned_content=f"Cleaned {document_type}.",
            content_group_id=f"META:{document_type}",
            published_at=date(2025, 1, index),
        )
        for index, (source_type, document_type) in enumerate(
            (
                ("investor_relations_release", "earnings_release"),
                ("investor_relations_transcript", "earnings_call_transcript"),
            ),
            start=4,
        )
    )
    write_corpus(tmp_path, records, sector_review_path=tmp_path / sector_bundle(tmp_path)["sector_review_path"])
    source = CachedCorpusDocumentSource(tmp_path)
    expected = sorted(records, key=lambda record: record.published_at)
    documents = source.fetch_evaluation_documents()
    assert source.fetch_documents(company="meta") == documents
    assert source.fetch_documents(company="AMAT") == ()
    assert [document.document_type for document in documents] == [record.document_type for record in expected]
    for document, record in zip(documents, expected, strict=True):
        assert document.raw_content == record.raw_content.decode()
        assert document.cleaned_content == record.cleaned_content
        assert document.provenance.source_type == record.source_type
        assert document.provenance.form == record.form
        assert document.provenance.form_items == record.form_items
        assert document.original_byte_sha256 == hashlib.sha256(record.raw_content).hexdigest()
        assert document.provenance.evaluation_member
    assert source.fetch_documents(published_after=date(2025, 1, 2), published_before=date(2025, 1, 5)) == documents[2:4]


def test_operational_history_union_deduplicates_revisions_and_keeps_evaluation_frozen(tmp_path, sector_bundle):
    from scripts.acquire_corpus import write_corpus
    from tests.unit.scripts.test_acquire_corpus import _record

    review = tmp_path / sector_bundle(tmp_path)["sector_review_path"]
    write_corpus(tmp_path, (_record(),), sector_review_path=review)
    history = tmp_path / "data/sec/history/META"
    history.mkdir(parents=True)
    records = []
    for index, (accession, published, raw, form) in enumerate(
        (
            ("acc-1", "2025-01-30", b"SEC release", "8-K"),
            ("acc-1", "2025-01-30", b"Changed original source", "8-K"),
            ("older", "2010-01-01", b"Annual report", "10-K"),
            ("amendment", "2025-01-30", b"Not an original filing", "10-K/A"),
        )
    ):
        path = history / f"{index}.txt"
        path.write_bytes(raw)
        records.append(
            {
                "accession_number": accession,
                "form": form,
                "form_items": ["2.02"] if form == "8-K" else [],
                "published_at": published,
                "filed_at": published,
                "raw_path": path.relative_to(tmp_path).as_posix(),
                "raw_sha256": hashlib.sha256(raw).hexdigest(),
                "source_url": "https://www.sec.gov/Archives/filing.txt",
                "retrieved_at": "2026-10-17T00:00:00+00:00",
                "status": "downloaded",
            }
        )
    manifest = history / "manifest.json"
    payload = {"schema_version": 1, "ticker": "META", "documents": records}
    manifest.write_text(json.dumps(payload))
    source = CachedCorpusDocumentSource(tmp_path)
    assert isinstance(source, DocumentSource)
    documents = source.fetch_documents()
    assert len(documents) == 3
    assert len(source.fetch_evaluation_documents()) == 1
    frozen = CachedCorpusDocumentSource(tmp_path, scope="frozen")
    assert frozen.fetch_documents() == source.fetch_evaluation_documents()
    assert frozen.fetch_documents(company="AMAT") == ()
    assert frozen.fetch_documents(published_before=date(2025, 1, 30)) == ()
    assert frozen.manifest_sha256
    assert next(d for d in documents if d.original_byte_sha256 == hashlib.sha256(b"SEC release").hexdigest()).provenance
    assert len(source.fetch_documents(published_before=date(2020, 1, 1))) == 1
    assert len(source.fetch_documents(published_after=date(2020, 1, 1))) == 2
    assert len({d.source_revision_id for d in documents}) == 3
    payload["documents"].reverse()
    manifest.write_text(json.dumps(payload))
    assert CachedCorpusDocumentSource(tmp_path).fetch_documents() == documents


def test_frozen_source_fails_instead_of_falling_back_when_manifest_is_absent(tmp_path):
    from sentiment_system.adapters.outbound.sources.cached import CacheManifestError

    with pytest.raises(CacheManifestError, match="frozen corpus"):
        CachedCorpusDocumentSource(tmp_path, scope="frozen")


def test_final_cached_corpus_implements_document_source_with_exclusive_filters(tmp_path: Path, sector_bundle) -> None:
    corpus = tmp_path / "data" / "corpora" / FINAL_CORPUS_VERSION
    raw_path = corpus / "raw" / "sec" / "META" / "acc-1.txt"
    cleaned_path = corpus / "cleaned" / "sec" / "META" / "acc-1.txt"
    raw_path.parent.mkdir(parents=True)
    cleaned_path.parent.mkdir(parents=True)
    raw_path.write_text("Quarterly filing.", encoding="utf-8")
    cleaned_path.write_text("Quarterly filing.", encoding="utf-8")
    (corpus / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": 2,
                "manifest_version": FINAL_CORPUS_VERSION,
                "corpus_window": {"start": "2020-01-30", "end": "2025-01-30"},
                "development_ends": "2023-01-30",
                "held_out_starts": "2025-01-30",
                **sector_bundle(corpus),
                "companies": _companies(),
                "records": [
                    {
                        "record_id": "sec:acc-1",
                        "company": "META",
                        "source": "sec",
                        "source_type": "sec_filing",
                        "source_id": "acc-1",
                        "document_type": "10-Q",
                        "form": "10-Q",
                        "form_items": [],
                        "published_at": "2025-01-30",
                        "retrieved_at": "2025-01-31T12:00:00+00:00",
                        "source_url": "https://www.sec.gov/Archives/edgar/data/320193/example.txt",
                        "raw_path": "raw/sec/META/acc-1.txt",
                        "raw_sha256": hashlib.sha256(raw_path.read_bytes()).hexdigest(),
                        "cleaned_path": "cleaned/sec/META/acc-1.txt",
                        "cleaned_sha256": hashlib.sha256(cleaned_path.read_bytes()).hexdigest(),
                        "parser_version": "source-cleaning-v1",
                        "content_group_id": "META:10-Q:2024-12-31",
                        "canonical_for_scoring": True,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    source = CachedCorpusDocumentSource(tmp_path)

    assert isinstance(source, DocumentSource)
    assert len(source.fetch_documents(company="meta")) == 1
    assert source.fetch_documents(published_before=date(2025, 1, 30)) == ()
    assert source.fetch_documents(published_after=date(2025, 1, 30)) == ()


def _companies() -> list[dict[str, object]]:
    return [
        {
            "ticker": ticker,
            "evaluation_member": True,
            "sector": sector,
            "benchmark": benchmark,
            "sector_source_url": f"https://example.com/{ticker}",
            "sector_retrieved_at": "2026-10-18T00:00:00+00:00",
        }
        for ticker, sector, benchmark in (
            ("META", "Communication Services", "XLC"),
            ("CRM", "Information Technology", "XLK"),
            ("V", "Financials", "XLF"),
            ("DIS", "Communication Services", "XLC"),
            ("WHR", "Consumer Discretionary", "XLY"),
            ("T", "Communication Services", "XLC"),
        )
    ]
