"""Freeze only verified source/price bytes; reruns never revise research evidence."""

import hashlib
import inspect
import json
from datetime import date, datetime, timezone
from pathlib import Path

import httpx
import pytest

from scripts.acquire_corpus import AcquiredCorpusRecord, publish_cleaned_corpus, write_corpus
from scripts.download_nasdaq_historical import fetch_historical, write_snapshot
from scripts.freeze_evaluation_manifest import freeze_evaluation_manifest, verify_evaluation_manifest
from sentiment_system.adapters.outbound.market_data.evaluation_bundle import load_evaluation_scope
from sentiment_system.application.use_cases.ingest_documents import _clean_content
from sentiment_system.application.use_cases.sec_content import select_sec_content
from sentiment_system.domain.research import RESEARCH_SELECTION_VERSION, RESEARCH_TICKERS


@pytest.fixture
def evaluation_inputs(tmp_path, sector_bundle):
    review_path = tmp_path / sector_bundle(tmp_path)["sector_review_path"]
    records = tuple(
        AcquiredCorpusRecord(
            company=ticker,
            source="sec",
            source_type="sec_filing",
            source_id=f"acc-{ticker}",
            document_type="10-K",
            form="10-K",
            form_items=(),
            published_at=date(2025, 1, 6 if ticker == "T" else 3),
            retrieved_at=datetime(2025, 1, 7, tzinfo=timezone.utc),
            source_url=f"https://www.sec.gov/Archives/edgar/data/1/{ticker}.txt",
            raw_content=b"<DOCUMENT><TYPE>10-K\n<TEXT><p>Annual financial results.</p></TEXT></DOCUMENT>",
            cleaned_content="Previous cleaner output.",
            parser_version="source-cleaning-v1",
            content_group_id=f"{ticker}:annual",
            canonical_for_scoring=True,
            raw_suffix=".txt",
        )
        for ticker in RESEARCH_TICKERS
    )
    previous = write_corpus(
        tmp_path, records, sector_review_path=review_path, manifest_version=RESEARCH_SELECTION_VERSION
    )
    old = json.loads((previous / "manifest.json").read_bytes())
    selection = {
        "manifest_version": RESEARCH_SELECTION_VERSION,
        "evaluation_universe": list(RESEARCH_TICKERS),
        "inputs": [],
        **{key: old[key] for key in ("corpus_window", "development_ends", "held_out_starts")},
        "records": [
            {
                **{
                    key: row[key]
                    for key in ("company", "source", "source_id", "document_type", "published_at", "raw_sha256")
                },
                "raw_path": (previous / row["raw_path"]).relative_to(tmp_path).as_posix(),
            }
            for row in old["records"]
        ],
    }
    path = tmp_path / f"data/research_selection/{RESEARCH_SELECTION_VERSION}.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(selection))
    extraction = tmp_path / "data/extraction_reviews/test/review.json"
    extraction.parent.mkdir(parents=True)
    extraction.write_text(
        json.dumps(
            {
                "parser_version": "sec-form-aware-v2",
                "errors": [],
                "records": [],
                "implementation_sha256": {
                    "sec_selector": hashlib.sha256(Path(inspect.getfile(select_sec_content)).read_bytes()).hexdigest(),
                    "text_cleaner": hashlib.sha256(Path(inspect.getfile(_clean_content)).read_bytes()).hexdigest(),
                },
            }
        )
    )
    findings = extraction.parent / "findings-final.md"
    findings.write_text("Synthetic bounded review.")
    corpus = publish_cleaned_corpus(tmp_path, selection_path=path, review_paths=(extraction,), findings_path=findings)
    market = tmp_path / "data/market_prices/test-prices"
    market.parent.mkdir()

    def serve(request):
        symbol = request.url.path.split("/")[-2]
        return httpx.Response(
            200,
            json={
                "status": {"rCode": 200},
                "data": {
                    "symbol": symbol,
                    "totalRecords": 4,
                    "tradesTable": {
                        "rows": [
                            {
                                "date": day,
                                "open": "100",
                                "high": "110",
                                "low": "90",
                                "close": str(100 + index),
                                "volume": "1000",
                            }
                            for index, day in enumerate(("01/03/2025", "01/06/2025", "01/07/2025", "01/08/2025"))
                        ]
                    },
                },
            },
        )

    with httpx.Client(transport=httpx.MockTransport(serve)) as client:
        series = [
            fetch_historical(
                client,
                ticker,
                start=date(2020, 1, 6),
                end=date(2025, 1, 8),
                asset_class="stocks" if ticker in RESEARCH_TICKERS else "etf",
                retrieved_at=datetime(2025, 1, 9, tzinfo=timezone.utc),
            )
            for ticker in (*RESEARCH_TICKERS, "XLC", "XLK", "XLF", "XLY", "SPY")
        ]
    write_snapshot(series, output_dir=market)
    return corpus, market


