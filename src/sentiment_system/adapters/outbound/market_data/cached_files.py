"""Validated offline market-price snapshot adapter."""

import csv
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date, datetime
from io import StringIO
from math import isfinite
from pathlib import Path
from typing import cast

from sentiment_system.application.ports.market_data import PricePoint

_CSV_FIELDS = ("Date", "Open", "High", "Low", "Close", "Volume")
_NULLABLE_CSV_FIELDS = ("Volume",)
_MAX_CSV_BYTES = 16 * 1024 * 1024
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")


class MarketDataCacheError(ValueError):
    """Raised when an immutable market-price snapshot is invalid."""


@dataclass(frozen=True, slots=True)
class _Series:
    symbol: str
    csv_file: str
    csv_sha256: str
    rows: int
    first_trading_date: date
    last_trading_date: date


class CachedCsvMarketData:
    """Load a verified provider-neutral CSV snapshot without network access."""

    def __init__(self, snapshot_dir: Path) -> None:
        if not snapshot_dir.is_dir():
            raise MarketDataCacheError(f"market-price snapshot directory does not exist: {snapshot_dir}")
        self._snapshot_dir = snapshot_dir
        self._prices = self._load_prices()

    def get_prices(
        self,
        symbol: str,
        *,
        start: date | None = None,
        end: date | None = None,
    ) -> tuple[PricePoint, ...]:
        """Return one symbol's verified closes with inclusive date bounds."""
        return tuple(
            point
            for point in self._prices.get(symbol, ())
            if (start is None or point.trading_date >= start) and (end is None or point.trading_date <= end)
        )

    def _load_prices(self) -> dict[str, tuple[PricePoint, ...]]:
        manifest = _read_manifest(self._snapshot_dir / "market_prices.json")
        series = _parse_manifest(manifest)
        return {item.symbol: self._load_series(item) for item in series}

    def _load_series(self, series: _Series) -> tuple[PricePoint, ...]:
        path = self._snapshot_dir / series.csv_file
        if path.is_symlink() or not path.is_file():
            raise MarketDataCacheError(f"missing regular cached CSV file: {path}")
        content = _read_verified_csv(path, series.csv_sha256)
        points = _parse_csv(path, content, series.symbol)
        if len(points) != series.rows:
            raise MarketDataCacheError(f"row count mismatch for {path}: expected {series.rows}, found {len(points)}")
        if points[0].trading_date != series.first_trading_date or points[-1].trading_date != series.last_trading_date:
            raise MarketDataCacheError(f"trading-date metadata mismatch for {path}")
        return points


