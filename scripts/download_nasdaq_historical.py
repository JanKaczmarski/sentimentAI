"""Acquire a validated Nasdaq daily-price CSV snapshot with JSON provenance."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import shutil
import sys
import tempfile
import time
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timezone
from io import StringIO
from math import isfinite
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import httpx

from sentiment_system.adapters.outbound.market_data.cached_files import CachedCsvMarketData

_API_URL = "https://api.nasdaq.com/api/quote/{symbol}/historical"
_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)
_ASSET_CLASSES = frozenset(("stocks", "etf", "index"))
_CSV_FIELDS = ("Date", "Open", "High", "Low", "Close", "Volume")
_MONEY_PATTERN = re.compile(r"^\$?([0-9,]+(?:\.[0-9]+)?)$")
_SYMBOL_PATTERN = re.compile(r"[A-Z][A-Z0-9.-]*\Z")


class NasdaqDownloadError(RuntimeError):
    """Raised when a Nasdaq response cannot produce a validated price snapshot."""


@dataclass(frozen=True, slots=True)
class DailyPrice:
    """One complete Nasdaq daily trading-price record."""

    trading_date: date
    open: float
    high: float
    low: float
    close: float
    volume: int | None

    def __post_init__(self) -> None:
        if not isinstance(self.trading_date, date) or isinstance(self.trading_date, datetime):
            raise ValueError("trading_date must be a date")
        for field in ("open", "high", "low", "close"):
            value = getattr(self, field)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value) or value <= 0:
                raise ValueError(f"{field} must be a positive finite number")
            object.__setattr__(self, field, float(value))
        if self.volume is not None and (
            isinstance(self.volume, bool) or not isinstance(self.volume, int) or self.volume < 0
        ):
            raise ValueError("volume must be a non-negative integer")


@dataclass(frozen=True, slots=True)
class DownloadedSeries:
    """Validated daily prices and provenance from one Nasdaq API response."""

    symbol: str
    asset_class: str
    requested_start: date
    requested_end: date
    retrieved_at: datetime
    source_url: str
    response_sha256: str
    prices: tuple[DailyPrice, ...]
    response_content: bytes | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "symbol", _validate_symbol(self.symbol))
        if self.asset_class not in _ASSET_CLASSES:
            raise ValueError(f"unsupported Nasdaq asset class: {self.asset_class}")
        if not isinstance(self.requested_start, date) or not isinstance(self.requested_end, date):
            raise ValueError("requested dates must be dates")
        if self.requested_start > self.requested_end:
            raise ValueError("requested start must not be after requested end")
        if not isinstance(self.retrieved_at, datetime) or self.retrieved_at.tzinfo is None:
            raise ValueError("retrieved_at must be a timezone-aware datetime")
        if not isinstance(self.source_url, str) or not self.source_url.startswith("https://api.nasdaq.com/"):
            raise ValueError("source_url must be a Nasdaq HTTPS API URL")
        if not re.fullmatch(r"[a-f0-9]{64}", self.response_sha256):
            raise ValueError("response_sha256 must be a lowercase SHA-256 hex digest")
        if (
            self.response_content is not None
            and hashlib.sha256(self.response_content).hexdigest() != self.response_sha256
        ):
            raise ValueError("raw response checksum mismatch")
        if not self.prices:
            raise ValueError("prices must not be empty")
        if any(not isinstance(price, DailyPrice) for price in self.prices):
            raise ValueError("prices must contain DailyPrice values")
        if any(
            price.trading_date < self.requested_start or price.trading_date > self.requested_end
            for price in self.prices
        ):
            raise ValueError("prices must be within the requested date range")
        if any(left.trading_date >= right.trading_date for left, right in zip(self.prices, self.prices[1:])):
            raise ValueError("prices must be strictly increasing by trading date")


def fetch_historical(
    client: httpx.Client,
    symbol: str,
    *,
    start: date,
    end: date,
    asset_class: str,
    retrieved_at: datetime | None = None,
) -> DownloadedSeries:
    """Fetch and validate one symbol's daily prices, sorted oldest first."""
    ticker = _validate_symbol(symbol)
    if asset_class not in _ASSET_CLASSES:
        raise NasdaqDownloadError(f"unsupported Nasdaq asset class: {asset_class}")
    if start > end:
        raise NasdaqDownloadError("start date must not be after end date")
    response = client.get(
        _API_URL.format(symbol=ticker),
        params={
            "assetclass": asset_class,
            "fromdate": start.isoformat(),
            "todate": end.isoformat(),
            "limit": 9999,
        },
        headers={"User-Agent": _USER_AGENT, "Accept": "application/json"},
    )
    response.raise_for_status()
    return parse_response(
        response.content,
        symbol=ticker,
        asset_class=asset_class,
        start=start,
        end=end,
        retrieved_at=retrieved_at or datetime.now(timezone.utc),
        source_url=str(response.url),
    )


