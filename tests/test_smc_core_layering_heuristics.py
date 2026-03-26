from __future__ import annotations

from typing import Literal

from smc_core import apply_layering
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
    VolumeRegime,
    VolumeInfo,
)


def _meta(
    *,
    regime: VolumeRegime = "NORMAL",
    tech_strength: float = 0.0,
    tech_bias: Literal["BULLISH", "BEARISH", "NEUTRAL"] = "NEUTRAL",
    news_strength: float = 0.0,
    news_bias: Literal["BULLISH", "BEARISH", "NEUTRAL"] = "NEUTRAL",
) -> SmcMeta:
    technical = TimedDirectionalStrength(
        value=DirectionalStrength(strength=tech_strength, bias=tech_bias),
        asof_ts=1709253570,
        stale=False,
    )
    news = TimedDirectionalStrength(
        value=DirectionalStrength(strength=news_strength, bias=news_bias),
        asof_ts=1709253560,
        stale=False,
    )
    return SmcMeta(
        symbol="AAPL",
        timeframe="15m",
        asof_ts=1709253580,
        volume=TimedVolumeInfo(value=VolumeInfo(regime=regime, thin_fraction=0.2), asof_ts=1709253580, stale=False),
        technical=technical,
        news=news,
    )


def test_bullish_heat_strengthens_bullish_ob_fvg() -> None:
    structure = SmcStructure(
        orderblocks=[Orderblock(id="ob:1", low=100.0, high=101.0, dir="BULL", valid=True)],
        fvg=[Fvg(id="fvg:1", low=101.0, high=101.5, dir="BULL", valid=True)],
    )
    snapshot = apply_layering(structure, _meta(tech_strength=0.9, tech_bias="BULLISH", news_strength=0.4, news_bias="BULLISH"), generated_at=1709253600.0)

    ob_style = snapshot.layered.zone_styles["ob:1"]
    fvg_style = snapshot.layered.zone_styles["fvg:1"]
    assert ob_style.bias == "LONG"
    assert fvg_style.bias == "LONG"
    assert ob_style.trade_state == "ALLOWED"
    assert fvg_style.trade_state == "ALLOWED"
    assert ob_style.tone == "BULLISH"
    assert fvg_style.tone == "BULLISH"


def test_bearish_heat_strengthens_bearish_ob_fvg() -> None:
    structure = SmcStructure(
        orderblocks=[Orderblock(id="ob:2", low=100.0, high=101.0, dir="BEAR", valid=True)],
        fvg=[Fvg(id="fvg:2", low=99.0, high=99.5, dir="BEAR", valid=True)],
    )
    snapshot = apply_layering(structure, _meta(tech_strength=0.85, tech_bias="BEARISH", news_strength=0.4, news_bias="BEARISH"), generated_at=1709253600.0)

    ob_style = snapshot.layered.zone_styles["ob:2"]
    fvg_style = snapshot.layered.zone_styles["fvg:2"]
    assert ob_style.bias == "SHORT"
    assert fvg_style.bias == "SHORT"
    assert ob_style.trade_state == "ALLOWED"
    assert fvg_style.trade_state == "ALLOWED"
    assert ob_style.tone == "BEARISH"
    assert fvg_style.tone == "BEARISH"


def test_counter_heat_discourages_zone() -> None:
    structure = SmcStructure(orderblocks=[Orderblock(id="ob:3", low=100.0, high=101.0, dir="BULL", valid=True)])
    snapshot = apply_layering(structure, _meta(tech_strength=0.8, tech_bias="BEARISH", news_strength=0.3, news_bias="BEARISH"), generated_at=1709253600.0)

    style = snapshot.layered.zone_styles["ob:3"]
    assert style.trade_state == "DISCOURAGED"
    assert style.bias != "LONG"
    assert style.tone in {"WARNING", "NEUTRAL"}


