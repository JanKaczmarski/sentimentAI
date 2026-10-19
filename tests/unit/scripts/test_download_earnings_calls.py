"""Acquisition must distinguish complete earnings calls from other IR PDFs."""

import json
from io import BytesIO
from pathlib import Path

import httpx
import pytest
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from scripts import download_earnings_calls as acquisition
from scripts.download_earnings_calls import (
    AcquisitionError,
    Candidate,
    Fetcher,
    download_candidate,
    inspect_pdf,
    parse_html_archive,
    select_q4_documents,
)


def transcript_pdf(text: str = "Earnings Call Transcript - May 20, 2014 - QUESTIONS AND ANSWERS") -> bytes:
    writer = PdfWriter()
    page = writer.add_blank_page(width=600, height=800)
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    page[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})}
    )
    content = DecodedStreamObject()
    content.set_data(f"BT /F1 12 Tf 30 750 Td ({text}) Tj ET".encode())
    page[NameObject("/Contents")] = content
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def test_q4_uses_events_to_extend_history_and_excludes_follow_up_and_non_earnings() -> None:
    report = {
        "ReportYear": 2024,
        "ReportSubType": "First Quarter",
        "ReportDate": "03/31/2024 00:00:00",
        "ReportId": 1,
        "Documents": [
            {"DocumentTitle": "Earnings Call Transcript", "DocumentPath": "/current.pdf"},
            {"DocumentTitle": "Follow Up Call Transcript", "DocumentPath": "/follow-up.pdf"},
            {"DocumentTitle": "Earnings Release", "DocumentPath": "/release.pdf"},
            {"DocumentTitle": "Earnings Script and Slides", "DocumentPath": "/script.pdf"},
            {"DocumentTitle": "Earnings Transcript", "DocumentPath": "/Earnings_Presentation.pdf"},
        ],
    }
    event = {
        "EventId": 2,
        "Title": "Q4 2016 Earnings",
        "StartDate": "02/01/2017 14:00:00",
        "Attachments": [{"Title": "Transcript", "Url": "/older.pdf"}],
    }
    conference = {**event, "Title": "Technology Investor Conference"}
    discovery = select_q4_documents("META", [report], [event, conference])
    assert {(item.fiscal_period, item.source_url) for item in discovery.candidates} == {
        ("FY2024-Q1", "https://investor.atmeta.com/current.pdf"),
        ("FY2016-Q4", "https://investor.atmeta.com/older.pdf"),
    }
    assert discovery.candidates[1].call_date == "2017-02-01"
    # ReportDate describes a fiscal period, not publication of the transcript.
    assert discovery.candidates[0].call_date is None


def test_html_archive_keeps_fiscal_context_and_drops_scripts_and_investor_meetings() -> None:
    html = """
    <main><h2>Fiscal year 2024</h2><h3>Q4</h3>
    <a href='/cc-shared/assets/investor-relations/pdfs/call.pdf#_blank'>Earnings transcript</a>
    <a href='/slides.pdf'>Earnings script and slides</a>
    <h3>Investor Meeting 2024</h3><a href='/conference.pdf'>Transcript</a>
    <h2>Fiscal year 2009</h2><h3>Q1</h3><a href='/old-script.pdf'>Earnings script</a></main>
    """
    discovery = parse_html_archive("ADBE", html)
    assert [(item.fiscal_period, item.source_url) for item in discovery.candidates] == [
        ("FY2024-Q4", "https://www.adobe.com/cc-shared/assets/investor-relations/pdfs/call.pdf")
    ]
    assert "FY2009-Q1" in discovery.available_periods


def test_amazon_without_transcripts_is_a_successful_empty_discovery() -> None:
    discovery = select_q4_documents(
        "AMZN",
        [
            {
                "ReportYear": 2000,
                "ReportSubType": "Fourth Quarter",
                "Documents": [{"DocumentTitle": "Earnings Release PDF", "DocumentPath": "/earnings.pdf"}],
            }
        ],
        [],
    )
    assert discovery.candidates == []
    assert discovery.available_periods == {"FY2000-Q4"}


def test_pdf_validation_rejects_html_and_prepared_remarks() -> None:
    with pytest.raises(AcquisitionError, match="PDF"):
        inspect_pdf(b"<html>Access denied</html>")
    with pytest.raises(AcquisitionError, match="question"):
        inspect_pdf(transcript_pdf("Earnings Call Prepared Remarks - May 20, 2014"))
    assert inspect_pdf(transcript_pdf())["call_date"] == "2014-05-20"


