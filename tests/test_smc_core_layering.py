from __future__ import annotations

from copy import deepcopy

from smc_core import apply_layering, snapshot_to_dict
from smc_core.types import (
    BosEvent,
    DirectionalStrength,
    Fvg,
    LiquiditySweep,
    Orderblock,
    SmcMeta,
    SmcStructure,
    TimedDirectionalStrength,
    TimedVolumeInfo,
    VolumeInfo,
)


def _structure() -> SmcStructure:
    return SmcStructure(
        bos=[BosEvent(id="bos:1", time=1.0, price=101.0, kind="BOS", dir="UP")],
        orderblocks=[Orderblock(id="ob:1", low=99.0, high=100.0, dir="BULL", valid=True)],
        fvg=[Fvg(id="fvg:1", low=100.2, high=100.8, dir="BULL", valid=True)],
        liquidity_sweeps=[LiquiditySweep(id="sweep:1", time=3.0, price=100.5, side="SELL_SIDE")],
    )


def _meta() -> SmcMeta:
    return SmcMeta(
        symbol="AAPL",
        timeframe="15m",
        asof_ts=1709253580.0,
        volume=TimedVolumeInfo(
            value=VolumeInfo(regime="NORMAL", thin_fraction=0.1),
            asof_ts=1709253580.0,
            stale=False,
        ),
        technical=TimedDirectionalStrength(
            value=DirectionalStrength(strength=0.8, bias="BULLISH"),
            asof_ts=1709253570.0,
            stale=False,
        ),
    )


def test_apply_layering_structure_is_pure() -> None:
    structure = _structure()
    before = deepcopy(structure)
    apply_layering(structure, _meta(), generated_at=1709253600.0)
    assert structure == before


def test_apply_layering_meta_is_pure() -> None:
    meta = _meta()
    before = deepcopy(meta)
    apply_layering(_structure(), meta, generated_at=1709253600.0)
    assert meta == before


def test_apply_layering_is_deterministic_with_fixed_generated_at() -> None:
    one = apply_layering(_structure(), _meta(), generated_at=1709253600.0)
    two = apply_layering(_structure(), _meta(), generated_at=1709253600.0)
    assert snapshot_to_dict(one) == snapshot_to_dict(two)


def test_zone_style_covers_all_structure_ids_without_orphans() -> None:
    snapshot = apply_layering(_structure(), _meta(), generated_at=1709253600.0)
    structure_ids = {
        *(item.id for item in snapshot.structure.bos),
        *(item.id for item in snapshot.structure.orderblocks),
        *(item.id for item in snapshot.structure.fvg),
        *(item.id for item in snapshot.structure.liquidity_sweeps),
    }
    style_ids = set(snapshot.layered.zone_styles.keys())

    assert style_ids == structure_ids
    assert len(style_ids) == len(structure_ids)
