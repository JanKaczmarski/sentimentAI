"""Independent checks of the actual frozen source/market artifacts, without network."""

import bisect
import hashlib
import json
import os
import subprocess
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

import httpx
import pytest

from scripts.freeze_evaluation_manifest import verify_evaluation_manifest
from sentiment_system.adapters.outbound.market_data.cached_files import CachedCsvMarketData
from sentiment_system.adapters.outbound.market_data.evaluation_bundle import load_evaluation_scope


@pytest.fixture(scope="module")
def frozen_bundle():
    configured = os.getenv("SENTIMENT_DATA_ROOT")
    if not configured:
        pytest.skip("SENTIMENT_DATA_ROOT is not configured")
    root = Path(configured)
    with pytest.MonkeyPatch.context() as patch:

        def forbid(*args, **kwargs):
            pytest.fail("frozen artifact verification must remain offline")

        patch.setattr(httpx.Client, "request", forbid)
        output = verify_evaluation_manifest(root)
        scope = load_evaluation_scope(root)
    manifest = json.loads((output / "manifest.json").read_bytes())
    corpus = json.loads((root / manifest["corpus"]["path"]).read_bytes())
    coverage = json.loads((output / "coverage.json").read_bytes())
    return root, manifest, corpus, coverage, scope


@pytest.mark.integration
def test_real_frozen_bundle_preserves_all_source_horizons_and_held_out_membership(frozen_bundle):
    root, manifest, corpus, coverage, scope = frozen_bundle
    assert manifest["corpus"]["sha256"] == "e79cd741a308bbb5aebea4da845e05a8df0c6acaa26e4a206073644935f6a16b"
    assert manifest["corpus_window"] == {"start": "2021-08-27", "end": "2026-08-27"}
    assert manifest["development_ends"] == "2024-08-27"
    assert manifest["held_out_starts"] == "2024-08-28"
    assert len(corpus["records"]) == 363
    assert len(coverage["outcomes"]) == 1815
    assert sum(row["partition"] == "held_out" for row in coverage["outcomes"]) == 735
    assert {(row["record_id"], row["horizon"]) for row in coverage["outcomes"]} == {
        (row["record_id"], horizon) for row in corpus["records"] for horizon in (1, 5, 20, 60, 252)
    }
    assert scope.market_snapshot_version == "nasdaq_2026_10_18_research_v2"
    assert all(not dates for value in coverage["calendar_differences"].values() for dates in value.values())


@pytest.mark.integration
def test_actual_price_endpoints_independently_match_every_saved_outcome(frozen_bundle):
    root, manifest, corpus, coverage, scope = frozen_bundle
    market = CachedCsvMarketData((root / manifest["market"]["path"]).parent)
    points = {
        symbol: market.get_prices(symbol) for symbol in (*scope.company_benchmarks, "XLC", "XLK", "XLF", "XLY", "SPY")
    }
    dates = {symbol: [point.trading_date for point in values] for symbol, values in points.items()}
    by_date = {symbol: {point.trading_date: point.close for point in values} for symbol, values in points.items()}
    for row in coverage["outcomes"]:
        company = row["company"]
        index = bisect.bisect_right(dates[company], date.fromisoformat(row["published_at"]))
        if index + row["horizon"] >= len(points[company]):
            assert row["reason"] == "subject_horizon_unavailable"
            assert row["exit_date"] is None
            continue
        entry = points[company][index]
        exit_point = points[company][index + row["horizon"]]
        assert row["reason"] is None
        assert row["entry_date"] == entry.trading_date.isoformat()
        assert row["exit_date"] == exit_point.trading_date.isoformat()
        assert row["subject_return"] == round(exit_point.close / entry.close - 1, 12)
        benchmark = by_date[scope.company_benchmarks[company]]
        assert row["sector_return"] == round(benchmark[exit_point.trading_date] / benchmark[entry.trading_date] - 1, 12)
        assert row["used_spy_fallback"] is False
    expected_counts = {1: (363, 147), 5: (363, 147), 20: (363, 147), 60: (348, 132), 252: (291, 75)}
    for horizon, (total, held_out) in expected_counts.items():
        values = [row for row in coverage["outcomes"] if row["horizon"] == horizon]
        assert sum(row["reason"] is None for row in values) == total
        assert sum(row["reason"] is None and row["partition"] == "held_out" for row in values) == held_out
        assert Counter(row["reason"] for row in values if row["reason"]) == (
            {"subject_horizon_unavailable": 363 - total} if total < 363 else {}
        )


@pytest.mark.integration
def test_real_complete_boundaries_distinguish_latest_entry_and_strict_prior_as_of(frozen_bundle):
    _, _, _, coverage, _ = frozen_bundle
    boundaries = {1: "2026-10-14", 5: "2026-10-08", 20: "2026-09-17", 60: "2026-07-22", 252: "2025-10-14"}
    for summary in coverage["summary"]:
        latest = date.fromisoformat(boundaries[summary["horizon"]])
        assert summary["latest_complete_as_of"] == latest.isoformat()
        assert summary["latest_complete_entry"] == (latest + timedelta(days=1)).isoformat()
        assert summary["as_of_intervals"] == [
            {"start": "2021-08-27", "end": latest.isoformat(), "reason": None},
            {
                "start": (latest + timedelta(days=1)).isoformat(),
                "end": "2026-10-16",
                "reason": "subject_horizon_unavailable",
            },
        ]


@pytest.mark.integration
def test_pinned_data_revision_contains_complete_frozen_artifact_closure(frozen_bundle):
    root, manifest, _, _, _ = frozen_bundle
    lock = json.loads((Path(__file__).parents[2] / "research-data.lock.json").read_bytes())
    revision = lock["revision"]
    assert len(revision) == 40 and all(character in "0123456789abcdef" for character in revision)
    pinned_manifest = subprocess.run(
        ["git", "show", f"{revision}:{lock['evaluation_manifest']['path']}"],
        cwd=root,
        check=True,
        capture_output=True,
    ).stdout
    assert hashlib.sha256(pinned_manifest).hexdigest() == lock["evaluation_manifest"]["sha256"]
    assert json.loads(pinned_manifest) == manifest
    tracked = set(
        subprocess.run(
            ["git", "ls-tree", "-r", "--name-only", revision],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.splitlines()
    )
    output = Path(lock["evaluation_manifest"]["path"]).parent.as_posix()
    required = {*manifest["input_artifacts"], lock["evaluation_manifest"]["path"]}
    required.update(f"{output}/{relative}" for relative in manifest["artifacts"])
    assert required <= tracked, f"Pinned revision is missing artifacts: {sorted(required - tracked)}"
