from __future__ import annotations

import json
from pathlib import Path

import jsonschema

from smc_adapters.pine import snapshot_to_pine_payload
from smc_core import apply_layering
from smc_core.types import BosEvent, SmcMeta, SmcStructure, TimedVolumeInfo, VolumeInfo

ROOT = Path(__file__).resolve().parents[1]


def _snapshot_bos_only():
    structure = SmcStructure(
        bos=[
            BosEvent(id="bos:1", time=1, price=101.0, kind="BOS", dir="UP"),
            BosEvent(id="bos:2", time=2, price=102.0, kind="CHOCH", dir="DOWN"),
        ],
        orderblocks=[],
        fvg=[],
        liquidity_sweeps=[],
    )
    meta = SmcMeta(
        symbol="AAPL",
        timeframe="15m",
        asof_ts=1709253580,
        volume=TimedVolumeInfo(value=VolumeInfo(regime="NORMAL", thin_fraction=0.1), asof_ts=1709253580, stale=False),
    )
    return apply_layering(structure, meta, generated_at=1709254000.0)


def test_pine_payload_contains_all_structure_arrays() -> None:
    payload = snapshot_to_pine_payload(_snapshot_bos_only())
    assert set(["bos", "orderblocks", "fvg", "liquidity_sweeps"]).issubset(payload.keys())


def test_pine_payload_has_structure_coverage_and_matches_content() -> None:
    payload = snapshot_to_pine_payload(_snapshot_bos_only())
    coverage = payload["structure_coverage"]

    assert coverage["has_bos"] is True
    assert coverage["has_orderblocks"] is False
    assert coverage["has_fvg"] is False
    assert coverage["has_liquidity_sweeps"] is False
    assert "choch" in coverage["available_categories"]


def test_unavailable_categories_remain_empty() -> None:
    payload = snapshot_to_pine_payload(_snapshot_bos_only())

    assert payload["orderblocks"] == []
    assert payload["fvg"] == []
    assert payload["liquidity_sweeps"] == []


def test_pine_payload_is_deterministic() -> None:
    one = snapshot_to_pine_payload(_snapshot_bos_only())
    two = snapshot_to_pine_payload(_snapshot_bos_only())
    assert one == two


def test_pine_payload_is_schema_valid() -> None:
    payload = snapshot_to_pine_payload(_snapshot_bos_only())
    schema = json.loads((ROOT / "spec" / "smc_pine_payload.schema.json").read_text(encoding="utf-8"))
    jsonschema.validate(instance=payload, schema=schema)
