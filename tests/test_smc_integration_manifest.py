from __future__ import annotations

import json
from pathlib import Path

import smc_integration.batch as batch


def _bundle(symbol: str, timeframe: str, *, has_structure: bool) -> dict:
    structure: dict[str, list[dict[str, str]]] = {"bos": [], "orderblocks": [], "fvg": [], "liquidity_sweeps": []}
    if has_structure:
        structure["bos"] = [{"id": "bos:1"}]
    return {
        "source": {"name": "databento_watchlist_csv", "path_hint": "reports/databento_watchlist_top5_pre1530.csv", "capabilities": {}, "notes": []},
        "snapshot": {
            "symbol": symbol,
            "timeframe": timeframe,
            "structure": structure,
            "meta": {"symbol": symbol, "timeframe": timeframe},
        },
        "dashboard_payload": {"symbol": symbol, "timeframe": timeframe},
        "pine_payload": {"symbol": symbol, "timeframe": timeframe},
    }


def test_manifest_contains_expected_root_fields() -> None:
    manifest = batch.build_snapshot_manifest(
        symbols_requested=["AAPL"],
        symbols_built=["AAPL"],
        timeframe="15m",
        source_name="databento_watchlist_csv",
        generated_at=1709254000.0,
        output_dir=Path("reports/smc_snapshot_bundles"),
        bundles=[_bundle("AAPL", "15m", has_structure=False)],
        errors=[],
    )
    assert set(["schema_version", "generated_at", "timeframe", "source", "counts", "bundles", "errors"]).issubset(set(manifest.keys()))


def test_manifest_counts_and_paths_are_deterministic() -> None:
    manifest = batch.build_snapshot_manifest(
        symbols_requested=["MSFT", "AAPL"],
        symbols_built=["MSFT", "AAPL"],
        timeframe="15m",
        source_name="databento_watchlist_csv",
        generated_at=1709254000.0,
        output_dir=Path("reports/smc_snapshot_bundles"),
        bundles=[_bundle("MSFT", "15m", has_structure=False), _bundle("AAPL", "15m", has_structure=False)],
        errors=[],
    )

    assert manifest["counts"] == {"symbols_requested": 2, "symbols_built": 2, "errors": 0}
    assert [item["symbol"] for item in manifest["bundles"]] == ["AAPL", "MSFT"]
    assert manifest["bundles"][0]["bundle_path"].endswith("AAPL_15m.bundle.json")


def test_manifest_has_structure_and_has_meta_are_honest() -> None:
    manifest = batch.build_snapshot_manifest(
        symbols_requested=["AAPL", "MSFT"],
        symbols_built=["AAPL", "MSFT"],
        timeframe="15m",
        source_name="databento_watchlist_csv",
        generated_at=1709254000.0,
        output_dir=Path("reports/smc_snapshot_bundles"),
        bundles=[_bundle("AAPL", "15m", has_structure=False), _bundle("MSFT", "15m", has_structure=True)],
        errors=[],
    )

    by_symbol = {row["symbol"]: row for row in manifest["bundles"]}
    assert by_symbol["AAPL"]["has_structure"] is False
    assert by_symbol["MSFT"]["has_structure"] is True
    assert by_symbol["AAPL"]["has_meta"] is True


def test_manifest_is_json_serializable_and_stable() -> None:
    one = batch.build_snapshot_manifest(
        symbols_requested=["AAPL"],
        symbols_built=["AAPL"],
        timeframe="15m",
        source_name="databento_watchlist_csv",
        generated_at=1709254000.0,
        output_dir=Path("reports/smc_snapshot_bundles"),
        bundles=[_bundle("AAPL", "15m", has_structure=False)],
        errors=[],
    )
    two = batch.build_snapshot_manifest(
        symbols_requested=["AAPL"],
        symbols_built=["AAPL"],
        timeframe="15m",
        source_name="databento_watchlist_csv",
        generated_at=1709254000.0,
        output_dir=Path("reports/smc_snapshot_bundles"),
        bundles=[_bundle("AAPL", "15m", has_structure=False)],
        errors=[],
    )

    assert json.dumps(one, sort_keys=True) == json.dumps(two, sort_keys=True)