def parse_response(
    content: bytes,
    *,
    symbol: str,
    asset_class: str,
    start: date,
    end: date,
    retrieved_at: datetime,
    source_url: str,
) -> DownloadedSeries:
    """Replay a saved response without provider access or invented price values."""
    ticker = _validate_symbol(symbol)
    parsed = urlsplit(source_url)
    if (
        parsed.scheme != "https"
        or parsed.netloc != "api.nasdaq.com"
        or parsed.path != f"/api/quote/{ticker}/historical"
    ):
        raise NasdaqDownloadError("raw response URL does not match the requested symbol")
    query = parse_qs(parsed.query)
    if any(
        query.get(key) != [value]
        for key, value in {"assetclass": asset_class, "fromdate": start.isoformat(), "todate": end.isoformat()}.items()
    ):
        raise NasdaqDownloadError("raw response URL does not match the requested parameters")
    if len(content) > 24 * 1024 * 1024:
        raise NasdaqDownloadError("Nasdaq response exceeds size limit")
    try:
        payload = json.loads(content)
    except (ValueError, UnicodeDecodeError) as error:
        raise NasdaqDownloadError("Nasdaq response is not JSON") from error
    if not isinstance(payload, Mapping):
        raise NasdaqDownloadError(f"Nasdaq returned a non-object response for {ticker}")
    status = payload.get("status")
    if not isinstance(status, Mapping) or status.get("rCode") != 200:
        raise NasdaqDownloadError(f"Nasdaq rejected {ticker}: {_response_message(payload, status)}")
    rows = _response_rows(payload, ticker)
    try:
        prices = tuple(sorted((_parse_row(ticker, row) for row in rows), key=lambda price: price.trading_date))
        return DownloadedSeries(
            symbol=ticker,
            asset_class=asset_class,
            requested_start=start,
            requested_end=end,
            retrieved_at=retrieved_at,
            source_url=source_url,
            response_sha256=hashlib.sha256(content).hexdigest(),
            prices=prices,
            response_content=content,
        )
    except ValueError as error:
        raise NasdaqDownloadError(f"Nasdaq returned invalid daily prices for {ticker}: {error}") from error


def write_snapshot(series: Sequence[DownloadedSeries], *, output_dir: Path) -> None:
    """Write a new, non-overwriting CSV snapshot and JSON provenance manifest."""
    if not series:
        raise NasdaqDownloadError("at least one market-price series is required")
    if output_dir.is_symlink() or output_dir.parent.is_symlink():
        raise NasdaqDownloadError("snapshot directories must not be symlinks")
    if not output_dir.parent.is_dir():
        raise NasdaqDownloadError(f"output parent directory does not exist: {output_dir.parent}")
    symbols = [item.symbol for item in series]
    if len(symbols) != len(set(symbols)):
        raise NasdaqDownloadError("each symbol may be downloaded only once")

    sorted_series = tuple(sorted(series, key=lambda item: item.symbol))
    csv_contents = {item.symbol: _csv_content(item.prices) for item in sorted_series}
    manifest = _snapshot_manifest(sorted_series, csv_contents)
    artifacts = {f"{symbol}.csv": content.encode() for symbol, content in csv_contents.items()}
    artifacts.update(
        {
            f"raw/{item.symbol}.json": item.response_content
            for item in sorted_series
            if item.response_content is not None
        }
    )
    artifacts["market_prices.json"] = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode()
    if output_dir.exists():
        _verify_artifacts(output_dir, artifacts)
        return
    staging = Path(tempfile.mkdtemp(prefix=f".{output_dir.name}-", dir=output_dir.parent))
    try:
        for relative, raw in artifacts.items():
            path = staging / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
        staging.rename(output_dir)
    finally:
        if staging.exists():
            shutil.rmtree(staging)


def _verify_artifacts(folder: Path, artifacts: Mapping[str, bytes]) -> None:
    paths = tuple(folder.rglob("*"))
    if any(path.is_symlink() for path in paths) or folder.is_symlink():
        raise NasdaqDownloadError("snapshot must not contain symlinks")
    if {path.relative_to(folder).as_posix() for path in paths if path.is_file()} != set(artifacts):
        raise NasdaqDownloadError("snapshot artifact set changed")
    for relative, content in artifacts.items():
        if (folder / relative).read_bytes() != content:
            raise NasdaqDownloadError(f"snapshot artifact checksum mismatch: {relative}")


