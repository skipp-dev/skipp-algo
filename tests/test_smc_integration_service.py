from __future__ import annotations

import csv
from pathlib import Path

import pytest

from smc_adapters import build_snapshot_from_raw
from smc_core import snapshot_to_dict
from smc_core.types import SmcSnapshot
from smc_integration.repo_sources import load_raw_meta_input_composite, load_raw_structure_input
from smc_integration.service import (
    build_dashboard_payload_for_symbol_timeframe,
    build_snapshot_bundle_for_symbol_timeframe,
    build_pine_payload_for_symbol_timeframe,
    build_snapshot_for_symbol_timeframe,
)

ROOT = Path(__file__).resolve().parents[1]


def _first_symbol() -> str:
    csv_path = ROOT / "reports" / "databento_watchlist_top5_pre1530.csv"
    with csv_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        row = next(reader, None)
    if row is None or not row.get("symbol"):
        raise AssertionError("watchlist CSV must contain at least one symbol row for integration tests")
    return str(row["symbol"]).strip().upper()



def test_build_snapshot_for_symbol_timeframe_returns_snapshot() -> None:
    symbol = _first_symbol()

    snapshot = build_snapshot_for_symbol_timeframe(symbol, "15m", generated_at=1709253600.0)

    assert isinstance(snapshot, SmcSnapshot)
    assert snapshot.symbol == symbol
    assert snapshot.timeframe == "15m"



def test_build_dashboard_and_pine_payloads_return_expected_shapes() -> None:
    symbol = _first_symbol()

    dashboard = build_dashboard_payload_for_symbol_timeframe(symbol, "15m", generated_at=1709253600.0)
    pine = build_pine_payload_for_symbol_timeframe(symbol, "15m", generated_at=1709253600.0)

    assert dashboard["symbol"] == symbol
    assert dashboard["timeframe"] == "15m"
    assert "summary" in dashboard
    assert "structure_coverage" in dashboard
    assert "source_plan" in dashboard
    assert "structure_status" in dashboard
    assert "zones" in dashboard
    assert "markers" in dashboard

    assert pine["symbol"] == symbol
    assert pine["timeframe"] == "15m"
    assert "structure_coverage" in pine
    assert "source_plan" in pine
    assert "structure_status" in pine
    assert set(["bos", "orderblocks", "fvg", "liquidity_sweeps"]).issubset(set(pine.keys()))



def test_build_snapshot_is_deterministic_for_fixed_generated_at() -> None:
    symbol = _first_symbol()

    one = build_snapshot_for_symbol_timeframe(symbol, "15m", generated_at=1709253600.0)
    two = build_snapshot_for_symbol_timeframe(symbol, "15m", generated_at=1709253600.0)

    assert snapshot_to_dict(one) == snapshot_to_dict(two)



def test_service_matches_direct_adapter_pipeline() -> None:
    symbol = _first_symbol()

    raw_structure = load_raw_structure_input(symbol, "15m")
    raw_meta = load_raw_meta_input_composite(symbol, "15m")
    direct = build_snapshot_from_raw(raw_structure, raw_meta, generated_at=1709253600.0)

    via_service = build_snapshot_for_symbol_timeframe(symbol, "15m", generated_at=1709253600.0)

    assert snapshot_to_dict(direct) == snapshot_to_dict(via_service)



def test_missing_symbol_fails_with_clear_error() -> None:
    with pytest.raises(ValueError, match="not present"):
        build_snapshot_for_symbol_timeframe("__MISSING__", "15m", generated_at=1709253600.0)


def test_snapshot_bundle_source_plan_and_structure_status_are_present() -> None:
    symbol = _first_symbol()
    bundle = build_snapshot_bundle_for_symbol_timeframe(symbol, "15m", generated_at=1709253600.0)

    assert set(["source_plan", "structure_status", "source", "snapshot", "dashboard_payload", "pine_payload"]).issubset(set(bundle.keys()))
    assert set(["measurement_summary", "market_context"]).issubset(set(bundle.keys()))
    assert bundle["source_plan"]["volume"] == "databento_watchlist_csv"
    assert "selected_structure_source" in bundle["structure_status"]
    assert bundle["dashboard_payload"]["source_plan"] == bundle["source_plan"]
    assert bundle["pine_payload"]["source_plan"] == bundle["source_plan"]
    assert bundle["dashboard_payload"]["structure_status"]["selected_structure_source"] == bundle["structure_status"]["selected_structure_source"]
    assert bundle["pine_payload"]["structure_status"]["selected_structure_source"] == bundle["structure_status"]["selected_structure_source"]
    assert bundle["measurement_refs"]["status"] in {"available", "unavailable", "error"}
