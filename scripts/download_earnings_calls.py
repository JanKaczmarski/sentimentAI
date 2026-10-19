"""Download complete earnings-call transcript PDFs from the full official IR archives.

Run from the application repository:
    SENTIMENT_DATA_ROOT=/path/to/sentimentAI-data \
        uv run python -m scripts.download_earnings_calls

No year cutoff, credentials, third-party transcript services, or HTML-to-PDF
conversion. Raw PDFs stay unchanged; curated copies require separate review.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urldefrag, urljoin, urlsplit

import httpx
from bs4 import BeautifulSoup
from pypdf import PdfReader

from sentiment_system.domain.research import RESEARCH_TICKERS

ARCHIVES = {
    "ADBE": "https://www.adobe.com/investor-relations/financial-documents.html",
    "AMD": "https://ir.amd.com/financial-information/financial-results",
    "AMZN": "https://ir.aboutamazon.com/quarterly-results/default.aspx",
    "META": "https://investor.atmeta.com/financials/default.aspx",
    "CRM": "https://investor.salesforce.com/financials/quarterly-results/default.aspx",
    "V": "https://investor.visa.com/financial-information/quarterly-earnings/default.aspx",
    "DIS": "https://investors.thewaltdisneycompany.com/financials/quarterly-results/default.aspx",
    "WHR": "https://investors.whirlpoolcorp.com/financial-information/quarterly-results/default.aspx",
    "T": "https://investors.att.com/financial-reports/quarterly-earnings",
}
DEFAULT_TICKERS = RESEARCH_TICKERS
_HOSTS = frozenset(urlsplit(url).hostname for url in ARCHIVES.values()) | {
    "s1.q4cdn.com",
    "s2.q4cdn.com",
    "s21.q4cdn.com",
    "s205.q4cdn.com",
    "s202.q4cdn.com",
    "s206.q4cdn.com",
    "d1io3yog0oux5.cloudfront.net",
}
_QUARTERS = {"First Quarter": 1, "Second Quarter": 2, "Third Quarter": 3, "Fourth Quarter": 4}
_MAX_BYTES = 32 * 1024 * 1024
_EXCLUSIONS = re.compile(r"follow[\s_-]*up|prepared[\s_-]*remarks|\bscript\b|\bslides\b|\bpresentation\b", re.I)
_QA = re.compile(
    r"questions?[\s\-‐‑–—]*(?:and|&)[\s\-‐‑–—]*answers?|\bQ\s*&\s*A\b"
    r"|(?:your|our|the)\s+(?:first|next)\s+question|open\s+(?:up\s+)?the\s+call\s+for\s+questions",
    re.I,
)
_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


class AcquisitionError(RuntimeError):
    """A source or file could not be acquired without changing its meaning."""


def official_url(url: str, base: str = "") -> str:
    """Only known public issuer/CDN HTTPS hosts, including on redirects."""
    normalized = urldefrag(urljoin(base, url))[0]
    parsed = urlsplit(normalized)
    if parsed.scheme == "http" and parsed.hostname in _HOSTS:
        normalized = "https:" + normalized[5:]
        parsed = urlsplit(normalized)
    if (
        parsed.scheme != "https"
        or parsed.hostname not in _HOSTS
        or parsed.username
        or parsed.password
        or parsed.port not in (None, 443)
    ):
        raise AcquisitionError(f"expected an official HTTPS source URL: {normalized}")
    return normalized


class Fetcher:
    """Bounded, rate-limited GETs; validate every redirect before following it."""

    def __init__(self, client: httpx.Client, *, delay: float = 0.2) -> None:
        self.client = client
        self.delay = delay
        self.evidence: list[dict[str, Any]] = []

    def get(self, url: str, params: dict[str, Any] | None = None) -> tuple[bytes, str]:
        target = str(httpx.URL(official_url(url), params=params))
        for attempt in range(3):
            try:
                current = target
                for _ in range(6):
                    official_url(current)
                    time.sleep(self.delay)
                    headers = _BROWSER_HEADERS if urlsplit(current).hostname == "investors.att.com" else {}
                    with self.client.stream("GET", current, follow_redirects=False, headers=headers) as response:
                        if response.is_redirect:
                            current = official_url(response.headers["location"], current)
                            continue
                        response.raise_for_status()
                        content = bytearray()
                        for chunk in response.iter_bytes():
                            content.extend(chunk)
                            if len(content) > _MAX_BYTES:
                                raise AcquisitionError(f"source exceeds {_MAX_BYTES} bytes: {current}")
                        return bytes(content), current
                raise AcquisitionError(f"too many redirects: {target}")
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code not in (429, 500, 502, 503, 504) or attempt == 2:
                    raise AcquisitionError(f"HTTP {exc.response.status_code}: {current}") from exc
            except httpx.TransportError as exc:
                if attempt == 2:
                    raise AcquisitionError(f"network error: {target}: {exc}") from exc
            time.sleep(self.delay * (2 ** (attempt + 1)))
        raise AssertionError("unreachable")

    def archive(self, url: str, params: dict[str, Any] | None = None) -> bytes:
        """Record discovery evidence; retry an uncached URL when a CDN returns 403."""
        try:
            content, final = self.get(url, params)
        except AcquisitionError as exc:
            if "HTTP 403:" not in str(exc):
                raise
            content, final = self.get(url, {**(params or {}), "ir_archive": "earnings_calls"})
        self.evidence.append({"url": final, "retrieved_at": _now(), "sha256": hashlib.sha256(content).hexdigest()})
        return content


@dataclass(frozen=True)
class Candidate:
    ticker: str
    fiscal_period: str
    source_url: str
    title: str
    source_id: str
    discovered_via: str
    call_date: str | None = None


@dataclass
class Discovery:
    candidates: list[Candidate] = field(default_factory=list)
    available_periods: set[str] = field(default_factory=set)
    exclusions: dict[str, int] = field(default_factory=dict)
    source_anomalies: list[dict[str, str]] = field(default_factory=list)

    def consider(
        self,
        ticker: str,
        period: str,
        url: str,
        title: str,
        category: str,
        source_id: str,
        via: str,
        call_date: str | None = None,
    ) -> None:
        label = f"{title} {category} {unquote(url)}".replace("_", " ")
        if not re.search("transcript", label, re.I):
            return
        if _EXCLUSIONS.search(label):
            self.exclusions["other_transcript_type"] = self.exclusions.get("other_transcript_type", 0) + 1
            return
        if not urlsplit(url).path.lower().endswith(".pdf"):
            self.exclusions["not_pdf"] = self.exclusions.get("not_pdf", 0) + 1
            return
        hint = re.search(r"\bq([1-4])[-_]?fy[-_]?(\d{2}(?:\d{2})?)\b", url, re.I)
        if hint:
            year = int(hint[2])
            linked_period = f"FY{year + 2000 if year < 100 else year}-Q{hint[1]}"
            if linked_period != period:
                self.source_anomalies.append(
                    {"source_url": url, "listed_period": period, "filename_period": linked_period}
                )
                return
        self.candidates.append(
            Candidate(ticker, period, official_url(url, ARCHIVES[ticker]), title, source_id, via, call_date)
        )


def _event_period(title: str, tags: list[str]) -> str | None:
    tagged = re.search(r"\bfin-(\d{4})-q([1-4])\b", " ".join(tags), re.I)
    if tagged:
        return f"FY{tagged[1]}-Q{tagged[2]}"
    quarter = re.search(r"\bQ([1-4])\s*(?:FY\s*)?['’]?(\d{2,4})\b", title, re.I)
    if not quarter:
        return None
    year = int(quarter[2])
    return f"FY{year + 2000 if year < 100 else year}-Q{quarter[1]}"


def select_q4_documents(ticker: str, reports: list[dict[str, Any]], events: list[dict[str, Any]]) -> Discovery:
    """Include event attachments: some older calls are absent from financial tables."""
    result = Discovery()
    for report in reports:
        quarter = _QUARTERS.get(report.get("ReportSubType", ""))
        if quarter is None:
            continue
        period = f"FY{int(report['ReportYear'])}-Q{quarter}"
        result.available_periods.add(period)
        for doc in report.get("Documents", []):
            result.consider(
                ticker,
                period,
                doc.get("DocumentPath", ""),
                doc.get("DocumentTitle", ""),
                doc.get("DocumentCategory", ""),
                f"financial-report:{report.get('ReportId')}:document:{doc.get('DocumentId')}",
                "financial_report_feed",
            )
    for event in events:
        title = event.get("Title", "")
        if not re.search(r"earnings|financial results", title, re.I):
            continue
        event_period = _event_period(title, event.get("TagsList") or [])
        if event_period is None:
            continue
        result.available_periods.add(event_period)
        call_date = _source_date(event.get("StartDate", ""))
        for doc in event.get("Attachments", []):
            result.consider(
                ticker,
                event_period,
                doc.get("Url", ""),
                doc.get("Title", ""),
                "",
                f"event:{event.get('EventId')}",
                "event_feed",
                call_date,
            )
    return result


def parse_html_archive(ticker: str, html: str) -> Discovery:
    """Use issuer headings, never publication year, to identify fiscal quarters."""
    result = Discovery()
    soup = BeautifulSoup(html, "html.parser")
    year: int | None = None
    period: str | None = None
    for element in soup.select("h2,h3,a[href]"):
        text = element.get_text(" ", strip=True)
        if element.name == "h2":
            match = re.fullmatch(r"(?:Fiscal year\s+)?(\d{4})", text, re.I)
            year = int(match[1]) if match else None
            period = None
        elif element.name == "h3":
            quarter = re.match(r"^Q([1-4])\b", text)
            period = f"FY{year}-Q{quarter[1]}" if quarter and year else None
            if period:
                result.available_periods.add(period)
        elif period:
            result.consider(ticker, period, str(element.get("href", "")), text, "", period, "archive_html")
    return result


def discover_att(fetcher: Fetcher) -> Discovery:
    """Visit every advertised year; quarterly headings override PDF path years."""
    archive = ARCHIVES["T"]
    index = BeautifulSoup(fetcher.archive(archive), "html.parser")
    year_urls = {
        official_url(str(link["href"]), archive)
        for link in index.select("a[href]")
        if re.fullmatch(r"/financial-reports/quarterly-earnings/\d{4}", str(link["href"]))
    }
    if not year_urls:
        raise AcquisitionError("AT&T archive has no year navigation; check source/parser")
    result = Discovery()
    ordinals = {"first": 1, "second": 2, "third": 3, "fourth": 4}
    for url in sorted(year_urls):
        year = int(url.rsplit("/", 1)[-1])
        soup = BeautifulSoup(fetcher.archive(url), "html.parser")
        period: str | None = None
        periods_before = len(result.available_periods)
        for element in soup.select("h3,a[href]"):
            if element.name == "h3":
                match = re.match(
                    r"^(First|Second|Third|Fourth)[\s-]+Quarter Earnings Package",
                    element.get_text(" ", strip=True),
                    re.I,
                )
                period = f"FY{year}-Q{ordinals[match[1].lower()]}" if match else None
                if period:
                    result.available_periods.add(period)
            elif period:
                row = element.find_parent("tr")
                title = row.get_text(" ", strip=True) if row else element.get_text(" ", strip=True)
                # Newer AT&T rows label a transcript PDF and prepared-remarks
                # HTML together. Use the PDF-specific label, not its neighbour.
                pdf_label = re.search(r"Transcript(?:\s+with\s+Q&A)?\s*\(PDF\)", title, re.I)
                if pdf_label:
                    title = pdf_label[0]
                result.consider("T", period, str(element["href"]), title, "", period, "archive_year_html")
        if len(result.available_periods) == periods_before:
            raise AcquisitionError(f"AT&T year {year} has no recognized earnings packages; check source/parser")
    return result


def discover(fetcher: Fetcher, ticker: str) -> Discovery:
    archive = ARCHIVES[ticker]
    if ticker in ("ADBE", "AMD"):
        result = parse_html_archive(ticker, fetcher.archive(archive).decode("utf-8"))
    elif ticker == "T":
        result = discover_att(fetcher)
    else:
        base = f"https://{urlsplit(archive).hostname}/feed/"
        params: dict[str, Any] = {"year": -1, "pageSize": -1, "includeTags": "true", "LanguageId": 1}
        reports = json.loads(fetcher.archive(base + "FinancialReport.svc/GetFinancialReportList", params))
        events = json.loads(fetcher.archive(base + "Event.svc/GetEventList", {**params, "eventSelection": 3}))
        result = select_q4_documents(ticker, reports["GetFinancialReportListResult"], events["GetEventListResult"])
    if not result.available_periods:
        raise AcquisitionError(f"{ticker}: archive contains no recognized fiscal periods; check source/parser")
    # A file may be linked both from a financial table and an event. Keep event
    # dates, but download that URL only once. Retain distinct corrected versions.
    unique: dict[str, Candidate] = {}
    for item in result.candidates:
        previous = unique.get(item.source_url)
        if previous and previous.fiscal_period != item.fiscal_period:
            raise AcquisitionError(f"conflicting fiscal periods for {item.source_url}")
        if previous is None or item.call_date:
            unique[item.source_url] = item
    result.candidates = sorted(unique.values(), key=lambda item: (item.fiscal_period, item.source_url))
    return result


def _source_date(value: str) -> str | None:
    try:
        return datetime.strptime(value.split()[0], "%m/%d/%Y").date().isoformat()
    except (ValueError, IndexError):
        return None


def _pdf_date(text: str) -> str | None:
    # Dates outside the header may refer to future conferences or disclaimers.
    # Do not use fiscal report dates or filesystem/PDF creation timestamps.
    header = text[:1200]
    numeric = re.search(r"\b(\d{2})\s*-\s*(\d{2})\s*-\s*(\d{4})\b", header)
    if numeric:
        try:
            return datetime(int(numeric[3]), int(numeric[1]), int(numeric[2])).date().isoformat()
        except ValueError:
            pass
    month = r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
    patterns = [rf"\b{month}\.?[\s-]+\d{{1,2}}[.,]?[\s-]+\d{{4}}\b", rf"\b\d{{1,2}}[\s-]+{month}\.?[\s,-]+\d{{4}}\b"]
    for pattern in patterns:
        match = re.search(pattern, header, re.I)
        if not match:
            continue
        cleaned = re.sub(r"[.,-]+", " ", match[0])
        cleaned = " ".join(cleaned.split())
        for fmt in ("%B %d %Y", "%b %d %Y", "%d %B %Y", "%d %b %Y"):
            try:
                return datetime.strptime(cleaned, fmt).date().isoformat()
            except ValueError:
                pass
    return None


def inspect_pdf(content: bytes) -> dict[str, Any]:
    """Validate PDF structure and call/Q&A content without rewriting the source."""
    if not content.startswith(b"%PDF-"):
        raise AcquisitionError("response is not a PDF (possibly an HTML error page)")
    try:
        reader = PdfReader(BytesIO(content))
        if reader.is_encrypted or not 1 <= len(reader.pages) <= 200:
            raise AcquisitionError("PDF is encrypted, empty, or exceeds 200 pages")
        texts = [page.extract_text() or "" for page in reader.pages]
    except AcquisitionError:
        raise
    except Exception as exc:
        raise AcquisitionError(f"cannot parse PDF: {exc}") from exc
    text = "\n".join(texts)
    if re.search(r"\bconference\b", texts[0], re.I) and not re.search(r"earnings|results", texts[0], re.I):
        raise AcquisitionError("PDF header identifies a non-earnings conference")
    if not re.search(r"earnings|financial results", text[:12000], re.I):
        raise AcquisitionError("PDF content does not identify an earnings/results call")
    if not _QA.search(text):
        raise AcquisitionError("PDF has no question-and-answer content; not a complete call transcript")
    return {"pages": len(texts), "call_date": _pdf_date(texts[0])}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _relative_path(candidate: Candidate) -> Path:
    original = unquote(urlsplit(candidate.source_url).path.rsplit("/", 1)[-1])
    basename = re.sub(r"[^A-Za-z0-9._+-]", "_", original)[:140]
    if not basename.lower().endswith(".pdf"):
        basename += ".pdf"
    digest = hashlib.sha256(candidate.source_url.encode()).hexdigest()[:12]
    return Path(candidate.ticker) / f"{candidate.fiscal_period}__{digest}__{basename}"


def _atomic_json(path: Path, value: object) -> None:
    staging = path.with_suffix(".json.part")
    staging.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    staging.replace(path)


def download_candidate(
    fetcher: Fetcher,
    candidate: Candidate,
    output: Path,
    *,
    previous: dict[str, Any] | None = None,
) -> dict[str, Any]:
    relative = _relative_path(candidate)
    destination = output / relative
    if not destination.resolve().is_relative_to(output.resolve()):
        raise AcquisitionError("output path escapes the raw-data directory")
    if destination.exists():
        existing = destination.read_bytes()
        checksum = hashlib.sha256(existing).hexdigest()
        if previous and previous.get("sha256") == checksum and previous.get("source_url") == candidate.source_url:
            return {**previous, "status": "existing"}
        raise AcquisitionError(f"existing file has no matching provenance/checksum: {destination}")
    content, resolved = fetcher.get(candidate.source_url)
    metadata = inspect_pdf(content)
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = destination.with_suffix(".pdf.part")
    try:
        staging.write_bytes(content)
        staging.replace(destination)
    finally:
        staging.unlink(missing_ok=True)
    call_date = candidate.call_date or metadata["call_date"]
    return {
        **asdict(candidate),
        "document_type": "earnings_call_transcript",
        "source": "investor_relations",
        "original_filename": unquote(urlsplit(candidate.source_url).path.rsplit("/", 1)[-1]),
        "resolved_url": resolved,
        "published_at": call_date,
        "publication_date_basis": (
            "official_event_start" if candidate.call_date else "pdf_header" if call_date else "not_available"
        ),
        "retrieved_at": _now(),
        "sha256": hashlib.sha256(content).hexdigest(),
        "bytes": len(content),
        "pages": metadata["pages"],
        "local_path": relative.as_posix(),
        "status": "downloaded",
    }


def coverage_summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Five-year eligibility requires five consecutive years with all four calls."""
    quarters: dict[int, set[int]] = {}
    for record in records:
        if record["status"] not in ("downloaded", "existing"):
            continue
        match = re.fullmatch(r"FY(\d{4})-Q([1-4])", record["fiscal_period"])
        if match:
            quarters.setdefault(int(match[1]), set()).add(int(match[2]))
    years = sorted(year for year, found in quarters.items() if found == {1, 2, 3, 4})
    longest = current = 0
    previous: int | None = None
    for year in years:
        current = current + 1 if previous == year - 1 else 1
        longest = max(longest, current)
        previous = year
    return {"complete_fiscal_years": years, "longest_complete_year_run": longest, "meets_five_full_years": longest >= 5}


