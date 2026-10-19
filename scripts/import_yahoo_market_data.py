"""Convert saved Yahoo Finance chart pages into provenance-validated CSV snapshots."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timezone
from io import StringIO
from math import isfinite
from pathlib import Path
from urllib.parse import unquote, urlsplit

from bs4 import BeautifulSoup
from bs4.element import Tag

_MAX_SOURCE_BYTES = 25 * 1024 * 1024
_SYMBOL_PATTERN = re.compile(r"(?:\^[A-Z][A-Z0-9.-]*|[A-Z][A-Z0-9.-]*)\Z")
_YAHOO_CHART_PATH_PREFIX = "/v8/finance/chart/"
_CSV_FIELDS = ("Date", "Open", "High", "Low", "Close", "Adj Close", "Volume")


class MarketDataImportError(ValueError):
    """Raised when a saved Yahoo Finance page cannot produce valid daily prices."""


@dataclass(frozen=True, slots=True)
class MarketPriceRow:
    """One complete daily Yahoo Finance price record."""

    trading_date: date
    open: float
    high: float
    low: float
    close: float
    adjusted_close: float
    volume: float


@dataclass(frozen=True, slots=True)
class ImportedMarketSeries:
    """Validated price rows and provenance extracted from one saved source page."""

    symbol: str
    source_url: str
    source_sha256: str
    prices: tuple[MarketPriceRow, ...]


def import_saved_page(path: Path, *, expected_symbol: str) -> ImportedMarketSeries:
    """Load one saved HTML page and validate its embedded daily chart response."""
    symbol = _validate_symbol(expected_symbol)
    source = _read_source(path)
    script = _find_chart_script(source, symbol)
    payload = _chart_payload(script)
    result = _chart_result(payload)
    actual_symbol = _mapping_string(_mapping_value(result, "meta"), "symbol")
    if actual_symbol != symbol:
        raise MarketDataImportError(f"Yahoo chart symbol {actual_symbol} does not match requested symbol {symbol}")
    source_url = _script_url(script, symbol)
    if source_url is None:
        raise MarketDataImportError(f"Yahoo chart response URL does not match {symbol}")
    return ImportedMarketSeries(
        symbol=symbol,
        source_url=source_url,
        source_sha256=hashlib.sha256(source).hexdigest(),
        prices=_price_rows(result),
    )


def write_snapshot(series: Sequence[ImportedMarketSeries], *, output_dir: Path, snapshot_date: date) -> None:
    """Write or safely extend a CSV snapshot and its provenance README."""
    if not series:
        raise MarketDataImportError("at least one market-price series is required")
    if not output_dir.parent.is_dir():
        raise MarketDataImportError(f"output parent directory does not exist: {output_dir.parent}")
    symbols = [item.symbol for item in series]
    if len(set(symbols)) != len(symbols):
        raise MarketDataImportError("each symbol may be imported only once")

    sorted_series = tuple(sorted(series, key=lambda value: value.symbol))
    csv_contents = {item.symbol: _csv_content(item.prices) for item in sorted_series}
    if output_dir.exists():
        _validate_existing_snapshot(output_dir, csv_contents)
    else:
        output_dir.mkdir()

    for symbol, content in csv_contents.items():
        path = output_dir / f"{symbol}.csv"
        if not path.exists():
            _write_csv(path, content)
    (output_dir / "README.md").write_text(_snapshot_readme(sorted_series, snapshot_date), encoding="utf-8")


def _validate_existing_snapshot(output_dir: Path, csv_contents: Mapping[str, str]) -> None:
    if not output_dir.is_dir():
        raise MarketDataImportError(f"output path is not a directory: {output_dir}")
    expected_names = {"README.md", *(f"{symbol}.csv" for symbol in csv_contents)}
    unexpected_names = sorted(path.name for path in output_dir.iterdir() if path.name not in expected_names)
    if unexpected_names:
        raise MarketDataImportError(
            f"existing snapshot contains files not supplied for re-import: {', '.join(unexpected_names)}"
        )
    for symbol, content in csv_contents.items():
        path = output_dir / f"{symbol}.csv"
        if not path.exists():
            continue
        if not path.is_file() or path.read_bytes() != content.encode("utf-8"):
            raise MarketDataImportError(f"existing CSV does not match re-imported source: {path}")
    readme_path = output_dir / "README.md"
    if readme_path.exists() and not readme_path.is_file():
        raise MarketDataImportError(f"existing snapshot README is not a file: {readme_path}")


def _read_source(path: Path) -> bytes:
    if path.suffix.casefold() not in {".htm", ".html"}:
        raise MarketDataImportError("source files must use the .htm or .html extension")
    if not path.is_file():
        raise MarketDataImportError(f"source file does not exist: {path}")
    if path.stat().st_size > _MAX_SOURCE_BYTES:
        raise MarketDataImportError(f"source file exceeds {_MAX_SOURCE_BYTES} bytes: {path}")
    return path.read_bytes()


def _find_chart_script(source: bytes, symbol: str) -> Tag:
    try:
        soup = BeautifulSoup(source.decode("utf-8"), "html.parser")
    except UnicodeDecodeError as error:
        raise MarketDataImportError("source page is not UTF-8 HTML") from error

    matches = [
        script
        for script in soup.find_all("script")
        if isinstance(script, Tag) and _script_url(script, symbol, required=False) is not None
    ]
    if len(matches) != 1:
        raise MarketDataImportError(f"expected one Yahoo daily chart response for {symbol}, found {len(matches)}")
    return matches[0]


def _script_url(script: Tag, symbol: str, *, required: bool = True) -> str | None:
    data_url = script.get("data-url")
    if not isinstance(data_url, str):
        if required:
            raise MarketDataImportError("Yahoo chart response has no URL")
        return None
    parsed = urlsplit(data_url)
    path = unquote(parsed.path)
    expected_path = f"{_YAHOO_CHART_PATH_PREFIX}{symbol}"
    if parsed.scheme != "https" or parsed.netloc != "query1.finance.yahoo.com" or path != expected_path:
        if required:
            raise MarketDataImportError(f"Yahoo chart response URL does not match {symbol}")
        return None
    return data_url


def _chart_payload(script: Tag) -> Mapping[str, object]:
    try:
        envelope = json.loads(script.get_text())
    except json.JSONDecodeError as error:
        raise MarketDataImportError("Yahoo chart response is not valid JSON") from error
    if not isinstance(envelope, Mapping):
        raise MarketDataImportError("Yahoo chart response must be a JSON object")
    body = envelope.get("body")
    if not isinstance(body, str):
        raise MarketDataImportError("Yahoo chart response has no JSON body")
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as error:
        raise MarketDataImportError("Yahoo chart payload is not valid JSON") from error
    if not isinstance(payload, Mapping):
        raise MarketDataImportError("Yahoo chart payload must be a JSON object")
    return payload


def _chart_result(payload: Mapping[str, object]) -> Mapping[str, object]:
    chart = _mapping_value(payload, "chart")
    results = chart.get("result")
    if not isinstance(results, list) or len(results) != 1 or not isinstance(results[0], Mapping):
        raise MarketDataImportError("Yahoo chart payload must contain exactly one result")
    return results[0]


def _price_rows(result: Mapping[str, object]) -> tuple[MarketPriceRow, ...]:
    timestamps = _number_sequence(result, "timestamp")
    indicators = _mapping_value(result, "indicators")
    quotes = indicators.get("quote")
    adjusted_closes = indicators.get("adjclose")
    if (
        not isinstance(quotes, list)
        or len(quotes) != 1
        or not isinstance(quotes[0], Mapping)
        or not isinstance(adjusted_closes, list)
        or len(adjusted_closes) != 1
        or not isinstance(adjusted_closes[0], Mapping)
    ):
        raise MarketDataImportError("Yahoo chart payload has invalid daily indicators")
    quote = quotes[0]
    adjusted_close = adjusted_closes[0]
    fields = {
        "open": _number_sequence(quote, "open"),
        "high": _number_sequence(quote, "high"),
        "low": _number_sequence(quote, "low"),
        "close": _number_sequence(quote, "close"),
        "adjclose": _number_sequence(adjusted_close, "adjclose"),
        "volume": _number_sequence(quote, "volume"),
    }
    lengths = {len(timestamps), *(len(values) for values in fields.values())}
    if len(lengths) != 1 or not timestamps:
        raise MarketDataImportError("Yahoo daily indicator lengths do not match")

    rows = tuple(
        MarketPriceRow(
            trading_date=_trading_date(timestamps[index]),
            open=_price_value(fields["open"][index], "open"),
            high=_price_value(fields["high"][index], "high"),
            low=_price_value(fields["low"][index], "low"),
            close=_price_value(fields["close"][index], "close"),
            adjusted_close=_price_value(fields["adjclose"][index], "adjclose"),
            volume=_volume_value(fields["volume"][index]),
        )
        for index in range(len(timestamps))
    )
    if any(left.trading_date >= right.trading_date for left, right in zip(rows, rows[1:])):
        raise MarketDataImportError("Yahoo daily prices must have strictly increasing trading dates")
    return rows


def _number_sequence(container: Mapping[str, object], field: str) -> list[object]:
    values = container.get(field)
    if not isinstance(values, list):
        raise MarketDataImportError(f"Yahoo chart field {field} must be an array")
    return values


def _trading_date(value: object) -> date:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value):
        raise MarketDataImportError("Yahoo timestamp must be a finite Unix timestamp")
    return datetime.fromtimestamp(value, tz=timezone.utc).date()


def _price_value(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value) or value <= 0:
        raise MarketDataImportError(f"Yahoo {field} must be a positive finite number")
    return float(value)


def _volume_value(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value) or value < 0:
        raise MarketDataImportError("Yahoo volume must be a non-negative finite number")
    return float(value)


def _mapping_value(container: Mapping[str, object], field: str) -> Mapping[str, object]:
    value = container.get(field)
    if not isinstance(value, Mapping):
        raise MarketDataImportError(f"Yahoo chart field {field} must be an object")
    return value


def _mapping_string(container: Mapping[str, object], field: str) -> str:
    value = container.get(field)
    if not isinstance(value, str):
        raise MarketDataImportError(f"Yahoo chart field {field} must be a string")
    return value


def _csv_content(prices: Iterable[MarketPriceRow]) -> str:
    handle = StringIO(newline="")
    writer = csv.writer(handle)
    writer.writerow(_CSV_FIELDS)
    for price in prices:
        writer.writerow(
            (
                price.trading_date.isoformat(),
                price.open,
                price.high,
                price.low,
                price.close,
                price.adjusted_close,
                price.volume,
            )
        )
    return handle.getvalue()


def _write_csv(path: Path, content: str) -> None:
    with path.open("x", encoding="utf-8", newline="") as handle:
        handle.write(content)


def _snapshot_readme(series: Sequence[ImportedMarketSeries], snapshot_date: date) -> str:
    lines = [
        "# Yahoo Finance Market Price Snapshot",
        "",
        f"This snapshot was extracted on {snapshot_date.isoformat()} from saved Yahoo Finance HTML pages.",
        "The source pages were parsed offline; no network request is made while reading these CSV files.",
        "",
        "## CSV Layout",
        "",
        "Each file is named after its Yahoo symbol and is sorted in ascending trading-date order.",
        "The files use UTF-8 CSV with this header:",
        "",
        "```text",
        ",".join(_CSV_FIELDS),
        "```",
        "",
        "`Date` is an ISO-8601 trading date. `Open`, `High`, `Low`, and `Close` are Yahoo's daily",
        "unadjusted prices. `Adj Close` is Yahoo's adjusted-close value. `Volume` is the daily traded volume.",
        "The evaluation adapter must explicitly select its return-price field; this snapshot preserves both values.",
        "",
        "## Provenance",
        "",
        "| Symbol | Rows | First date | Last date | Saved-source SHA-256 |",
        "|---|---:|---|---|---|",
    ]
    for item in sorted(series, key=lambda value: value.symbol):
        lines.append(
            f"| `{item.symbol}` | {len(item.prices)} | {item.prices[0].trading_date.isoformat()} | "
            f"{item.prices[-1].trading_date.isoformat()} | `{item.source_sha256}` |"
        )
        lines.extend(("", f"Source URL for `{item.symbol}`: `{item.source_url}`"))
    lines.extend(
        (
            "",
            "This is a development snapshot, not the final thesis evaluation manifest. It does not replace the",
            "top-level Kaggle-derived market-price files in the parent directory.",
            "",
        )
    )
    return "\n".join(lines)


def _validate_symbol(value: str) -> str:
    symbol = value.strip().upper()
    if not _SYMBOL_PATTERN.fullmatch(symbol):
        raise MarketDataImportError("symbols must use Yahoo's uppercase ticker syntax")
    return symbol


def _source_argument(value: str) -> tuple[str, Path]:
    symbol, separator, raw_path = value.partition("=")
    if not separator or not raw_path:
        raise argparse.ArgumentTypeError("sources must use SYMBOL=/absolute/path/to/page.html")
    path = Path(raw_path)
    if not path.is_absolute():
        raise argparse.ArgumentTypeError("source paths must be absolute")
    try:
        return _validate_symbol(symbol), path
    except MarketDataImportError as error:
        raise argparse.ArgumentTypeError(str(error)) from error


def main() -> int:
    """Import saved Yahoo Finance HTML pages into one new CSV snapshot directory."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--snapshot-date", type=date.fromisoformat, required=True)
    parser.add_argument("--source", type=_source_argument, action="append", required=True)
    arguments = parser.parse_args()
    sources = arguments.source
    symbols = [symbol for symbol, _ in sources]
    if len(symbols) != len(set(symbols)):
        parser.error("each --source symbol may be supplied only once")
    try:
        series = tuple(import_saved_page(path, expected_symbol=symbol) for symbol, path in sources)
        write_snapshot(series, output_dir=arguments.output_dir, snapshot_date=arguments.snapshot_date)
    except MarketDataImportError as error:
        parser.error(str(error))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