def test_numeric_date_on_salesforce_transcript_cover() -> None:
    assert (
        inspect_pdf(transcript_pdf("05 - 31 - 2023 Salesforce Q1 FY24 Earnings Call QUESTIONS AND ANSWERS"))[
            "call_date"
        ]
        == "2023-05-31"
    )


@pytest.mark.parametrize(
    "qa_text",
    [
        "We will now open the lines for a question-and-answer session.",
        "Operator: Your first question comes from Morgan Stanley.",
        "Operator: Our first question comes from Michael Nathanson.",
        "Operator: The first question in the queue comes from Ben Swinburne.",
        "Let us open up the call for questions. Operator: We go first to Alex.",
    ],
)
def test_pdf_validation_accepts_actual_issuer_qa_formats(qa_text: str) -> None:
    assert inspect_pdf(transcript_pdf(f"Earnings Call Transcript - May 20, 2014 - {qa_text}"))["pages"] == 1


def test_pdf_validation_rejects_a_mislabelled_investor_conference() -> None:
    content = transcript_pdf("JP Morgan Media Conference - May 24, 2021 - QUESTIONS AND ANSWERS")
    with pytest.raises(AcquisitionError, match="non-earnings conference"):
        inspect_pdf(content)


def test_download_retains_bytes_provenance_and_resumes_without_network(tmp_path: Path) -> None:
    content = transcript_pdf()
    calls: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, content=content, headers={"Content-Type": "application/pdf"})

    candidate = Candidate("CRM", "FY2015-Q1", "https://s205.q4cdn.com/626266368/call.pdf", "Transcript", "1", "feed")
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        fetcher = Fetcher(client, delay=0)
        record = download_candidate(fetcher, candidate, tmp_path)
        assert (tmp_path / str(record["local_path"])).read_bytes() == content
        assert record["published_at"] == "2014-05-20"
        assert record["fiscal_period"] == "FY2015-Q1"
        assert len(str(record["sha256"])) == 64
        resumed = download_candidate(fetcher, candidate, tmp_path, previous=record)
        assert resumed["status"] == "existing"
        assert len(calls) == 1


