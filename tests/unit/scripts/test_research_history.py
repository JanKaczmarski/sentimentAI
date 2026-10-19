"""Historical acquisition retains source evidence and reports actual gaps."""

import hashlib
import json
from datetime import date
from pathlib import Path

import httpx
import pytest

from scripts.curate_earnings_calls import curate_company
from scripts.download_sec_history import SecFetcher, acquire_company, select_filings
from scripts.research_inventory import build_inventory
from sentiment_system.domain.research import RESEARCH_TICKERS
from tests.unit.scripts.test_download_earnings_calls import transcript_pdf


def test_research_sample_is_the_six_transcript_companies() -> None:
    assert RESEARCH_TICKERS == ("META", "CRM", "V", "DIS", "WHR", "T")


def raw_ir(root: Path, *, published_at: str | None = "2016-07-27") -> bytes:
    folder = root / "data/company_communications/raw/META"
    folder.mkdir(parents=True)
    content = transcript_pdf(
        "Meta Q2 2016 Earnings Call - " + ("July 27, 2016 - " if published_at else "") + "QUESTIONS AND ANSWERS"
    )
    (folder / "original.pdf").write_bytes(content)
    (folder / "earnings_calls_manifest.json").write_text(
        json.dumps(
            {
                "ticker": "META",
                "archive_fiscal_periods": ["FY2016-Q2", "FY2016-Q3"],
                "documents": [
                    {
                        "ticker": "META",
                        "status": "downloaded",
                        "fiscal_period": "FY2016-Q2",
                        "published_at": published_at,
                        "local_path": "META/original.pdf",
                        "original_filename": "original.pdf",
                        "source_url": "https://investor.atmeta.com/call.pdf",
                        "sha256": hashlib.sha256(content).hexdigest(),
                        "retrieved_at": "2026-10-17T12:00:00+00:00",
                        "document_type": "earnings_call_transcript",
                        "publication_date_basis": "pdf_header",
                    }
                ],
            }
        )
    )
    return content


def test_curate_preserves_bytes_and_provenance_and_reports_missing_quarters(tmp_path: Path) -> None:
    content = raw_ir(tmp_path)
    first = curate_company(tmp_path, "META")
    second = curate_company(tmp_path, "META")
    folder = tmp_path / "data/company_communications/curated/META"
    filename = "META__FY2016-Q2__2016-07-27__investor_relations__earnings_call_transcript.pdf"
    assert (folder / filename).read_bytes() == content
    assert (folder / "manifest.csv").is_file()
    assert first == second
    assert first["coverage"]["archive_periods_without_curated_transcript"] == ["FY2016-Q3"]
    assert first["coverage"]["publication_start"] == "2016-07-27"
    assert first["documents"][0]["raw_path"].endswith("META/original.pdf")


def test_curate_never_invents_unknown_dates_or_accepts_tampered_raw(tmp_path: Path) -> None:
    raw_ir(tmp_path, published_at=None)
    assert curate_company(tmp_path, "META")["issues"][0]["reason"] == "publication date unavailable"
    raw = tmp_path / "data/company_communications/raw/META/original.pdf"
    raw.write_bytes(b"changed")
    result = curate_company(tmp_path, "META")
    assert "checksum" in result["issues"][0]["reason"]


def columns(accession: str, *, form: str = "8-K", filed: str = "2016-07-27") -> dict:
    return {
        "form": [form],
        "filingDate": [filed],
        "accessionNumber": [accession],
        "reportDate": [filed],
        "items": ["2.02,9.01" if form == "8-K" else ""],
        "primaryDocument": ["filing.htm"],
    }


def test_selection_includes_all_8k_but_excludes_amendments_and_outside_dates() -> None:
    found = select_filings(columns("0001326801-16-000001"), "1326801", date(2016, 1, 1), date(2016, 12, 31))
    assert found[0]["form_items"] == ["2.02", "9.01"]
    non_earnings = columns("0001326801-16-000002")
    non_earnings["items"] = ["5.02"]
    assert select_filings(non_earnings, "1326801", date(2016, 1, 1), date(2016, 12, 31))
    assert not select_filings(
        columns("0001326801-16-000003", form="8-K/A"), "1326801", date(2016, 1, 1), date(2016, 12, 31)
    )
    assert not select_filings(
        columns("0001326801-16-000004", filed="2015-12-31"), "1326801", date(2016, 1, 1), date(2016, 12, 31)
    )


