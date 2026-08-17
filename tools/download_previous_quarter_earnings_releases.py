#!/usr/bin/env python3
"""Download official SEC-filed earnings releases from prior-quarter 8-K filings.

The script selects 8-K filings whose Item 2.02 reports results of operations,
then stores each complete SEC submission. Earnings releases are normally an
EX-99.1 exhibit inside that submission, so preserving the complete filing keeps
the original document and exhibit available for later deterministic extraction.

Usage:
    SEC_USER_AGENT='Project Name contact@example.com' \
        uv run python tools/download_previous_quarter_earnings_releases.py
"""

import json
import os
import time
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from download_previous_quarter_10q_indexes import (
    DEFAULT_USER_AGENT,
    OUTPUT_DIRECTORY,
    REQUEST_DELAY_SECONDS,
    load_companies,
    previous_calendar_quarter,
)

SUBMISSIONS_DIRECTORY = OUTPUT_DIRECTORY / "submissions"
RELEASES_DIRECTORY = OUTPUT_DIRECTORY / "earnings_releases"
MANIFEST_PATH = OUTPUT_DIRECTORY / "manifests" / "previous_calendar_quarter_earnings_releases.json"
SEC_ARCHIVES_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{directory}/{accession}.txt"


@dataclass(frozen=True, slots=True)
class EarningsRelease:
    """SEC metadata for an official earnings-release submission."""

    ticker: str
    cik: str
    accession_number: str
    filed_at: str
    report_date: str
    primary_document: str
    items: str
    source_url: str


def select_earnings_releases(
    *, ticker: str, cik: str, submission: dict[str, object], start: date, end: date
) -> tuple[EarningsRelease, ...]:
    """Select 8-K results releases submitted in the requested date range."""
    filings = submission.get("filings")
    if not isinstance(filings, dict) or not isinstance(filings.get("recent"), dict):
        raise ValueError(f"SEC submission for {ticker} has no recent filings section")
    recent = filings["recent"]

    forms = recent.get("form")
    filed_dates = recent.get("filingDate")
    accessions = recent.get("accessionNumber")
    report_dates = recent.get("reportDate")
    primary_documents = recent.get("primaryDocument")
    items = recent.get("items")
    columns = (forms, filed_dates, accessions, report_dates, primary_documents, items)
    if not all(isinstance(column, list) for column in columns):
        raise ValueError(f"SEC submission for {ticker} has malformed recent filings")

    releases: list[EarningsRelease] = []
    for form, filed_at, accession, report_date, primary_document, filing_items in zip(*columns, strict=True):
        values = (filed_at, accession, report_date, primary_document, filing_items)
        if form != "8-K" or not all(isinstance(value, str) for value in values) or "2.02" not in filing_items:
            continue
        filing_date = date.fromisoformat(filed_at)
        if not start <= filing_date <= end:
            continue
        accession_without_hyphens = accession.replace("-", "")
        releases.append(
            EarningsRelease(
                ticker=ticker,
                cik=cik,
                accession_number=accession,
                filed_at=filed_at,
                report_date=report_date,
                primary_document=primary_document,
                items=filing_items,
                source_url=SEC_ARCHIVES_URL.format(
                    cik=int(cik), directory=accession_without_hyphens, accession=accession
                ),
            )
        )
    return tuple(releases)


def fetch_submission(url: str, user_agent: str) -> bytes:
    """Fetch a raw SEC submission while retaining the complete exhibit package."""
    request = Request(url, headers={"User-Agent": user_agent})
    with urlopen(request, timeout=30) as response:
        return response.read()


def main() -> None:
    user_agent = os.environ.get("SEC_USER_AGENT", DEFAULT_USER_AGENT)
    if "@" not in user_agent:
        raise ValueError("SEC_USER_AGENT must include a contact email address")

    start, end = previous_calendar_quarter(date.today())
    releases: list[EarningsRelease] = []
    for ticker, cik in load_companies(Path("cik_map.csv")):
        submission_path = SUBMISSIONS_DIRECTORY / f"{ticker}_{cik}.json"
        if not submission_path.is_file():
            raise FileNotFoundError(
                f"Missing {submission_path}; run tools/download_previous_quarter_10q_indexes.py first"
            )
        submission = json.loads(submission_path.read_text(encoding="utf-8"))
        releases.extend(select_earnings_releases(ticker=ticker, cik=cik, submission=submission, start=start, end=end))

    RELEASES_DIRECTORY.mkdir(parents=True, exist_ok=True)
    failures: list[str] = []
    for release in releases:
        try:
            content = fetch_submission(release.source_url, user_agent)
        except (HTTPError, URLError, TimeoutError) as error:
            failures.append(f"{release.ticker} {release.accession_number}: {error}")
            continue
        output_path = RELEASES_DIRECTORY / f"{release.ticker}_{release.accession_number}.txt"
        output_path.write_bytes(content)
        time.sleep(REQUEST_DELAY_SECONDS)

    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text(
        json.dumps(
            {
                "form": "8-K",
                "item": "2.02",
                "period": {"start": start.isoformat(), "end": end.isoformat()},
                "releases": [asdict(release) for release in releases],
                "failures": failures,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    print(f"Found {len(releases)} official 8-K Item 2.02 earnings-release filings")
    print(f"Stored {len(releases) - len(failures)} raw SEC submissions in {RELEASES_DIRECTORY}")
    print(f"Wrote {MANIFEST_PATH}")
    if failures:
        print("Failed submissions:")
        print("\n".join(failures))


if __name__ == "__main__":
    main()
