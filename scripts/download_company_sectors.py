"""Save six actual company profiles for separate assistant sector review.

Run: uv run python -m scripts.download_company_sectors --data-root /path/to/sentimentAI-data
The downloader deliberately does not invent or approve classifications.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from bs4 import BeautifulSoup

from sentiment_system.domain.research import RESEARCH_TICKERS

_MAX_BYTES = 8 * 1024 * 1024


def download_profiles(root: Path, snapshot: str, client: httpx.Client) -> Path:
    """Atomically preserve HTML and readable text with real retrieval provenance."""
    if not root.is_dir() or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}", snapshot):
        raise ValueError("existing data root and safe snapshot name are required")
    parent = root / "data/company_sectors"
    if not parent.resolve().is_relative_to(root.resolve()):
        raise ValueError("sector directory escapes data root")
    parent.mkdir(parents=True, exist_ok=True)
    destination = parent / snapshot
    if destination.exists():
        raise ValueError("sector snapshot already exists; refusing overwrite")
    staging = Path(tempfile.mkdtemp(prefix=".sectors-", dir=parent))
    downloads: list[dict[str, Any]] = []
    try:
        for ticker in RESEARCH_TICKERS:
            url = f"https://stockanalysis.com/stocks/{ticker.lower()}/company/"
            # Fixed HTTPS host, TLS verification enabled, no redirected destinations.
            with client.stream("GET", url, follow_redirects=False) as response:
                response.raise_for_status()
                if response.status_code != 200:
                    raise ValueError(f"profile was not returned for {ticker}")
                content = bytearray()
                for chunk in response.iter_bytes():
                    content.extend(chunk)
                    if len(content) > _MAX_BYTES:
                        raise ValueError("sector response exceeds size limit")
                retrieved = datetime.now(timezone.utc).isoformat()
                content_type = response.headers.get("content-type", "")
            soup = BeautifulSoup(bytes(content), "html.parser")
            main = soup.find("main")
            if main is None or ticker not in main.get_text() or "Sector" not in main.get_text():
                raise ValueError(f"response has no company/sector evidence for {ticker}")
            for node in main.select("script, style"):
                node.decompose()
            text = main.get_text("\n", strip=True) + "\n"
            (staging / f"{ticker}.html").write_bytes(content)
            (staging / f"{ticker}.txt").write_text(text, encoding="utf-8")
            relative = destination.relative_to(root).as_posix()
            downloads.append(
                {
                    "ticker": ticker,
                    "source_url": url,
                    "retrieved_at": retrieved,
                    "content_type": content_type,
                    "raw_path": f"{relative}/{ticker}.html",
                    "raw_sha256": hashlib.sha256(content).hexdigest(),
                    "text_path": f"{relative}/{ticker}.txt",
                    "text_sha256": hashlib.sha256(text.encode()).hexdigest(),
                }
            )
            time.sleep(0.2)
        payload = {"schema_version": 1, "provider": "Stock Analysis company profiles", "downloads": downloads}
        (staging / "downloads.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        staging.replace(destination)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return destination


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, default=os.environ.get("SENTIMENT_DATA_ROOT"))
    parser.add_argument("--snapshot", default="stockanalysis_2026_10_18")
    args = parser.parse_args()
    if args.data_root is None or not args.data_root.is_dir():
        parser.error("set SENTIMENT_DATA_ROOT or --data-root to the existing data repository")
    with httpx.Client(timeout=30.0, headers={"User-Agent": "sentimentAI-research/0.1"}) as client:
        print(download_profiles(args.data_root, args.snapshot, client))


if __name__ == "__main__":
    main()
