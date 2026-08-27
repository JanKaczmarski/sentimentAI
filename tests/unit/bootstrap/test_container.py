"""Tests for source selection in the application composition root."""

import hashlib
import json
from datetime import date

from sentiment_system.bootstrap.container import build_container


def test_build_container_uses_cached_source_when_legacy_demo_setting_exists(tmp_path, monkeypatch) -> None:
    source_path = tmp_path / "data" / "sec" / "earnings_releases" / "AAPL_acc-1.txt"
    source_path.parent.mkdir(parents=True)
    source_path.write_text(
        "<DOCUMENT><TYPE>8-K<TEXT><p>Revenue increased and costs improved.</p></TEXT></DOCUMENT>",
        encoding="utf-8",
    )
    manifest_path = tmp_path / "data" / "sec" / "manifests" / "previous_calendar_quarter_earnings_releases.json"
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_text(
        json.dumps(
            {
                "releases": [
                    {
                        "ticker": "AAPL",
                        "accession_number": "acc-1",
                        "report_date": "2025-01-01",
                        "raw_sha256": hashlib.sha256(source_path.read_bytes()).hexdigest(),
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("EMBEDDING_BACKEND", "mock")
    monkeypatch.setenv("LLM_BACKEND", "deterministic")
    monkeypatch.setenv("SENTIMENT_DATA_ROOT", str(tmp_path))
    monkeypatch.setenv("DEMO_MANIFEST_PATH", str(tmp_path / "missing-demo-manifest.json"))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("QDRANT_URL", raising=False)

    result = build_container().run_batch.execute(as_of=date(2025, 1, 1), company="AAPL")

    assert result.document_count == 1
    assert result.scored_chunk_count > 0
