from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import cast

import jsonschema

from smc_integration.service import build_snapshot_bundle_for_symbol_timeframe

ROOT = Path(__file__).resolve().parents[1]


def _first_symbol() -> str:
    csv_path = ROOT / "reports" / "databento_watchlist_top5_pre1530.csv"
    with csv_path.open("r", encoding="utf-8", newline="") as handle:
        row = next(csv.DictReader(handle), None)
    if row is None or not row.get("symbol"):
        raise AssertionError("watchlist CSV must contain at least one symbol")
    return str(row["symbol"]).strip().upper()


def _schema(path: str) -> dict:
    return cast(dict, json.loads((ROOT / path).read_text(encoding="utf-8")))


def _validate_bundle_schema(bundle: dict) -> None:
    snapshot_schema = _schema("spec/smc_snapshot.schema.json")
    dashboard_schema = _schema("spec/smc_dashboard_payload.schema.json")
    pine_schema = _schema("spec/smc_pine_payload.schema.json")
    bundle_schema = _schema("spec/smc_delivery_bundle.schema.json")

    store = {
        "https://skipp-algo.local/spec/smc_snapshot.schema.json": snapshot_schema,
        "https://skipp-algo.local/spec/smc_dashboard_payload.schema.json": dashboard_schema,
        "https://skipp-algo.local/spec/smc_pine_payload.schema.json": pine_schema,
        "https://skipp-algo.local/spec/smc_delivery_bundle.schema.json": bundle_schema,
    }
    base_uri = f"file://{(ROOT / 'spec').resolve().as_posix()}/"
    resolver = jsonschema.RefResolver(base_uri=base_uri, referrer=bundle_schema, store=store)
    jsonschema.validate(instance=bundle, schema=bundle_schema, resolver=resolver)


def test_delivery_bundle_contains_required_top_level_keys() -> None:
    symbol = _first_symbol()
    bundle = build_snapshot_bundle_for_symbol_timeframe(symbol, "15m", generated_at=1709253600.0)

    assert set(["source_plan", "structure_status", "snapshot", "dashboard_payload", "pine_payload"]).issubset(bundle.keys())


def test_delivery_bundle_snapshot_dashboard_pine_alignment() -> None:
    symbol = _first_symbol()
    bundle = build_snapshot_bundle_for_symbol_timeframe(symbol, "15m", generated_at=1709253600.0)

    dashboard = bundle["dashboard_payload"]
    pine = bundle["pine_payload"]

    assert dashboard["source_plan"] == bundle["source_plan"]
    assert pine["source_plan"] == bundle["source_plan"]
    assert dashboard["structure_status"]["selected_structure_source"] == bundle["structure_status"]["selected_structure_source"]
    assert pine["structure_status"]["selected_structure_source"] == bundle["structure_status"]["selected_structure_source"]
    assert dashboard["structure_coverage"] == pine["structure_coverage"]


def test_delivery_bundle_is_schema_valid() -> None:
    symbol = _first_symbol()
    bundle = build_snapshot_bundle_for_symbol_timeframe(symbol, "15m", generated_at=1709253600.0)
    _validate_bundle_schema(bundle)


def test_delivery_bundle_is_deterministic_for_fixed_generated_at() -> None:
    symbol = _first_symbol()
    one = build_snapshot_bundle_for_symbol_timeframe(symbol, "15m", generated_at=1709253600.0)
    two = build_snapshot_bundle_for_symbol_timeframe(symbol, "15m", generated_at=1709253600.0)
    assert one == two