def test_fetch_retries_transient_errors_but_validates_redirect_before_following() -> None:
    calls: list[str] = []

    def respond(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        if len(calls) == 1:
            return httpx.Response(503)
        return httpx.Response(302, headers={"Location": "http://127.0.0.1/private"})

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        with pytest.raises(AcquisitionError, match="official HTTPS"):
            Fetcher(client, delay=0).get("https://investor.visa.com/file.pdf")
    assert len(calls) == 2


def test_discovery_requests_unbounded_history_and_merges_event_dates() -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        assert request.url.params["year"] == "-1"
        assert request.url.params["pageSize"] == "-1"
        if "FinancialReport" in request.url.path:
            return httpx.Response(
                200,
                json={
                    "GetFinancialReportListResult": [
                        {
                            "ReportYear": 2008,
                            "ReportSubType": "Second Quarter",
                            "Documents": [{"DocumentTitle": "Transcript", "DocumentPath": "/old.pdf"}],
                        }
                    ]
                },
            )
        return httpx.Response(
            200,
            json={
                "GetEventListResult": [
                    {
                        "Title": "Q2 2008 Visa Earnings Conference Call",
                        "StartDate": "04/28/2008 17:00:00",
                        "Attachments": [{"Title": "Transcript", "Url": "/old.pdf"}],
                    }
                ]
            },
        )

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        discovery = acquisition.discover(Fetcher(client, delay=0), "V")
    assert len(discovery.candidates) == 1
    assert discovery.candidates[0].call_date == "2008-04-28"


def test_interrupted_resume_preserves_provenance_of_unprocessed_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    raw = tmp_path / "data" / "company_communications" / "raw" / "CRM"
    raw.mkdir(parents=True)
    candidates = [
        Candidate("CRM", "FY2020-Q1", "https://s205.q4cdn.com/first.pdf", "Transcript", "1", "feed"),
        Candidate("CRM", "FY2020-Q2", "https://s205.q4cdn.com/second.pdf", "Transcript", "2", "feed"),
    ]
    previous = [
        {"source_url": item.source_url, "fiscal_period": item.fiscal_period, "sha256": "abc", "status": "downloaded"}
        for item in candidates
    ]
    manifest = raw / "earnings_calls_manifest.json"
    manifest.write_text(json.dumps({"documents": previous}))
    monkeypatch.setattr(
        acquisition,
        "discover",
        lambda *_: acquisition.Discovery(candidates, {"FY2020-Q1", "FY2020-Q2"}),
    )

    def interrupted(*args: object, **kwargs: object) -> dict[str, object]:
        if args[1] == candidates[1]:
            raise KeyboardInterrupt
        assert kwargs["previous"] == previous[0]
        return {**previous[0], "status": "existing"}

    monkeypatch.setattr(acquisition, "download_candidate", interrupted)
    with pytest.raises(KeyboardInterrupt):
        acquisition.run(tmp_path, ["CRM"], delay=0)
    saved = json.loads(manifest.read_text())
    assert len(saved["documents"]) == 2
    assert previous[1] in saved["documents"]


def test_att_discovery_follows_all_years_and_uses_quarter_heading_not_pdf_path() -> None:
    visited: list[str] = []

    def respond(request: httpx.Request) -> httpx.Response:
        visited.append(request.url.path)
        assert "Chrome/" in request.headers["User-Agent"]
        if request.url.path.endswith("/quarterly-earnings"):
            return httpx.Response(
                200,
                text="""<a href='/financial-reports/quarterly-earnings/2019'>2019</a>
                <a href='/financial-reports/quarterly-earnings/2020'>2020</a>""",
            )
        if request.url.path.endswith("/2019"):
            return httpx.Response(200, text="<h3>Second-Quarter Earnings Package</h3>")
        return httpx.Response(
            200,
            text="""<h3>Fourth-Quarter Earnings Package</h3>
            <table><tr><td>Transcript with Q&amp;A (PDF) and Prepared Remarks (HTML)</td><td>
              <a href='/media/2021/call-transcript.pdf'>PDF</a>
              <a href='/prepared-remarks.aspx'>HTML</a>
            </td></tr><tr><td>News Release</td><td><a href='/release.pdf'>PDF</a></td></tr></table>
            <h3>Supplemental Files</h3><a href='/supplement-transcript.pdf'>Transcript</a>""",
        )

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        discovery = acquisition.discover(Fetcher(client, delay=0), "T")
    assert len(visited) == 3
    assert discovery.available_periods == {"FY2019-Q2", "FY2020-Q4"}
    assert [(item.fiscal_period, item.source_url) for item in discovery.candidates] == [
        ("FY2020-Q4", "https://investors.att.com/media/2021/call-transcript.pdf")
    ]


def test_disney_event_only_quarter_extends_past_financial_table() -> None:
    discovery = select_q4_documents(
        "DIS",
        [],
        [
            {
                "Title": "Disney’s Q3 FY26 Earnings Results Webcast",
                "StartDate": "08/05/2026 08:30:00",
                "Attachments": [
                    {"Title": "Transcript", "Url": "https://s206.q4cdn.com/979796730/q3-fy26-transcript.pdf"}
                ],
            }
        ],
    )
    assert discovery.candidates[0].fiscal_period == "FY2026-Q3"


def test_mislinked_disney_quarter_is_reported_and_correct_event_link_is_kept() -> None:
    bad_url = "https://s206.q4cdn.com/979796730/files/doc_events/2022/11/q4-fy22-earnings-transcript.pdf"
    good_url = "https://s206.q4cdn.com/979796730/files/doc_events/2021/11/q4-fy21-earnings-transcript.pdf"
    discovery = select_q4_documents(
        "DIS",
        [
            {
                "ReportYear": 2021,
                "ReportSubType": "Fourth Quarter",
                "Documents": [{"DocumentTitle": "Q4 FY21 Earnings Transcript", "DocumentPath": bad_url}],
            }
        ],
        [
            {
                "Title": "Disney’s Fiscal Full Year and Q4 2021 Earnings Results Webcast",
                "StartDate": "11/10/2021 16:30:00",
                "Attachments": [{"Title": "Transcript", "Url": good_url}],
            }
        ],
    )
    assert [(item.fiscal_period, item.source_url) for item in discovery.candidates] == [("FY2021-Q4", good_url)]
    assert discovery.source_anomalies[0]["source_url"] == bad_url


def test_five_year_requirement_needs_consecutive_complete_years_not_just_oldest_pdf() -> None:
    records = [
        {"fiscal_period": f"FY{year}-Q{quarter}", "status": "downloaded"}
        for year in (2017, 2020, 2021, 2022, 2023, 2024)
        for quarter in range(1, 5)
    ]
    records = [item for item in records if item["fiscal_period"] != "FY2022-Q3"]
    assert acquisition.coverage_summary(records)["meets_five_full_years"] is False
    records.append({"fiscal_period": "FY2022-Q3", "status": "failed"})
    assert acquisition.coverage_summary(records)["meets_five_full_years"] is False
    records[-1]["status"] = "existing"
    assert acquisition.coverage_summary(records)["meets_five_full_years"] is True
    assert acquisition.coverage_summary(records)["longest_complete_year_run"] == 5
