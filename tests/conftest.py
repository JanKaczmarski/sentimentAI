"""Synthetic, local sector evidence for corpus contract tests (never research data)."""

import hashlib
import json
from pathlib import Path

import pytest


@pytest.fixture
def sector_bundle():
    def install(root: Path) -> dict[str, str]:
        folder = root / "sector_evidence"
        folder.mkdir(parents=True, exist_ok=True)
        downloads, companies = [], []
        for ticker, sector in (
            ("META", "Communication Services"),
            ("CRM", "Information Technology"),
            ("V", "Financials"),
            ("DIS", "Communication Services"),
            ("WHR", "Consumer Discretionary"),
            ("T", "Communication Services"),
        ):
            text = f"Ticker Symbol\n{ticker}\nSector\n{sector}\n"
            raw = f"<main><div>Ticker Symbol</div><div>{ticker}</div><div>Sector</div><div>{sector}</div></main>"
            (folder / f"{ticker}.html").write_text(raw)
            (folder / f"{ticker}.txt").write_text(text)
            downloads.append(
                {
                    "ticker": ticker,
                    "source_url": f"https://example.com/{ticker}",
                    "retrieved_at": "2026-10-18T00:00:00+00:00",
                    "raw_path": f"sector_evidence/{ticker}.html",
                    "raw_sha256": hashlib.sha256(raw.encode()).hexdigest(),
                    "text_path": f"sector_evidence/{ticker}.txt",
                    "text_sha256": hashlib.sha256(text.encode()).hexdigest(),
                }
            )
            companies.append(
                {
                    "ticker": ticker,
                    "source_sector": sector,
                    "sector": sector,
                    "evidence_quote": f"Sector\n{sector}",
                    "normalization_note": "Synthetic label unchanged.",
                }
            )
        encoded = json.dumps({"schema_version": 1, "downloads": downloads}).encode()
        (folder / "downloads.json").write_bytes(encoded)
        review = {
            "schema_version": 1,
            "reviewer": "test fixture",
            "note": "Synthetic test data only.",
            "downloads_path": "sector_evidence/downloads.json",
            "downloads_sha256": hashlib.sha256(encoded).hexdigest(),
            "companies": companies,
        }
        encoded_review = json.dumps(review).encode()
        (folder / "reviewed.json").write_bytes(encoded_review)
        return {
            "sector_review_path": "sector_evidence/reviewed.json",
            "sector_review_sha256": hashlib.sha256(encoded_review).hexdigest(),
        }

    return install
