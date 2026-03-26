from __future__ import annotations

import csv
from pathlib import Path

from smc_integration.batch import write_snapshot_bundles_for_symbols

ROOT = Path(__file__).resolve().parents[1]


def _watchlist_symbols(limit: int = 2) -> list[str]:
    csv_path = ROOT / "reports" / "databento_watchlist_top5_pre1530.csv"
    with csv_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        symbols: list[str] = []
        for row in reader:
            value = str(row.get("symbol", "")).strip().upper()
            if value and value not in symbols:
                symbols.append(value)
            if len(symbols) >= limit:
                break
    if len(symbols) < limit:
        raise AssertionError("watchlist CSV must contain enough symbols")
    return symbols


def test_watchlist_manifest_includes_aggregate_coverage_summary(tmp_path: Path) -> None:
    symbols = _watchlist_symbols(limit=2)
    manifest = write_snapshot_bundles_for_symbols(
        symbols,
        "15m",
        source="auto",
        output_dir=tmp_path / "bundles",
        generated_at=1709254000.0,
    )

    summary = manifest["coverage_summary"]
    assert set(summary.keys()) == {
        "symbols_with_bos",
        "symbols_with_orderblocks",
        "symbols_with_fvg",
        "symbols_with_liquidity_sweeps",
    }


def test_watchlist_manifest_bundle_paths_are_deterministic(tmp_path: Path) -> None:
    symbols = _watchlist_symbols(limit=2)
    manifest = write_snapshot_bundles_for_symbols(
        symbols,
        "15m",
        source="auto",
        output_dir=tmp_path / "bundles",
        generated_at=1709254000.0,
    )

    bundle_paths = [row["bundle_path"] for row in manifest["bundles"]]
    assert bundle_paths == sorted(bundle_paths)
    assert all(path.endswith("_15m.bundle.json") for path in bundle_paths)


def test_watchlist_manifest_coverage_counts_match_bundle_rows(tmp_path: Path) -> None:
    symbols = _watchlist_symbols(limit=2)
    manifest = write_snapshot_bundles_for_symbols(
        symbols,
        "15m",
        source="auto",
        output_dir=tmp_path / "bundles",
        generated_at=1709254000.0,
    )

    rows = manifest["bundles"]
    summary = manifest["coverage_summary"]

    assert summary["symbols_with_bos"] == sum(1 for row in rows if row["has_bos"])
    assert summary["symbols_with_orderblocks"] == sum(1 for row in rows if row["has_orderblocks"])
    assert summary["symbols_with_fvg"] == sum(1 for row in rows if row["has_fvg"])
    assert summary["symbols_with_liquidity_sweeps"] == sum(1 for row in rows if row["has_liquidity_sweeps"])


def test_watchlist_manifest_does_not_overstate_missing_categories(tmp_path: Path) -> None:
    symbols = _watchlist_symbols(limit=2)
    manifest = write_snapshot_bundles_for_symbols(
        symbols,
        "15m",
        source="auto",
        output_dir=tmp_path / "bundles",
        generated_at=1709254000.0,
    )

    summary = manifest["coverage_summary"]
    assert summary["symbols_with_orderblocks"] == 0
    assert summary["symbols_with_fvg"] == 0
    assert summary["symbols_with_liquidity_sweeps"] == 0
