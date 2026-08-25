#!/usr/bin/env python3
"""
Map a list of tickers to SEC EDGAR CIK numbers.

Uses the SEC's official ticker->CIK mapping file, which is an exact lookup --
unlike the EDGAR company-name search, which returns fuzzy matches.

Usage:
    python ticker_to_cik.py tickers.txt          # one ticker per line, or your
                                                 # ("AAPL", "SMART", "USD") format
    python ticker_to_cik.py                      # uses the TICKERS list below

Output: ``cik_map.csv`` below ``SENTIMENT_DATA_ROOT`` plus a printed list of
anything that could not be matched.
"""

import csv
import json
import os
import re
import sys
import urllib.request
from pathlib import Path

# SEC requires a descriptive User-Agent with a contact address on all automated
# requests, or it returns 403. Put your own email here.
USER_AGENT = "jj-wk sentimetn.ai@gmail.com"

SEC_TICKER_URL = "https://www.sec.gov/files/company_tickers.json"
DATA_REPOSITORY_ROOT = Path(os.environ.get("SENTIMENT_DATA_ROOT", ".")).expanduser()

# Fallback list, used when no input file is given.
TICKERS = [
    "AAPL",
    "ADBE",
    "ALGM",
    "ALK",
    "AMAT",
    "AMD",
    "AMZN",
    "ANET",
    "ANF",
    "APH",
    "ARE",
    "AVGO",
    "BLBD",
    "BWXT",
    "CAKE",
    "CMCSA",
    "COST",
    "CRM",
    "CRWD",
    "DDOG",
    "DIS",
    "DUOL",
    "ELF",
    "EPR",
    "FOUR",
    "FCN",
    "FUBO",
    "GIS",
    "GS",
    "HD",
    "ISRG",
    "KSPI",
    "LULU",
    "MAA",
    "META",
    "MRP",
    "MSFT",
    "NLCP",
    "NU",
    "PINS",
    "PLTR",
    "POOL",
    "PYPL",
    "RBLX",
    "SILA",
    "SIRI",
    "SOFI",
    "SOUN",
    "SPY",
    "STZ",
    "SYNA",
    "T",
    "TDW",
    "TSN",
    "TTD",
    "UNH",
    "UUUU",
    "V",
    "VICI",
    "WHR",
    "ZM",
]


def fetch_sec_map():
    """Download the SEC ticker->CIK file. Returns {TICKER: (cik_int, name)}."""
    req = urllib.request.Request(SEC_TICKER_URL, headers={"User-Agent": USER_AGENT})
    # Default urlopen validates TLS certs against the system trust store.
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.load(resp)

    return {row["ticker"].upper(): (int(row["cik_str"]), row["title"]) for row in data.values()}


def parse_input(path):
    """Pull tickers out of a file. Handles plain lines and ("XYZ", "SMART", ...).

    Skips lines commented out with '#' so your disabled entries stay disabled.
    """
    tickers = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            m = re.search(r'["\']([A-Za-z0-9.\- ]{1,12})["\']', line)
            tickers.append((m.group(1) if m else line.split()[0]).upper())
    return tickers


def main():
    tickers = parse_input(sys.argv[1]) if len(sys.argv) > 1 else TICKERS

    sec_map = fetch_sec_map()
    print(f"Loaded {len(sec_map):,} tickers from SEC.\n")

    rows, missing = [], []
    for t in dict.fromkeys(tickers):  # dedupe, keep original order
        hit = sec_map.get(t)
        if hit:
            cik, name = hit
            rows.append(
                {
                    "ticker": t,
                    "cik": cik,  # integer form, for data.sec.gov
                    "cik_padded": f"{cik:010d}",  # 10-digit form, for filing URLs
                    "company_name": name,
                }
            )
        else:
            missing.append(t)

    output_path = DATA_REPOSITORY_ROOT / "cik_map.csv"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=["ticker", "cik", "cik_padded", "company_name"])
        writer.writeheader()
        writer.writerows(rows)

    for r in rows:
        print(f"{r['ticker']:<8} {r['cik_padded']}  {r['company_name']}")

    print(f"\nMatched {len(rows)} -> {output_path}")
    if missing:
        print(f"No CIK found for: {', '.join(missing)}")
        print(
            "Usually means: non-US listing with no SEC registration, a ticker "
            "change, or an ADR that trades under a different symbol."
        )


if __name__ == "__main__":
    main()
