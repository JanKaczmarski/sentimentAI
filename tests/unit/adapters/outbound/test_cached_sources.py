"""Tests for the local SEC and investor-relations cache adapter."""

import csv
import hashlib
import json
from datetime import date
from pathlib import Path

import pytest

from sentiment_system.adapters.outbound.sources.cached import CachedCorpusDocumentSource, CacheManifestError
from sentiment_system.domain.research import FINAL_CORPUS_VERSION


def test_cached_source_loads_sec_records_and_filters_deterministically(tmp_path: Path) -> None:
    sec = tmp_path / "data" / "sec"
    (sec / "manifests").mkdir(parents=True)
    (sec / "earnings_releases").mkdir()
    content = "Revenue increased."
    (sec / "earnings_releases" / "AAPL_acc-1.txt").write_text(content, encoding="utf-8")
    (sec / "manifests" / "previous_calendar_quarter_earnings_releases.json").write_text(
        json.dumps(
            {
                "manifest_version": "sec-v1",
                "releases": [
                    {
                        "ticker": "AAPL",
                        "accession_number": "acc-1",
                        "filed_at": "2026-05-01",
                        "report_date": "2026-03-31",
                        "source_url": "https://sec.example/release",
                        "document_type": "earnings_release",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    documents = CachedCorpusDocumentSource(tmp_path).fetch_documents(company="AAPL", published_after=date(2026, 1, 1))

    assert len(documents) == 1
    assert documents[0].source == "sec"
    assert documents[0].source_id == "acc-1"
    assert documents[0].raw_content == content
    assert documents[0].manifest_version == "sec-v1"
    assert CachedCorpusDocumentSource(tmp_path).fetch_documents() == documents
    assert CachedCorpusDocumentSource(tmp_path).fetch_evaluation_documents() == ()


def test_cached_source_rejects_sec_hash_mismatch(tmp_path: Path) -> None:
    sec = tmp_path / "data" / "sec"
    (sec / "manifests").mkdir(parents=True)
    (sec / "earnings_releases").mkdir()
    document = sec / "earnings_releases" / "AAPL_acc-1.txt"
    document.write_text("Revenue increased.", encoding="utf-8")
    (sec / "manifests" / "previous_calendar_quarter_earnings_releases.json").write_text(
        json.dumps(
            {
                "manifest_version": "sec-v1",
                "releases": [
                    {
                        "ticker": "AAPL",
                        "accession_number": "acc-1",
                        "filed_at": "2026-05-01",
                        "report_date": "2026-03-31",
                        "source_url": "https://sec.example/release",
                        "raw_sha256": "0" * 64,
                        "document_type": "earnings_release",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(CacheManifestError, match="checksum mismatch"):
        CachedCorpusDocumentSource(tmp_path)


def test_cached_source_loads_curated_ir_records_and_rejects_hash_mismatch(tmp_path: Path) -> None:
    curated = tmp_path / "data" / "company_communications" / "curated" / "AMAT"
    curated.mkdir(parents=True)
    document = curated / "AMAT__FY2026-Q1__2026-02-12__investor_relations__remarks.txt"
    document.write_text("Prepared remarks.", encoding="utf-8")
    with (curated / "manifest.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=("canonical_filename", "ticker", "published_at", "source", "document_type", "sha256"),
        )
        writer.writeheader()
        writer.writerow(
            {
                "canonical_filename": document.name,
                "ticker": "AMAT",
                "published_at": "2026-02-12",
                "source": "investor_relations",
                "document_type": "remarks",
                "sha256": hashlib.sha256(document.read_bytes()).hexdigest(),
            }
        )

    documents = CachedCorpusDocumentSource(tmp_path).fetch_documents(company="AMAT")
    assert documents[0].manifest_version == "ir-v1"
    assert documents[0].raw_content == "Prepared remarks."

    document.write_text("Changed.", encoding="utf-8")
    with pytest.raises(CacheManifestError, match="checksum mismatch"):
        CachedCorpusDocumentSource(tmp_path)


def test_cached_source_loads_final_manifest_records_with_auditable_release_group(tmp_path: Path, sector_bundle) -> None:
    corpus = tmp_path / "data" / "corpora" / FINAL_CORPUS_VERSION
    raw_sec = corpus / "raw" / "sec" / "META" / "acc-1.txt"
    cleaned_sec = corpus / "cleaned" / "sec" / "META" / "acc-1.txt"
    raw_ir = corpus / "raw" / "investor_relations" / "META" / "release.html"
    cleaned_ir = corpus / "cleaned" / "investor_relations" / "META" / "release.txt"
    for path, content in (
        (raw_sec, "<DOCUMENT>SEC release</DOCUMENT>"),
        (cleaned_sec, "SEC release"),
        (raw_ir, "<html><body>IR release</body></html>"),
        (cleaned_ir, "IR release"),
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def record(
        *,
        source: str,
        source_type: str,
        source_id: str,
        raw_path: Path,
        cleaned_path: Path,
        canonical_for_scoring: bool,
    ) -> dict[str, object]:
        return {
            "record_id": f"{source}:{source_id}",
            "company": "META",
            "source": source,
            "source_type": source_type,
            "source_id": source_id,
            "document_type": "earnings_release",
            "form": "8-K" if source == "sec" else None,
            "form_items": ["2.02"] if source == "sec" else [],
            "published_at": "2025-01-30",
            "retrieved_at": "2025-01-31T12:00:00+00:00",
            "source_url": (
                "https://www.sec.gov/Archives/edgar/data/1326801/example.txt"
                if source == "sec"
                else "https://investor.atmeta.com/example.html"
            ),
            "raw_path": raw_path.relative_to(corpus).as_posix(),
            "raw_sha256": hashlib.sha256(raw_path.read_bytes()).hexdigest(),
            "cleaned_path": cleaned_path.relative_to(corpus).as_posix(),
            "cleaned_sha256": hashlib.sha256(cleaned_path.read_bytes()).hexdigest(),
            "parser_version": "source-cleaning-v1",
            "content_group_id": "META:2025-Q1",
            "canonical_for_scoring": canonical_for_scoring,
        }

    (corpus / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": 2,
                "manifest_version": FINAL_CORPUS_VERSION,
                "corpus_window": {"start": "2020-01-30", "end": "2025-01-30"},
                "development_ends": "2023-01-30",
                "held_out_starts": "2025-01-30",
                **sector_bundle(corpus),
                "companies": _final_companies(),
                "records": [
                    record(
                        source="sec",
                        source_type="sec_filing",
                        source_id="acc-1",
                        raw_path=raw_sec,
                        cleaned_path=cleaned_sec,
                        canonical_for_scoring=True,
                    ),
                    record(
                        source="investor_relations",
                        source_type="investor_relations_release",
                        source_id="apple-q1-2025",
                        raw_path=raw_ir,
                        cleaned_path=cleaned_ir,
                        canonical_for_scoring=False,
                    ),
                ],
            }
        ),
        encoding="utf-8",
    )

    documents = CachedCorpusDocumentSource(tmp_path).fetch_documents(company="meta")

    assert [document.source for document in documents] == ["investor_relations", "sec"]
    assert [document.provenance.canonical_for_scoring for document in documents] == [False, True]
    assert {document.provenance.content_group_id for document in documents} == {"META:2025-Q1"}
    assert documents[0].raw_content == "<html><body>IR release</body></html>"
    assert documents[0].cleaned_content == "IR release"


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"raw_path": "../outside.txt"}, "safe relative path"),
        ({"raw_sha256": None}, "raw_sha256 is required"),
        ({"form": "6-K"}, "SEC form is unsupported"),
    ],
)
def test_cached_source_rejects_unsafe_or_unsupported_final_manifest_records(
    tmp_path: Path, overrides: dict[str, object], message: str, sector_bundle
) -> None:
    corpus = tmp_path / "data" / "corpora" / FINAL_CORPUS_VERSION
    corpus.mkdir(parents=True)
    record: dict[str, object] = {
        "record_id": "sec:acc-1",
        "company": "META",
        "source": "sec",
        "source_type": "sec_filing",
        "source_id": "acc-1",
        "document_type": "earnings_release",
        "form": "8-K",
        "form_items": ["2.02"],
        "published_at": "2025-01-30",
        "retrieved_at": "2025-01-31T12:00:00+00:00",
        "source_url": "https://www.sec.gov/Archives/edgar/data/320193/example.txt",
        "raw_path": "raw/sec/META/acc-1.txt",
        "raw_sha256": "a" * 64,
        "cleaned_path": "cleaned/sec/META/acc-1.txt",
        "cleaned_sha256": "b" * 64,
        "parser_version": "source-cleaning-v1",
        "content_group_id": "META:2025-Q1",
        "canonical_for_scoring": True,
    }
    record.update(overrides)
    (corpus / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": 2,
                "manifest_version": FINAL_CORPUS_VERSION,
                "corpus_window": {"start": "2020-01-30", "end": "2025-01-30"},
                "development_ends": "2023-01-30",
                "held_out_starts": "2025-01-30",
                **sector_bundle(corpus),
                "companies": _final_companies(),
                "records": [record],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(CacheManifestError, match=message):
        CachedCorpusDocumentSource(tmp_path)


def test_cached_source_rejects_malformed_final_manifest(tmp_path: Path) -> None:
    corpus = tmp_path / "data" / "corpora" / FINAL_CORPUS_VERSION
    corpus.mkdir(parents=True)
    (corpus / "manifest.json").write_text("{", encoding="utf-8")

    with pytest.raises(CacheManifestError, match="cannot read cache manifest"):
        CachedCorpusDocumentSource(tmp_path)


def _final_companies() -> list[dict[str, object]]:
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
