"""Tests for offline Yahoo Finance market-price snapshot imports."""

import json
from datetime import date
from pathlib import Path

import pytest

from scripts.import_yahoo_market_data import MarketDataImportError, import_saved_page, write_snapshot


def test_import_saved_page_reads_valid_daily_prices(tmp_path: Path) -> None:
    source = _write_page(tmp_path / "aapl.html", symbol="AAPL")

    imported = import_saved_page(source, expected_symbol="AAPL")

    assert imported.symbol == "AAPL"
    assert imported.source_url.endswith("interval=1d&region=US")
    assert [item.trading_date for item in imported.prices] == [date(2025, 1, 2), date(2025, 1, 3)]
    assert imported.prices[0].close == 102.0
    assert imported.prices[0].adjusted_close == 101.0


def test_import_saved_page_rejects_a_symbol_mismatch(tmp_path: Path) -> None:
    source = _write_page(tmp_path / "amat.html", symbol="AMAT")

    with pytest.raises(MarketDataImportError, match="found 0"):
        import_saved_page(source, expected_symbol="AAPL")


def test_write_snapshot_safely_extends_a_matching_snapshot(tmp_path: Path) -> None:
    imported = import_saved_page(_write_page(tmp_path / "aapl.html", symbol="AAPL"), expected_symbol="AAPL")
    additional = import_saved_page(_write_page(tmp_path / "amat.html", symbol="AMAT"), expected_symbol="AMAT")
    output_dir = tmp_path / "snapshot"

    write_snapshot((imported,), output_dir=output_dir, snapshot_date=date(2026, 9, 26))
    write_snapshot((imported, additional), output_dir=output_dir, snapshot_date=date(2026, 9, 26))

    assert (output_dir / "AAPL.csv").read_text(encoding="utf-8") == (
        "Date,Open,High,Low,Close,Adj Close,Volume\n"
        "2025-01-02,100.0,103.0,99.0,102.0,101.0,1000.0\n"
        "2025-01-03,101.0,104.0,100.0,103.0,102.0,2000.0\n"
    )
    assert (output_dir / "AMAT.csv").exists()
    readme = (output_dir / "README.md").read_text(encoding="utf-8")
    assert "Yahoo Finance Market Price Snapshot" in readme
    assert "`AAPL` | 2 | 2025-01-02 | 2025-01-03" in readme
    assert "`AMAT` | 2 | 2025-01-02 | 2025-01-03" in readme


def test_write_snapshot_rejects_a_changed_existing_csv(tmp_path: Path) -> None:
    imported = import_saved_page(_write_page(tmp_path / "aapl.html", symbol="AAPL"), expected_symbol="AAPL")
    output_dir = tmp_path / "snapshot"
    write_snapshot((imported,), output_dir=output_dir, snapshot_date=date(2026, 9, 26))
    (output_dir / "AAPL.csv").write_text("changed\n", encoding="utf-8")

    with pytest.raises(MarketDataImportError, match="does not match"):
        write_snapshot((imported,), output_dir=output_dir, snapshot_date=date(2026, 9, 26))


def _write_page(path: Path, *, symbol: str) -> Path:
    timestamps = [1735831800, 1735918200]
    chart = {
        "chart": {
            "result": [
                {
                    "meta": {"symbol": symbol},
                    "timestamp": timestamps,
                    "indicators": {
                        "quote": [
                            {
                                "open": [100.0, 101.0],
                                "high": [103.0, 104.0],
                                "low": [99.0, 100.0],
                                "close": [102.0, 103.0],
                                "volume": [1000.0, 2000.0],
                            }
                        ],
                        "adjclose": [{"adjclose": [101.0, 102.0]}],
                    },
                }
            ]
        }
    }
    envelope = json.dumps({"body": json.dumps(chart)})
    path.write_text(
        '<script type="application/json" data-sveltekit-fetched '
        f'data-url="https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&amp;region=US">'
        f"{envelope}</script>",
        encoding="utf-8",
    )
    return path
