"""Operational history is a deterministic superset, never an evaluation selection."""

import hashlib
import json
from datetime import date

import pytest

from sentiment_system.adapters.outbound.persistence.in_memory import InMemoryChunkRepository, InMemoryDocumentRepository
from sentiment_system.adapters.outbound.sources.cached import CachedCorpusDocumentSource
from sentiment_system.application.use_cases.ingest_documents import IngestDocuments


def test_history_uses_publication_dates_original_hashes_and_preserves_revisions(tmp_path):
    root = tmp_path / "data/sec/history/META"
    root.mkdir(parents=True)
    records = []
    for index, text in enumerate(("Annual results.", "Revised annual results.")):
        raw = f"<html><p>{text}</p></html>".encode()
        path = root / f"revision-{index}.html"
        path.write_bytes(raw)
        records.append(
            {
                "accession_number": "same-accession",
                "form": "10-K",
                "form_items": [],
                "filed_at": "2020-02-20",
                "published_at": "2020-02-20",
                "report_date": "2019-12-31",
                "raw_path": path.relative_to(tmp_path).as_posix(),
                "raw_sha256": hashlib.sha256(raw).hexdigest(),
                "source_url": "https://www.sec.gov/Archives/example.html",
                "status": "downloaded",
                "retrieved_at": "2026-10-17T00:00:00+00:00",
            }
        )
    manifest = root / "manifest.json"
    payload = {"schema_version": 1, "ticker": "META", "documents": [*records, records[0]]}
    manifest.write_text(json.dumps(payload))
    source = CachedCorpusDocumentSource(tmp_path)
    documents = source.fetch_documents(company="META")
    assert len(documents) == 2
    assert all(d.published_at == date(2020, 2, 20) for d in documents)
    assert {d.original_byte_sha256 for d in documents} == {r["raw_sha256"] for r in records}
    assert len({d.document_id for d in documents}) == 2
    assert source.fetch_evaluation_documents() == ()
    payload["documents"].reverse()
    manifest.write_text(json.dumps(payload))
    assert CachedCorpusDocumentSource(tmp_path).fetch_documents() == documents
    (root / "revision-0.html").write_text("corrupt")
    with pytest.raises(ValueError, match="checksum"):
        CachedCorpusDocumentSource(tmp_path)


def test_non_earnings_8k_ingests_main_disclosure_without_earnings_exhibits(tmp_path):
    folder = tmp_path / "data/sec/history/T"
    folder.mkdir(parents=True)
    raw = (
        b"<DOCUMENT><TYPE>8-K\n<TEXT><p>Director appointment disclosure.</p></TEXT></DOCUMENT>"
        b"<DOCUMENT><TYPE>EX-99.1\n<TEXT><p>Unrelated attached presentation.</p></TEXT></DOCUMENT>"
    )
    (folder / "filing.txt").write_bytes(raw)
    (folder / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "ticker": "T",
                "documents": [
                    {
                        "accession_number": "non-earnings",
                        "form": "8-K",
                        "form_items": ["5.02"],
                        "published_at": "2026-10-16",
                        "filed_at": "2026-10-16",
                        "status": "existing",
                        "raw_path": "data/sec/history/T/filing.txt",
                        "raw_sha256": hashlib.sha256(raw).hexdigest(),
                        "source_url": "https://www.sec.gov/Archives/filing.txt",
                        "retrieved_at": "2026-10-17T00:00:00+00:00",
                    }
                ],
            }
        )
    )
    source = CachedCorpusDocumentSource(tmp_path)
    result = IngestDocuments(
        source,
        InMemoryDocumentRepository(),
        InMemoryChunkRepository(),
        processing_config_version="processing-v1",
        token_counter=lambda text: len(text.split()),
    ).run()
    assert result.documents[0].cleaned_content == "Director appointment disclosure."
    assert result.documents[0].original_byte_sha256 == hashlib.sha256(raw).hexdigest()
    assert source.fetch_evaluation_documents() == ()


def test_quarterly_snapshot_uses_filing_date_not_report_period(tmp_path):
    sec = tmp_path / "data/sec"
    (sec / "manifests").mkdir(parents=True)
    (sec / "earnings_releases").mkdir()
    (sec / "earnings_releases/META_acc.txt").write_text("Published release.")
    (sec / "manifests/previous_calendar_quarter_earnings_releases.json").write_text(
        json.dumps(
            {
                "releases": [
                    {"ticker": "META", "accession_number": "acc", "filed_at": "2026-05-01", "report_date": "2026-03-31"}
                ],
            }
        )
    )
    document = CachedCorpusDocumentSource(tmp_path).fetch_documents()[0]
    assert document.published_at == date(2026, 5, 1)
    assert document.original_byte_sha256 == hashlib.sha256(b"Published release.").hexdigest()
