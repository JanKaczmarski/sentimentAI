"""Tests for bounded supervisor-demo manifest loading."""

import hashlib
import json
from datetime import date

import pytest

from sentiment_system.adapters.outbound.sources.demo_manifest import DemoManifestDocumentSource, DemoManifestError


def test_demo_manifest_loads_hashed_sec_and_ir_records_in_deterministic_order(tmp_path) -> None:
    sec_path = tmp_path / "sec.txt"
    ir_path = tmp_path / "ir.txt"
    sec_path.write_text("SEC communication.", encoding="utf-8")
    ir_path.write_text("Investor relations communication.", encoding="utf-8")
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "manifest_version": "demo-v1",
                "cutoff_date": "2025-02-01",
                "processing_config_version": "processing-v2",
                "records": [
                    {
                        "document_id": "ir:1",
                        "source_id": "ir-1",
                        "company": "AAPL",
                        "source": "investor_relations",
                        "published_at": "2025-01-31",
                        "document_type": "earnings_release",
                        "raw_path": "ir.txt",
                        "raw_sha256": hashlib.sha256(ir_path.read_bytes()).hexdigest(),
                        "cleaned_content_version": "processing-v2",
                    },
                    {
                        "document_id": "sec:1",
                        "source_id": "sec-1",
                        "company": "AAPL",
                        "source": "sec",
                        "published_at": "2025-01-30",
                        "document_type": "8-K",
                        "raw_path": "sec.txt",
                        "raw_sha256": hashlib.sha256(sec_path.read_bytes()).hexdigest(),
                        "cleaned_content_version": "processing-v2",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    source = DemoManifestDocumentSource(root=tmp_path, manifest_path=manifest_path)

    documents = source.fetch_documents()

    assert [document.source_id for document in documents] == ["sec-1", "ir-1"]
    assert documents[0].published_at == date(2025, 1, 30)
    assert {document.source for document in documents} == {"sec", "investor_relations"}


def test_demo_manifest_rejects_checksum_mismatch(tmp_path) -> None:
    source_path = tmp_path / "source.txt"
    source_path.write_text("content", encoding="utf-8")
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "manifest_version": "demo-v1",
                "cutoff_date": "2025-02-01",
                "records": [
                    {
                        "document_id": "sec:1",
                        "source_id": "sec-1",
                        "company": "AAPL",
                        "source": "sec",
                        "published_at": "2025-01-30",
                        "document_type": "8-K",
                        "raw_path": "source.txt",
                        "raw_sha256": "0" * 64,
                        "cleaned_content_version": "processing-v2",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(DemoManifestError, match="checksum mismatch"):
        DemoManifestDocumentSource(root=tmp_path, manifest_path=manifest_path)