def test_acquisition_merges_history_deduplicates_resumes_and_records_failures(tmp_path: Path) -> None:
    seen: list[str] = []
    accession = "0001326801-16-000001"
    failed = "0001326801-16-000002"

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        seen.append(path)
        if path.endswith("CIK0001326801.json"):
            return httpx.Response(
                200,
                json={
                    "filings": {
                        "recent": columns(accession),
                        "files": [
                            {
                                "name": "CIK0001326801-submissions-001.json",
                                "filingFrom": "2016-01-01",
                                "filingTo": "2016-12-31",
                            },
                            {
                                "name": "CIK0001326801-submissions-002.json",
                                "filingFrom": "2010-01-01",
                                "filingTo": "2010-12-31",
                            },
                        ],
                    }
                },
            )
        if path.endswith("submissions-001.json"):
            older = columns(failed, form="10-K")
            return httpx.Response(200, json={key: value + older[key] for key, value in columns(accession).items()})
        if failed in path:
            return httpx.Response(404)
        # Older SEC submissions wrap the SGML in a privacy-enhanced message.
        return httpx.Response(
            200,
            content=b"-----BEGIN PRIVACY-ENHANCED MESSAGE-----\n"
            + b" " * 500
            + b"<SEC-DOCUMENT>\n<SEC-HEADER>\n<ACCESSION-NUMBER>"
            + accession.encode()
            + b"\n</SEC-DOCUMENT>",
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        fetcher = SecFetcher(client, "Research test@example.test", delay=0)
        manifest = acquire_company(tmp_path, "META", date(2016, 1, 1), date(2016, 12, 31), fetcher)
        assert manifest["coverage"]["expected"] == 2
        assert manifest["coverage"]["downloaded"] == 1
        assert manifest["coverage"]["missing"][0]["accession_number"] == failed
        before = seen.count(f"/Archives/edgar/data/1326801/{accession.replace('-', '')}/{accession}.txt")
        acquire_company(tmp_path, "META", date(2016, 1, 1), date(2016, 12, 31), fetcher)
        assert seen.count(f"/Archives/edgar/data/1326801/{accession.replace('-', '')}/{accession}.txt") == before
    assert not any("submissions-002" in path for path in seen)


def test_sec_history_rejects_untrusted_history_paths_and_mismatched_columns() -> None:
    with pytest.raises(ValueError):
        select_filings({"form": ["10-K"]}, "1326801", date(2016, 1, 1), date(2016, 12, 31))
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200))) as client:
        with pytest.raises(ValueError, match="official SEC"):
            SecFetcher(client, "Research test@example.test", delay=0).get("https://example.test/file")


def test_inventory_detects_tampering_even_when_manifest_claims_success(tmp_path: Path) -> None:
    raw_ir(tmp_path)
    curate_company(tmp_path, "META")
    sec = tmp_path / "data/sec/history/META"
    sec.mkdir(parents=True)
    (sec / "manifest.json").write_text(
        json.dumps(
            {
                "requested_window": {"start": "2016-01-01", "end": "2016-12-31"},
                "ciks": ["1326801"],
                "indexes": [],
                "documents": [],
                "coverage": {},
                "discovery_complete": True,
                "index_errors": [],
            }
        )
    )
    assert build_inventory(tmp_path, ("META",))["verification"]["errors"] == []
    (tmp_path / "data/company_communications/raw/META/original.pdf").write_bytes(b"tampered")
    errors = build_inventory(tmp_path, ("META",))["verification"]["errors"]
    assert len(errors) == 1
    assert errors[0]["error"] == "checksum mismatch"


def test_curate_rejects_source_path_traversal_without_copying_it(tmp_path: Path) -> None:
    raw_ir(tmp_path)
    path = tmp_path / "data/company_communications/raw/META/earnings_calls_manifest.json"
    manifest = json.loads(path.read_text())
    manifest["documents"][0]["local_path"] = "../outside.pdf"
    path.write_text(json.dumps(manifest))
    result = curate_company(tmp_path, "META")
    assert result["documents"] == []
    assert "safe regular relative file" in result["issues"][0]["reason"]
