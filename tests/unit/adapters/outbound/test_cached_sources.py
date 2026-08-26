"""Tests for the local SEC and investor-relations cache adapter."""

import csv
import hashlib
import json
from datetime import date
from pathlib import Path

import pytest

from sentiment_system.adapters.outbound.sources.cached import CachedCorpusDocumentSource, CacheManifestError


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
