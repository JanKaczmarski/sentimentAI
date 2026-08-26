#!/usr/bin/env python3
"""Cache SEC company indexes and select 10-Q filings from the previous calendar quarter.

Usage:
    uv run python tools/download_previous_quarter_10q_indexes.py

The script reads the CIK map and writes SEC submissions below the configured
data repository root. Set ``SENTIMENT_DATA_ROOT`` to the separate data repo.
"""

import csv
import json
import os
import time
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from data_paths import cik_map_path, sec_directory

CIK_MAP_PATH = cik_map_path()
OUTPUT_DIRECTORY = sec_directory()
SEC_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
DEFAULT_USER_AGENT = "sentiment-system research contact@example.com"
REQUEST_DELAY_SECONDS = 0.2


@dataclass(frozen=True, slots=True)
class Filing:
    """Minimal filing metadata needed to fetch the filing document later."""

    ticker: str
    cik: str
    accession_number: str
    filed_at: str
    report_date: str
    primary_document: str
    form: str


def previous_calendar_quarter(today: date) -> tuple[date, date]:
    """Return inclusive boundaries for the calendar quarter before ``today``."""
    current_quarter = (today.month - 1) // 3
    current_year = today.year
    if current_quarter == 0:
        return date(current_year - 1, 10, 1), date(current_year - 1, 12, 31)

    start_month = (current_quarter - 1) * 3 + 1
    end_month = current_quarter * 3
    quarter_end_days = {3: 31, 6: 30, 9: 30, 12: 31}
    return date(current_year, start_month, 1), date(current_year, end_month, quarter_end_days[end_month])


def load_companies(path: Path) -> tuple[tuple[str, str], ...]:
    """Load ticker and zero-padded CIK values produced by ``tools/cik.py``."""
    with path.open(encoding="utf-8", newline="") as file_handle:
        reader = csv.DictReader(file_handle)
        if reader.fieldnames is None or {"ticker", "cik_padded"} - set(reader.fieldnames):
            raise ValueError(f"{path} must contain ticker and cik_padded columns")
        return tuple((row["ticker"], row["cik_padded"]) for row in reader)


def fetch_json(url: str, user_agent: str) -> dict[str, object]:
    """Fetch a SEC JSON response with the required descriptive User-Agent."""
    request = Request(url, headers={"User-Agent": user_agent})
    with urlopen(request, timeout=30) as response:
        return json.load(response)


def select_10q_filings(
    *, ticker: str, cik: str, submission: dict[str, object], start: date, end: date
) -> tuple[Filing, ...]:
    """Select submitted 10-Q filings that fall within the requested date range."""
    filings = submission.get("filings")
    if not isinstance(filings, dict):
        raise ValueError(f"SEC submission for {ticker} has no filings section")
    recent = filings.get("recent")
    if not isinstance(recent, dict):
        raise ValueError(f"SEC submission for {ticker} has no recent filings section")

    forms = recent.get("form")
    filed_dates = recent.get("filingDate")
    accessions = recent.get("accessionNumber")
    report_dates = recent.get("reportDate")
    primary_documents = recent.get("primaryDocument")
    columns = (forms, filed_dates, accessions, report_dates, primary_documents)
    if not all(isinstance(column, list) for column in columns):
        raise ValueError(f"SEC submission for {ticker} has malformed recent filings")

    selected: list[Filing] = []
    for form, filed_at, accession, report_date, primary_document in zip(*columns, strict=True):
        if form != "10-Q" or not all(
            isinstance(value, str) for value in (filed_at, accession, report_date, primary_document)
        ):
            continue
        filing_date = date.fromisoformat(filed_at)
        if start <= filing_date <= end:
            selected.append(
                Filing(
                    ticker=ticker,
                    cik=cik,
                    accession_number=accession,
                    filed_at=filed_at,
                    report_date=report_date,
                    primary_document=primary_document,
                    form=form,
                )
            )
    return tuple(selected)


def main() -> None:
    if not CIK_MAP_PATH.is_file():
        raise FileNotFoundError(f"Missing {CIK_MAP_PATH}; run uv run python tools/cik.py first")

    user_agent = os.environ.get("SEC_USER_AGENT", DEFAULT_USER_AGENT)
    if "@" not in user_agent:
        raise ValueError("SEC_USER_AGENT must include a contact email address")

    start, end = previous_calendar_quarter(date.today())
    submissions_directory = OUTPUT_DIRECTORY / "submissions"
    manifests_directory = OUTPUT_DIRECTORY / "manifests"
    submissions_directory.mkdir(parents=True, exist_ok=True)
    manifests_directory.mkdir(parents=True, exist_ok=True)

    selected_filings: list[Filing] = []
    failures: list[str] = []
    for ticker, cik in load_companies(CIK_MAP_PATH):
        url = SEC_SUBMISSIONS_URL.format(cik=cik)
        try:
            submission = fetch_json(url, user_agent)
        except (HTTPError, URLError, TimeoutError) as error:
            failures.append(f"{ticker}: {error}")
            continue

        output_path = submissions_directory / f"{ticker}_{cik}.json"
        output_path.write_text(json.dumps(submission, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        selected_filings.extend(select_10q_filings(ticker=ticker, cik=cik, submission=submission, start=start, end=end))
        time.sleep(REQUEST_DELAY_SECONDS)

    manifest = {
        "form": "10-Q",
        "period": {"start": start.isoformat(), "end": end.isoformat()},
        "filings": [asdict(filing) for filing in selected_filings],
        "failures": failures,
    }
    manifest_path = manifests_directory / "previous_calendar_quarter_10q.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(f"Cached {len(load_companies(CIK_MAP_PATH)) - len(failures)} company indexes in {submissions_directory}")
    print(f"Selected {len(selected_filings)} 10-Q filings from {start} through {end}")
    print(f"Wrote {manifest_path}")
    if failures:
        print("Failed indexes:")
        print("\n".join(failures))


if __name__ == "__main__":
    main()