def _manifest(
    ticker: str, discovery: Discovery, evidence: list[dict[str, Any]], records: list[dict[str, Any]]
) -> dict[str, Any]:
    found = {item.fiscal_period for item in discovery.candidates}
    saved = sorted({str(item["fiscal_period"]) for item in records if item["status"] in ("downloaded", "existing")})
    return {
        "schema_version": 1,
        "ticker": ticker,
        "updated_at": _now(),
        "archive_url": ARCHIVES[ticker],
        "scope": "all years and all items exposed by the official archive and event feed; no date cutoff",
        "selection": "complete earnings-call transcript PDFs only; excludes follow-up calls, scripts, prepared remarks, slides, releases, and investor conferences",
        "discovery_status": "complete",
        "availability": "transcript_pdf_links_found" if found else "no_transcript_pdf_links_in_checked_sources",
        "discovery_evidence": evidence,
        "archive_fiscal_periods": sorted(discovery.available_periods),
        "periods_without_transcript_pdf_link": sorted(discovery.available_periods - found),
        "periods_without_saved_transcript": sorted(discovery.available_periods - set(saved)),
        "pending_source_urls": sorted(
            {item.source_url for item in discovery.candidates} - {item["source_url"] for item in records}
        ),
        "excluded": discovery.exclusions,
        "source_anomalies": discovery.source_anomalies,
        "summary": {
            **coverage_summary(records),
            "pdf_links_found": len(discovery.candidates),
            "pdfs_saved": sum(item["status"] in ("downloaded", "existing") for item in records),
            "fiscal_periods_saved": len(saved),
            "unique_pdf_checksums": len({item["sha256"] for item in records if item.get("sha256")}),
            "total_bytes": sum(item.get("bytes", 0) for item in records),
            "failed": sum(item["status"] == "failed" for item in records),
            "earliest_saved_period": saved[0] if saved else None,
            "latest_saved_period": saved[-1] if saved else None,
            "dates_unavailable": sum(item.get("publication_date_basis") == "not_available" for item in records),
        },
        "documents": records,
    }


