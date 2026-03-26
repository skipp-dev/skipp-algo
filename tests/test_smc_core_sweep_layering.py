from __future__ import annotations

from smc_core import apply_layering
from smc_core.types import DirectionalStrength, LiquiditySweep, SmcMeta, SmcStructure, TimedDirectionalStrength, TimedVolumeInfo, VolumeInfo


def test_liquidity_sweep_style_is_warning_and_neutral_with_reason_code() -> None:
    structure = SmcStructure(
        liquidity_sweeps=[
            LiquiditySweep(id="sweep:buy", time=1709250100.0, price=100.5, side="BUY_SIDE"),
            LiquiditySweep(id="sweep:sell", time=1709250110.0, price=101.5, side="SELL_SIDE"),
        ]
    )
    meta = SmcMeta(
        symbol="AAPL",
        timeframe="15m",
        asof_ts=1709253580.0,
        volume=TimedVolumeInfo(value=VolumeInfo(regime="NORMAL", thin_fraction=0.2), asof_ts=1709253580.0, stale=False),
        technical=TimedDirectionalStrength(
            value=DirectionalStrength(strength=0.9, bias="BULLISH"),
            asof_ts=1709253570.0,
            stale=False,
        ),
    )

    snapshot = apply_layering(structure, meta, generated_at=1709253600.0)

    buy = snapshot.layered.zone_styles["sweep:buy"]
    sell = snapshot.layered.zone_styles["sweep:sell"]

    assert buy.bias == "NEUTRAL"
    assert sell.bias == "NEUTRAL"
    assert buy.tone == "WARNING"
    assert sell.tone == "WARNING"
    assert "SWEEP_BUY_SIDE" in buy.reason_codes
    assert "SWEEP_SELL_SIDE" in sell.reason_codes
