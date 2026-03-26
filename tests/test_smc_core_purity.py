from __future__ import annotations

from copy import deepcopy

from smc_core import apply_layering
from smc_core.types import BosEvent, SmcMeta, SmcStructure, TimedVolumeInfo, VolumeInfo


def test_apply_layering_does_not_mutate_inputs() -> None:
    structure = SmcStructure(
        bos=[BosEvent(id="bos:AAPL:15m:1709250000:BOS:UP:185.25", time=1709250000, price=185.25, kind="BOS", dir="UP")]
    )
    meta = SmcMeta(
        symbol="AAPL",
        timeframe="15m",
        asof_ts=1709253580,
        volume=TimedVolumeInfo(value=VolumeInfo(regime="NORMAL", thin_fraction=0.1), asof_ts=1709253580, stale=False),
    )

    before_structure = deepcopy(structure)
    before_meta = deepcopy(meta)

    layered = apply_layering(structure, meta)

    assert structure == before_structure
    assert meta == before_meta
    assert layered is not structure