def test_invalid_ob_and_fvg_are_dimmed() -> None:
    structure = SmcStructure(
        orderblocks=[Orderblock(id="ob:4", low=100.0, high=101.0, dir="BULL", valid=False)],
        fvg=[Fvg(id="fvg:4", low=101.0, high=101.4, dir="BULL", valid=False)],
    )
    snapshot = apply_layering(structure, _meta(), generated_at=1709253600.0)

    ob_style = snapshot.layered.zone_styles["ob:4"]
    fvg_style = snapshot.layered.zone_styles["fvg:4"]
    assert ob_style.render_state == "DIMMED"
    assert ob_style.trade_state == "DISCOURAGED"
    assert "OB_INVALID" in ob_style.reason_codes

    assert fvg_style.render_state == "DIMMED"
    assert fvg_style.trade_state == "DISCOURAGED"
    assert "FVG_INVALID" in fvg_style.reason_codes


def test_holiday_suspect_blocks_everything() -> None:
    structure = SmcStructure(
        orderblocks=[Orderblock(id="ob:5", low=100.0, high=101.0, dir="BULL", valid=True)],
        fvg=[Fvg(id="fvg:5", low=101.0, high=101.5, dir="BEAR", valid=True)],
        bos=[BosEvent(id="bos:5", time=1709250000, price=101.0, kind="BOS", dir="UP")],
        liquidity_sweeps=[LiquiditySweep(id="sweep:5", time=1709250100, price=100.5, side="BUY_SIDE")],
    )
    snapshot = apply_layering(structure, _meta(regime="HOLIDAY_SUSPECT"), generated_at=1709253600.0)

    for style in snapshot.layered.zone_styles.values():
        assert style.trade_state == "BLOCKED"
        assert style.render_state == "DIMMED"
        assert "REGIME_HOLIDAY_SUSPECT" in style.reason_codes


def test_low_volume_dims_and_discourages() -> None:
    structure = SmcStructure(orderblocks=[Orderblock(id="ob:6", low=100.0, high=101.0, dir="BULL", valid=True)])
    snapshot = apply_layering(structure, _meta(regime="LOW_VOLUME", tech_strength=0.9, tech_bias="BULLISH"), generated_at=1709253600.0)

    style = snapshot.layered.zone_styles["ob:6"]
    assert style.render_state == "DIMMED"
    assert style.trade_state != "ALLOWED"
    assert style.trade_state != "BLOCKED"


def test_sweep_remains_neutral_with_side_reason() -> None:
    structure = SmcStructure(
        liquidity_sweeps=[
            LiquiditySweep(id="sweep:buy", time=1709250100, price=100.5, side="BUY_SIDE"),
            LiquiditySweep(id="sweep:sell", time=1709250110, price=101.5, side="SELL_SIDE"),
        ]
    )
    snapshot = apply_layering(structure, _meta(tech_strength=0.9, tech_bias="BULLISH", news_strength=0.9, news_bias="BULLISH"), generated_at=1709253600.0)

    buy_style = snapshot.layered.zone_styles["sweep:buy"]
    sell_style = snapshot.layered.zone_styles["sweep:sell"]

    assert buy_style.bias == "NEUTRAL"
    assert sell_style.bias == "NEUTRAL"
    assert buy_style.tone == "WARNING"
    assert sell_style.tone == "WARNING"
    assert "SWEEP_BUY_SIDE" in buy_style.reason_codes
    assert "SWEEP_SELL_SIDE" in sell_style.reason_codes


def test_bos_choch_have_marker_reasons() -> None:
    structure = SmcStructure(
        bos=[
            BosEvent(id="bos:6", time=1709250000, price=101.0, kind="BOS", dir="UP"),
            BosEvent(id="choch:6", time=1709250060, price=100.0, kind="CHOCH", dir="DOWN"),
        ]
    )
    snapshot = apply_layering(structure, _meta(), generated_at=1709253600.0)

    assert "BOS" in snapshot.layered.zone_styles["bos:6"].reason_codes
    assert "CHOCH" in snapshot.layered.zone_styles["choch:6"].reason_codes


def test_reason_codes_are_deduplicated() -> None:
    structure = SmcStructure(orderblocks=[Orderblock(id="ob:7", low=100.0, high=101.0, dir="BULL", valid=True)])
    snapshot = apply_layering(structure, _meta(regime="NORMAL", tech_strength=0.9, tech_bias="BULLISH", news_strength=0.9, news_bias="BULLISH"), generated_at=1709253600.0)

    reasons = snapshot.layered.zone_styles["ob:7"].reason_codes
    assert len(reasons) == len(set(reasons))