def _read_manifest(path: Path) -> dict[str, object]:
    if path.is_symlink() or not path.is_file():
        raise MarketDataCacheError(f"missing regular market-price manifest: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise MarketDataCacheError(f"cannot read market-price manifest: {path}") from error
    if not isinstance(payload, dict) or any(not isinstance(key, str) for key in payload):
        raise MarketDataCacheError(f"market-price manifest must be an object: {path}")
    return cast(dict[str, object], payload)


def _parse_manifest(manifest: dict[str, object]) -> tuple[_Series, ...]:
    if manifest.get("schema_version") != 1:
        raise MarketDataCacheError("market-price manifest schema_version must be 1")
    if _string_list(manifest, "csv_fields") != _CSV_FIELDS:
        raise MarketDataCacheError(f"market-price manifest csv_fields must be {list(_CSV_FIELDS)!r}")
    if _string_list(manifest, "nullable_csv_fields") != _NULLABLE_CSV_FIELDS:
        raise MarketDataCacheError(f"market-price manifest nullable_csv_fields must be {list(_NULLABLE_CSV_FIELDS)!r}")
    if _string(manifest, "price_frequency") != "daily_trading_day":
        raise MarketDataCacheError("market-price manifest price_frequency must be daily_trading_day")
    if _string(manifest, "return_price_field") != "Close":
        raise MarketDataCacheError("market-price manifest return_price_field must be Close")
    _string(manifest, "provider")
    values = manifest.get("series")
    if not isinstance(values, list) or not values:
        raise MarketDataCacheError("market-price manifest series must be a non-empty list")

    parsed = tuple(_parse_series(value) for value in values)
    symbols = {item.symbol for item in parsed}
    filenames = {item.csv_file for item in parsed}
    if len(symbols) != len(parsed):
        raise MarketDataCacheError("market-price manifest series symbols must be unique")
    if len(filenames) != len(parsed):
        raise MarketDataCacheError("market-price manifest CSV filenames must be unique")
    return parsed


def _parse_series(value: object) -> _Series:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise MarketDataCacheError("market-price manifest contains an invalid series")
    series = cast(dict[str, object], value)
    _string(series, "asset_class")
    csv_file = _string(series, "csv_file")
    csv_path = Path(csv_file)
    if csv_file != csv_path.name or csv_path.suffix != ".csv":
        raise MarketDataCacheError(f"CSV file must be a direct child .csv file: {csv_file}")
    csv_sha256 = _sha256(series, "csv_sha256")
    first = _date(series, "first_trading_date")
    last = _date(series, "last_trading_date")
    requested_start = _date(series, "requested_start")
    requested_end = _date(series, "requested_end")
    if first > last:
        raise MarketDataCacheError("first_trading_date must not be after last_trading_date")
    if requested_start > requested_end:
        raise MarketDataCacheError("requested_start must not be after requested_end")
    if first < requested_start or last > requested_end:
        raise MarketDataCacheError("actual trading dates must be within requested dates")
    _sha256(series, "response_sha256")
    _timestamp(series, "retrieved_at")
    _string(series, "source_url")
    rows = _positive_int(series, "rows")
    return _Series(
        symbol=_string(series, "symbol"),
        csv_file=csv_file,
        csv_sha256=csv_sha256,
        rows=rows,
        first_trading_date=first,
        last_trading_date=last,
    )


def _read_verified_csv(path: Path, expected_hash: str) -> str:
    try:
        raw_content = path.read_bytes()
    except OSError as error:
        raise MarketDataCacheError(f"cannot read cached CSV file: {path}") from error
    if len(raw_content) > _MAX_CSV_BYTES:
        raise MarketDataCacheError(f"cached CSV file exceeds {_MAX_CSV_BYTES} bytes: {path}")
    actual_hash = hashlib.sha256(raw_content).hexdigest()
    if actual_hash != expected_hash:
        raise MarketDataCacheError(f"checksum mismatch for {path}")
    try:
        return raw_content.decode("utf-8")
    except UnicodeDecodeError as error:
        raise MarketDataCacheError(f"cached CSV file is not UTF-8: {path}") from error


def _parse_csv(path: Path, content: str, symbol: str) -> tuple[PricePoint, ...]:
    reader = csv.reader(StringIO(content), strict=True)
    try:
        header = next(reader, None)
        if header != list(_CSV_FIELDS):
            raise MarketDataCacheError(f"CSV schema mismatch for {path}")
        points: list[PricePoint] = []
        previous_date: date | None = None
        for line_number, row in enumerate(reader, start=2):
            if len(row) != len(_CSV_FIELDS):
                raise MarketDataCacheError(f"CSV row has an invalid column count at {path}:{line_number}")
            if any(not value.strip() for value in row[1:5]):
                raise MarketDataCacheError(f"CSV row has a missing OHLC price at {path}:{line_number}")
            trading_date = _csv_date(row[0], path, line_number)
            if previous_date is not None and trading_date <= previous_date:
                raise MarketDataCacheError(f"CSV trading dates must be strictly increasing at {path}:{line_number}")
            point = _price_point(symbol, trading_date, row[4], path, line_number)
            points.append(point)
            previous_date = trading_date
    except csv.Error as error:
        raise MarketDataCacheError(f"invalid CSV syntax in {path}") from error
    if not points:
        raise MarketDataCacheError(f"cached CSV file has no price rows: {path}")
    return tuple(points)


def _price_point(symbol: str, trading_date: date, raw_close: str, path: Path, line_number: int) -> PricePoint:
    try:
        close = float(raw_close)
    except ValueError as error:
        raise MarketDataCacheError(f"invalid Close price at {path}:{line_number}") from error
    if not isfinite(close) or close <= 0:
        raise MarketDataCacheError(f"invalid Close price at {path}:{line_number}")
    return PricePoint(symbol, trading_date, close)


def _csv_date(value: str, path: Path, line_number: int) -> date:
    try:
        parsed = date.fromisoformat(value)
    except ValueError as error:
        raise MarketDataCacheError(f"invalid Date value at {path}:{line_number}") from error
    if value != parsed.isoformat():
        raise MarketDataCacheError(f"invalid Date value at {path}:{line_number}")
    return parsed


def _string(payload: dict[str, object], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise MarketDataCacheError(f"market-price manifest field {key} is required")
    return value


def _string_list(payload: dict[str, object], key: str) -> tuple[str, ...]:
    value = payload.get(key)
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise MarketDataCacheError(f"market-price manifest field {key} must be a string list")
    return tuple(value)


def _sha256(payload: dict[str, object], key: str) -> str:
    value = _string(payload, key)
    if _SHA256_PATTERN.fullmatch(value) is None:
        raise MarketDataCacheError(f"market-price manifest field {key} must be a lowercase SHA-256 hash")
    return value


def _date(payload: dict[str, object], key: str) -> date:
    value = _string(payload, key)
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise MarketDataCacheError(f"market-price manifest field {key} must be an ISO date") from error


def _timestamp(payload: dict[str, object], key: str) -> datetime:
    value = _string(payload, key)
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise MarketDataCacheError(f"market-price manifest field {key} must be an ISO timestamp") from error
    if parsed.tzinfo is None:
        raise MarketDataCacheError(f"market-price manifest field {key} must include a timezone")
    return parsed


def _positive_int(payload: dict[str, object], key: str) -> int:
    value = payload.get(key)
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise MarketDataCacheError(f"market-price manifest field {key} must be a positive integer")
    return value