def verify_snapshot(
    folder: Path,
    *,
    requested_series: Sequence[tuple[str, str]] | None = None,
    start: date | None = None,
    end: date | None = None,
) -> None:
    """Verify all saved responses and reproduce every CSV and manifest offline."""
    if folder.is_symlink() or (folder / "market_prices.json").is_symlink():
        raise NasdaqDownloadError("snapshot must not contain symlinks")
    CachedCsvMarketData(folder)
    manifest = json.loads((folder / "market_prices.json").read_bytes())
    if manifest["provider"] != "nasdaq":
        raise NasdaqDownloadError("snapshot provider must be nasdaq")
    if requested_series is not None and sorted(requested_series) != sorted(
        (item["symbol"], item["asset_class"]) for item in manifest["series"]
    ):
        raise NasdaqDownloadError("requested symbols/asset classes differ from frozen snapshot")
    reconstructed = []
    for item in manifest["series"]:
        if (start is not None and item["requested_start"] != start.isoformat()) or (
            end is not None and item["requested_end"] != end.isoformat()
        ):
            raise NasdaqDownloadError("requested dates differ from frozen snapshot")
        symbol = _validate_symbol(item["symbol"])
        relative = f"raw/{symbol}.json"
        if item.get("response_file") != relative or (folder / "raw").is_symlink() or (folder / relative).is_symlink():
            raise NasdaqDownloadError("missing or unsafe raw response path")
        content = (folder / relative).read_bytes()
        if hashlib.sha256(content).hexdigest() != item["response_sha256"]:
            raise NasdaqDownloadError("raw response checksum mismatch")
        reconstructed.append(
            parse_response(
                content,
                symbol=symbol,
                asset_class=item["asset_class"],
                start=date.fromisoformat(item["requested_start"]),
                end=date.fromisoformat(item["requested_end"]),
                retrieved_at=datetime.fromisoformat(item["retrieved_at"]),
                source_url=item["source_url"],
            )
        )
    write_snapshot(reconstructed, output_dir=folder)


def _response_rows(payload: Mapping[str, object], symbol: str) -> tuple[Mapping[str, object], ...]:
    data = payload.get("data")
    if not isinstance(data, Mapping):
        raise NasdaqDownloadError(f"Nasdaq returned no historical data for {symbol}")
    table = data.get("tradesTable")
    if not isinstance(table, Mapping):
        raise NasdaqDownloadError(f"Nasdaq returned no historical table for {symbol}")
    rows = table.get("rows")
    if not isinstance(rows, list) or not rows:
        raise NasdaqDownloadError(f"Nasdaq returned no historical rows for {symbol}")
    if any(not isinstance(row, Mapping) for row in rows):
        raise NasdaqDownloadError(f"Nasdaq returned malformed historical rows for {symbol}")
    if data.get("symbol", symbol) != symbol:
        raise NasdaqDownloadError("Nasdaq response symbol does not match requested symbol")
    if "totalRecords" in data:
        try:
            count = int(str(data["totalRecords"]).replace(",", ""))
        except ValueError as error:
            raise NasdaqDownloadError("invalid Nasdaq totalRecords") from error
        if count != len(rows):
            raise NasdaqDownloadError("Nasdaq historical response is truncated")
    return tuple(rows)


def _response_message(payload: Mapping[str, object], status: Mapping[str, object] | object) -> str:
    messages = status.get("bCodeMessage") if isinstance(status, Mapping) else None
    if isinstance(messages, list):
        errors: list[str] = []
        for message in messages:
            error_message = message.get("errorMessage") if isinstance(message, Mapping) else None
            if isinstance(error_message, str):
                errors.append(error_message)
        if errors:
            return "; ".join(errors)
    message = payload.get("message")
    return message if isinstance(message, str) else "no error detail"


def _parse_row(symbol: str, row: Mapping[str, object]) -> DailyPrice:
    try:
        month, day, year = _row_value(row, "date").split("/")
        return DailyPrice(
            trading_date=date(int(year), int(month), int(day)),
            open=_money(_row_value(row, "open")),
            high=_money(_row_value(row, "high")),
            low=_money(_row_value(row, "low")),
            close=_money(_row_value(row, "close")),
            volume=_volume(_row_value(row, "volume")),
        )
    except (KeyError, ValueError) as error:
        raise NasdaqDownloadError(f"Nasdaq returned an unparseable row for {symbol}: {row!r}") from error


def _row_value(row: Mapping[str, object], field: str) -> str:
    value = row[field]
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string")
    return value


def _volume(value: str) -> int | None:
    stripped = value.strip()
    if stripped in {"", "N/A"}:
        return None
    if not re.fullmatch(r"[0-9][0-9,]*", stripped):
        raise ValueError(f"not a volume: {value!r}")
    return int(stripped.replace(",", ""))


def _money(value: str) -> float:
    match = _MONEY_PATTERN.fullmatch(value.strip())
    if match is None:
        raise ValueError(f"not a price: {value!r}")
    return float(match.group(1).replace(",", ""))


