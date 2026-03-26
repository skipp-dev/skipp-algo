from __future__ import annotations

import json
from pathlib import Path

import jsonschema

from smc_adapters.dashboard import snapshot_to_dashboard_payload
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


def test_dashboard_payload_has_structure_coverage_block() -> None:
    payload = snapshot_to_dashboard_payload(_snapshot_bos_only())
    assert "structure_coverage" in payload


def test_dashboard_missing_categories_are_explicit() -> None:
    payload = snapshot_to_dashboard_payload(_snapshot_bos_only())
    coverage = payload["structure_coverage"]

    assert "orderblocks" in coverage["missing_categories"]
    assert "fvg" in coverage["missing_categories"]
    assert "liquidity_sweeps" in coverage["missing_categories"]


def test_dashboard_no_fabricated_zones_or_sweep_markers() -> None:
    payload = snapshot_to_dashboard_payload(_snapshot_bos_only())

    assert payload["zones"] == []
    assert all(marker["kind"] in {"BOS", "CHOCH"} for marker in payload["markers"])


def test_dashboard_counts_match_actual_payload_content() -> None:
    payload = snapshot_to_dashboard_payload(_snapshot_bos_only())

    assert payload["summary"]["zone_count"] == len(payload["zones"])
    assert payload["summary"]["marker_count"] == len(payload["markers"])


def test_dashboard_payload_is_deterministic() -> None:
    one = snapshot_to_dashboard_payload(_snapshot_bos_only())
    two = snapshot_to_dashboard_payload(_snapshot_bos_only())
    assert one == two


def test_dashboard_payload_is_schema_valid() -> None:
    payload = snapshot_to_dashboard_payload(_snapshot_bos_only())
    schema = json.loads((ROOT / "spec" / "smc_dashboard_payload.schema.json").read_text(encoding="utf-8"))
    jsonschema.validate(instance=payload, schema=schema)