def run(data_root: Path, tickers: list[str], *, delay: float = 0.2) -> int:
    if not data_root.is_dir():
        raise AcquisitionError(f"data repository does not exist: {data_root}")
    output = data_root / "data" / "company_communications" / "raw"
    if not output.is_dir():
        raise AcquisitionError(f"expected the existing company-communications raw directory: {output}")
    failures = 0
    with httpx.Client(timeout=60.0, follow_redirects=False) as client:
        fetcher = Fetcher(client, delay=delay)
        for ticker in tickers:
            folder = output / ticker
            folder.mkdir(exist_ok=True)
            manifest_path = folder / "earnings_calls_manifest.json"
            previous = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
            by_url = {item["source_url"]: item for item in previous.get("documents", [])}
            fetcher.evidence = []
            try:
                discovery = discover(fetcher, ticker)
            except (AcquisitionError, ValueError, KeyError) as exc:
                failures += 1
                # Preserve any successful prior manifest and its resume checksums.
                _atomic_json(folder / "earnings_calls_discovery_error.json", {"at": _now(), "error": str(exc)})
                print(f"{ticker}: discovery failed: {exc}", flush=True)
                continue
            # Keep prior provenance until each record is refreshed, including
            # files removed from the live archive. An interruption must not make
            # already-downloaded files impossible to resume safely.
            records: list[dict[str, Any]] = list(previous.get("documents", []))
            current_urls = {item.source_url for item in discovery.candidates}
            records = [
                (
                    {**item, "status": "excluded", "exclusion_reason": "no longer selected by current discovery"}
                    if item["status"] == "failed" and item["source_url"] not in current_urls
                    else item
                )
                for item in records
            ]
            _atomic_json(manifest_path, _manifest(ticker, discovery, fetcher.evidence, records))
            print(f"{ticker}: {len(discovery.candidates)} transcript PDFs discovered", flush=True)
            for index, candidate in enumerate(discovery.candidates, 1):
                try:
                    record = download_candidate(fetcher, candidate, output, previous=by_url.get(candidate.source_url))
                except (AcquisitionError, OSError) as exc:
                    failures += 1
                    record = {**asdict(candidate), "status": "failed", "error": str(exc)}
                records = [item for item in records if item["source_url"] != candidate.source_url]
                records.append(record)
                _atomic_json(manifest_path, _manifest(ticker, discovery, fetcher.evidence, records))
                print(
                    f"  {index}/{len(discovery.candidates)} {candidate.fiscal_period}: {record['status']}", flush=True
                )
            (folder / "earnings_calls_discovery_error.json").unlink(missing_ok=True)
            print(json.dumps({"ticker": ticker, **_manifest(ticker, discovery, [], records)["summary"]}), flush=True)
    return 1 if failures else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data-root", type=Path, default=os.environ.get("SENTIMENT_DATA_ROOT"))
    parser.add_argument("--tickers", nargs="+", choices=list(ARCHIVES), default=list(DEFAULT_TICKERS))
    parser.add_argument("--delay", type=float, default=0.2, help="minimum delay between HTTP requests (seconds)")
    args = parser.parse_args()
    if args.data_root is None:
        parser.error("set SENTIMENT_DATA_ROOT or pass --data-root pointing at the data repository")
    if args.delay < 0:
        parser.error("--delay must be non-negative")
    try:
        return run(args.data_root.expanduser().resolve(), list(dict.fromkeys(args.tickers)), delay=args.delay)
    except (AcquisitionError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
