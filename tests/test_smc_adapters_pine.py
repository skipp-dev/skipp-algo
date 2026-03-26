from __future__ import annotations

import pytest

from smc_adapters.pine import snapshot_to_pine_payload
from smc_core import apply_layering
from smc_core.types import BosEvent, Fvg, LiquiditySweep, Orderblock, SmcMeta, SmcStructure, TimedVolumeInfo, VolumeInfo


def _snapshot():
    structure = SmcStructure(
        bos=[BosEvent(id="bos:1", time=1, price=101.0, kind="BOS", dir="UP")],
        orderblocks=[Orderblock(id="ob:1", low=99.0, high=100.0, dir="BULL", valid=True)],
        fvg=[Fvg(id="fvg:1", low=100.2, high=100.8, dir="BULL", valid=True)],
        liquidity_sweeps=[LiquiditySweep(id="sw:1", time=3, price=100.5, side="SELL_SIDE")],
    )
    meta = SmcMeta(
        symbol="AAPL",
        timeframe="15m",
        asof_ts=1709253580,
        volume=TimedVolumeInfo(value=VolumeInfo(regime="NORMAL", thin_fraction=0.1), asof_ts=1709253580, stale=False),
    )
    return apply_layering(structure, meta, generated_at=1709254000.0)


def test_pine_payload_contains_all_structure_sections() -> None:
    payload = snapshot_to_pine_payload(_snapshot())
    assert "structure_coverage" in payload
    assert "bos" in payload
    assert "orderblocks" in payload
    assert "fvg" in payload
    assert "liquidity_sweeps" in payload


def test_pine_structure_coverage_matches_snapshot_content() -> None:
    payload = snapshot_to_pine_payload(_snapshot())
    coverage = payload["structure_coverage"]

    assert coverage["has_bos"] is True
    assert coverage["has_orderblocks"] is True
    assert coverage["has_fvg"] is True
    assert coverage["has_liquidity_sweeps"] is True
    assert "choch" not in coverage["available_categories"]


def test_each_entity_contains_style() -> None:
    payload = snapshot_to_pine_payload(_snapshot())
    assert "style" in payload["bos"][0]
    assert "style" in payload["orderblocks"][0]
    assert "style" in payload["fvg"][0]
    assert "style" in payload["liquidity_sweeps"][0]


def test_missing_style_raises_value_error() -> None:
    snapshot = _snapshot()
    snapshot.layered.zone_styles.pop("ob:1")
    with pytest.raises(ValueError):
        snapshot_to_pine_payload(snapshot)


def test_payload_is_deterministic() -> None:
    snapshot = _snapshot()
    p1 = snapshot_to_pine_payload(snapshot)
    p2 = snapshot_to_pine_payload(snapshot)
    assert p1 == p2


def test_pine_adapter_only_projects_snapshot_data() -> None:
    snapshot = _snapshot()
    payload = snapshot_to_pine_payload(snapshot)
    assert payload["orderblocks"][0]["id"] == snapshot.structure.orderblocks[0].id
    assert payload["orderblocks"][0]["style"]["reason_codes"] == list(snapshot.layered.zone_styles["ob:1"].reason_codes)
