"""Actual downloads, reviewed evidence, and immutable local selection contracts."""

import hashlib
import json
from pathlib import Path

import httpx
import pytest

from scripts import freeze_corpus_selection
from scripts.download_company_sectors import download_profiles
from sentiment_system.adapters.outbound.sources.sector_metadata import load_sector_review
from sentiment_system.domain.research import RESEARCH_TICKERS


def test_sector_downloader_preserves_actual_responses_and_does_not_invent_review(tmp_path: Path) -> None:
    def serve(request: httpx.Request) -> httpx.Response:
        ticker = request.url.path.split("/")[2].upper()
        return httpx.Response(200, text=f"<main>{ticker}<div>Sector</div><div>Financials</div></main>")

    with httpx.Client(transport=httpx.MockTransport(serve)) as client:
        output = download_profiles(tmp_path, "test", client)
    payload = json.loads((output / "downloads.json").read_text())

    assert {item["ticker"] for item in payload["downloads"]} == set(RESEARCH_TICKERS)
    for item in payload["downloads"]:
        assert item["raw_sha256"] == hashlib.sha256((tmp_path / item["raw_path"]).read_bytes()).hexdigest()
        assert item["retrieved_at"].endswith("+00:00")
    assert not (output / "reviewed.json").exists()
    with pytest.raises(ValueError, match="overwrite"):
        with httpx.Client(transport=httpx.MockTransport(serve)) as client:
            download_profiles(tmp_path, "test", client)


@pytest.mark.parametrize("status", [302, 403])
def test_sector_downloader_does_not_publish_failed_or_redirected_snapshots(tmp_path: Path, status: int) -> None:
    with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(status))) as client:
        with pytest.raises((ValueError, httpx.HTTPStatusError)):
            download_profiles(tmp_path, "failed", client)
    assert not (tmp_path / "data/company_sectors/failed").exists()


def test_review_requires_original_download_hashes_and_supported_quote(tmp_path: Path, sector_bundle) -> None:
    metadata = sector_bundle(tmp_path)
    companies, _ = load_sector_review(tmp_path, metadata["sector_review_path"])
    assert len(companies) == 6

    (tmp_path / "sector_evidence/META.html").write_text("Changed")
    with pytest.raises(ValueError, match="checksum"):
        load_sector_review(tmp_path, metadata["sector_review_path"])


def test_review_cannot_claim_a_sector_not_reported_by_the_source(tmp_path: Path, sector_bundle) -> None:
    metadata = sector_bundle(tmp_path)
    path = tmp_path / metadata["sector_review_path"]
    review = json.loads(path.read_text())
    review["companies"][0]["evidence_quote"] = "Sector\nFinancials"
    path.write_text(json.dumps(review))
    with pytest.raises(ValueError, match="quote"):
        load_sector_review(tmp_path, metadata["sector_review_path"])


def test_frozen_selection_uses_eligible_dates_and_rejects_changed_inputs(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(freeze_corpus_selection, "RESEARCH_TICKERS", ("META",))
    checksum = hashlib.sha256(b"source").hexdigest()
    (tmp_path / "source.txt").write_bytes(b"source")
    sec_documents = [
        {
            "status": "downloaded",
            "form": form,
            "form_items": items,
            "filed_at": published,
            "accession_number": f"acc-{index}",
            "raw_path": "source.txt",
            "raw_sha256": checksum,
        }
        for index, (form, items, published) in enumerate(
            (
                ("10-K", [], "2020-01-01"),  # retained cache, outside five years
                ("10-K", [], "2022-01-01"),
                ("8-K", ["2.02"], "2024-09-04"),
                ("10-Q", [], "2026-08-27"),
                ("8-K", ["5.02"], "2026-10-16"),  # not eligible for evaluation
            )
        )
    ]
    sec_path = tmp_path / "data/sec/history/META/manifest.json"
    sec_path.parent.mkdir(parents=True)
    sec = {"ticker": "META", "discovery_complete": True, "index_errors": [], "documents": sec_documents}
    sec_path.write_text(json.dumps(sec))
    ir_path = tmp_path / "data/company_communications/curated/META/manifest.json"
    ir_path.parent.mkdir(parents=True)
    ir_path.write_text(
        json.dumps(
            {
                "ticker": "META",
                "documents": [
                    {
                        "published_at": "2026-07-29",
                        "document_type": "earnings_call_transcript",
                        "curated_path": "source.txt",
                        "sha256": checksum,
                        "canonical_filename": "call.txt",
                    }
                ],
            }
        )
    )

    path = freeze_corpus_selection.freeze_selection(tmp_path)
    frozen = path.read_bytes()
    payload = json.loads(frozen)
    assert payload["latest_cached_publication"] == "2026-10-16"
    assert payload["corpus_window"] == {"start": "2021-08-27", "end": "2026-08-27"}
    assert payload["held_out_starts"] == "2024-09-04"
    assert len(payload["records"]) == 4
    assert freeze_corpus_selection.freeze_selection(tmp_path).read_bytes() == frozen

    sec["note"] = "changed input manifest"
    sec_path.write_text(json.dumps(sec))
    with pytest.raises(ValueError, match="immutable"):
        freeze_corpus_selection.freeze_selection(tmp_path)
    assert path.read_bytes() == frozen