def test_freeze_reconciles_source_membership_and_keeps_all_incomplete_horizons(tmp_path, evaluation_inputs):
    corpus, market = evaluation_inputs
    output = freeze_evaluation_manifest(tmp_path, market_snapshot=market.name)
    manifest = json.loads((output / "manifest.json").read_bytes())
    coverage = json.loads((output / "coverage.json").read_bytes())
    reconciliation = json.loads((output / "reconciliation.json").read_bytes())
    assert manifest["corpus"]["sha256"] == hashlib.sha256((corpus / "manifest.json").read_bytes()).hexdigest()
    assert manifest["company_benchmarks"] == {
        "META": "XLC",
        "CRM": "XLK",
        "V": "XLF",
        "DIS": "XLC",
        "WHR": "XLY",
        "T": "XLC",
    }
    assert reconciliation["source_records"] == 6
    assert len(coverage["outcomes"]) == 30
    assert sum(row["reason"] is None for row in coverage["outcomes"]) == 6
    assert freeze_evaluation_manifest(tmp_path, market_snapshot=market.name) == output
    assert verify_evaluation_manifest(tmp_path) == output
    scope = load_evaluation_scope(tmp_path)
    assert scope.corpus_manifest_version == corpus.name
    assert scope.market_snapshot_version == market.name


@pytest.mark.parametrize(
    "target", ["csv", "response", "corpus", "predecessor", "selection", "coverage", "extra", "tree_extra", "symlink"]
)
def test_frozen_bundle_rejects_corruption_and_unrecorded_artifacts(tmp_path, evaluation_inputs, target):
    corpus, market = evaluation_inputs
    output = freeze_evaluation_manifest(tmp_path, market_snapshot=market.name)
    manifest = json.loads((corpus / "manifest.json").read_bytes())
    paths = {
        "csv": market / "META.csv",
        "response": market / "raw/META.json",
        "corpus": corpus / manifest["records"][0]["cleaned_path"],
        "predecessor": tmp_path / f"data/corpora/{RESEARCH_SELECTION_VERSION}/manifest.json",
        "selection": tmp_path / f"data/research_selection/{RESEARCH_SELECTION_VERSION}.json",
        "coverage": output / "coverage.json",
        "extra": output / "unexpected.txt",
        "tree_extra": market / "unexpected.txt",
    }
    if target == "symlink":
        path = market / "raw/META.json"
        content = path.read_bytes()
        path.unlink()
        alternate = tmp_path / "alternate.json"
        alternate.write_bytes(content)
        path.symlink_to(alternate)
    else:
        paths[target].write_bytes(b"changed")
    with pytest.raises(ValueError):
        load_evaluation_scope(tmp_path)
    with pytest.raises(ValueError):
        verify_evaluation_manifest(tmp_path)


def test_rerun_rejects_different_requested_market_snapshot(tmp_path, evaluation_inputs):
    _, market = evaluation_inputs
    freeze_evaluation_manifest(tmp_path, market_snapshot=market.name)
    with pytest.raises(ValueError, match="requested"):
        freeze_evaluation_manifest(tmp_path, market_snapshot="another-snapshot")
