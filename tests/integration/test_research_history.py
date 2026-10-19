"""Verify real local IR/SEC artifacts without contacting providers or infrastructure."""

import json
import os
from pathlib import Path

import pytest

from scripts.research_inventory import build_inventory
from sentiment_system.adapters.outbound.sources.cached import CachedCorpusDocumentSource
from sentiment_system.domain.research import RESEARCH_TICKERS


def data_root() -> Path:
    configured = os.environ.get("SENTIMENT_DATA_ROOT")
    if not configured:
        pytest.skip("SENTIMENT_DATA_ROOT is not configured")
    root = Path(configured)
    if not (root / "data/sec/history/coverage.json").is_file():
        pytest.skip("historical SEC acquisition has not run")
    return root


@pytest.mark.integration
def test_external_research_history_reconciles_indexes_and_verifies_every_source_hash() -> None:
    inventory = build_inventory(data_root())

    assert {item["ticker"] for item in inventory["companies"]} == set(RESEARCH_TICKERS)
    assert inventory["verification"]["errors"] == []
    assert all(item["sec"]["complete_against_indexes"] for item in inventory["companies"])
    for item in inventory["companies"]:
        assert item["ir"]["documents"] > 0
        assert item["sec"]["by_form"]["10-K"]["downloaded"] >= 5
        assert item["sec"]["by_form"]["10-Q"]["downloaded"] > 0
        assert item["sec"]["by_form"]["8-K:2.02"]["downloaded"] > 0


@pytest.mark.integration
def test_external_curated_transcripts_are_available_through_existing_offline_csv_contract() -> None:
    root = data_root()
    source = CachedCorpusDocumentSource(root)
    for ticker in RESEARCH_TICKERS:
        manifest = json.loads((root / f"data/company_communications/curated/{ticker}/manifest.json").read_text())
        transcripts = [
            document
            for document in source.fetch_documents(company=ticker)
            if document.document_type == "earnings_call_transcript"
        ]
        assert len(transcripts) == len(manifest["documents"])
        assert all(document.raw_content.strip() for document in transcripts)