def _csv_content(prices: Iterable[DailyPrice]) -> str:
    handle = StringIO(newline="")
    writer = csv.writer(handle)
    writer.writerow(_CSV_FIELDS)
    for price in prices:
        writer.writerow((price.trading_date.isoformat(), price.open, price.high, price.low, price.close, price.volume))
    return handle.getvalue()


def _write_csv(path: Path, content: str) -> None:
    with path.open("x", encoding="utf-8", newline="") as handle:
        handle.write(content)


def _snapshot_manifest(series: Sequence[DownloadedSeries], csv_contents: Mapping[str, str]) -> dict[str, object]:
    return {
        "csv_fields": list(_CSV_FIELDS),
        "nullable_csv_fields": ["Volume"],
        "price_frequency": "daily_trading_day",
        "provider": "nasdaq",
        "return_price_field": "Close",
        "schema_version": 1,
        "series": [
            {
                "asset_class": item.asset_class,
                "csv_file": f"{item.symbol}.csv",
                "csv_sha256": hashlib.sha256(csv_contents[item.symbol].encode("utf-8")).hexdigest(),
                "first_trading_date": item.prices[0].trading_date.isoformat(),
                "last_trading_date": item.prices[-1].trading_date.isoformat(),
                "requested_end": item.requested_end.isoformat(),
                "requested_start": item.requested_start.isoformat(),
                "response_sha256": item.response_sha256,
                **({"response_file": f"raw/{item.symbol}.json"} if item.response_content is not None else {}),
                "retrieved_at": item.retrieved_at.isoformat(),
                "rows": len(item.prices),
                "source_url": item.source_url,
                "symbol": item.symbol,
            }
            for item in series
        ],
    }


def _validate_symbol(value: str) -> str:
    symbol = value.strip().upper()
    if not _SYMBOL_PATTERN.fullmatch(symbol):
        raise ValueError("Nasdaq symbols must use uppercase ticker syntax")
    return symbol


def _series_argument(value: str) -> tuple[str, str]:
    symbol, separator, asset_class = value.partition(":")
    if not separator:
        raise argparse.ArgumentTypeError("series must use SYMBOL:asset_class, for example AAPL:stocks")
    try:
        ticker = _validate_symbol(symbol)
    except ValueError as error:
        raise argparse.ArgumentTypeError(str(error)) from error
    if asset_class not in _ASSET_CLASSES:
        raise argparse.ArgumentTypeError(f"asset class must be one of: {', '.join(sorted(_ASSET_CLASSES))}")
    return ticker, asset_class


def main(argv: list[str] | None = None) -> int:
    """Download a reproducible Nasdaq price snapshot."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--series", type=_series_argument, action="append", required=True)
    parser.add_argument("--start", type=date.fromisoformat, required=True, help="First requested date, ISO format")
    parser.add_argument("--end", type=date.fromisoformat, required=True, help="Last requested date, ISO format")
    parser.add_argument(
        "--output-dir", type=Path, required=True, help="New directory for CSV files and market_prices.json"
    )
    parser.add_argument("--delay", type=float, default=1.5, help="Seconds to wait between requests")
    arguments = parser.parse_args(argv)
    if arguments.start > arguments.end:
        parser.error("--start must not be after --end")
    if arguments.delay < 0:
        parser.error("--delay must not be negative")
    if not arguments.output_dir.parent.is_dir():
        parser.error(f"output parent directory does not exist: {arguments.output_dir.parent}")
    if len({symbol for symbol, _ in arguments.series}) != len(arguments.series):
        parser.error("each --series symbol may be supplied only once")
    if arguments.output_dir.exists() or arguments.output_dir.is_symlink():
        verify_snapshot(
            arguments.output_dir, requested_series=arguments.series, start=arguments.start, end=arguments.end
        )
        print(f"Verified existing snapshot offline: {arguments.output_dir}")
        return 0

    downloaded: list[DownloadedSeries] = []
    with httpx.Client(timeout=30.0, follow_redirects=True) as client:
        for index, (symbol, asset_class) in enumerate(arguments.series):
            if index > 0:
                time.sleep(arguments.delay)
            try:
                downloaded.append(
                    fetch_historical(
                        client,
                        symbol,
                        start=arguments.start,
                        end=arguments.end,
                        asset_class=asset_class,
                    )
                )
            except (httpx.HTTPError, NasdaqDownloadError, ValueError) as error:
                print(f"FAILED {symbol}: {error}", file=sys.stderr)
                return 1
    try:
        write_snapshot(tuple(downloaded), output_dir=arguments.output_dir)
    except NasdaqDownloadError as error:
        print(f"FAILED to write snapshot: {error}", file=sys.stderr)
        return 1
    for item in sorted(downloaded, key=lambda value: value.symbol):
        print(
            f"{item.symbol}: wrote {len(item.prices)} rows "
            f"({item.prices[0].trading_date} to {item.prices[-1].trading_date})"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
