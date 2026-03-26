from __future__ import annotations

from dataclasses import replace
from typing import Any, Literal, TypedDict

from .types import (
    BosEvent,
    Fvg,
    LiquiditySweep,
    Orderblock,
    SmcMeta,
    SmcStructure,
    ZoneStyle,
)


class NormalizedMeta(TypedDict):
    liquidity_pressure: float
    volume_zscore: float
    event_risk: float
    options_pin_pressure: float
    gamma_tilt: float
    net_bias: Literal["bullish", "bearish", "neutral"]


class BaseLayerSignals(TypedDict):
    ifvg_score: float
    ob_score: float
    sweep_risk: float
    confidence: float


# Regime-to-style mapping kept compact and deterministic for phase-1.
REGIME_STYLE = {
    "NORMAL": ZoneStyle(
        opacity=0.4,
        line_width=2,
        render_state="NORMAL",
        trade_state="ALLOWED",
        bias="NEUTRAL",
        strength=0.5,
        heat=0.5,
        tone="NEUTRAL",
        emphasis="MEDIUM",
    ),
    "LOW_VOLUME": ZoneStyle(
        opacity=0.35,
        line_width=2,
        render_state="DIMMED",
        trade_state="DISCOURAGED",
        bias="NEUTRAL",
        strength=0.4,
        heat=0.35,
        tone="WARNING",
        emphasis="LOW",
    ),
    "HOLIDAY_SUSPECT": ZoneStyle(
        opacity=0.3,
        line_width=1,
        render_state="DIMMED",
        trade_state="DISCOURAGED",
        bias="NEUTRAL",
        strength=0.3,
        heat=0.25,
        tone="WARNING",
        emphasis="LOW",
    ),
}


def _clamp(value: float, lower: float = -1.0, upper: float = 1.0) -> float:
    return max(lower, min(upper, float(value)))


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def normalize_meta(meta: SmcMeta | dict) -> NormalizedMeta:
    regime: str
    if isinstance(meta, SmcMeta):
        regime = meta.volume.value.regime
        liquidity_pressure = _to_float(meta.volume.value.thin_fraction, 0.0)
        volume_zscore = _to_float(meta.volume.value.thin_fraction, 0.0)
        event_risk = 1.0 if (meta.news is not None and meta.news.stale) else 0.0
        options_pin_pressure = 0.0
        gamma_tilt = 0.0
    elif isinstance(meta, dict):
        volume_data = meta.get("volume", {})
        if isinstance(volume_data, dict):
            regime = str(volume_data.get("regime", "NORMAL"))
            liquidity_pressure = _to_float(volume_data.get("thin_fraction", 0.0), 0.0)
            volume_zscore = _to_float(volume_data.get("thin_fraction", 0.0), 0.0)
        else:
            regime = "NORMAL"
            liquidity_pressure = 0.0
            volume_zscore = 0.0
        event_risk = _to_float(meta.get("eventRisk", 0.0), 0.0)
        options_pin_pressure = 0.0
        gamma_tilt = 0.0
    else:
        regime = "NORMAL"
        liquidity_pressure = 0.0
        volume_zscore = 0.0
        event_risk = 0.0
        options_pin_pressure = 0.0
        gamma_tilt = 0.0

    if regime == "NORMAL":
        net_bias: Literal["bullish", "bearish", "neutral"] = "bullish"
    elif regime == "LOW_VOLUME":
        net_bias = "bearish"
    else:
        net_bias = "neutral"

    return NormalizedMeta(
        liquidity_pressure=_clamp(liquidity_pressure),
        volume_zscore=_clamp(volume_zscore),
        event_risk=_clamp(event_risk),
        options_pin_pressure=_clamp(options_pin_pressure),
        gamma_tilt=_clamp(gamma_tilt),
        net_bias=net_bias,
    )


def derive_base_signals(normalized: NormalizedMeta) -> BaseLayerSignals:
    liquidity_pressure = normalized["liquidity_pressure"]
    volume_zscore = normalized["volume_zscore"]
    event_risk = normalized["event_risk"]

    ifvg_score = _clamp((liquidity_pressure + volume_zscore) / 2.0)
    ob_score = _clamp((liquidity_pressure - event_risk) / 2.0)
    sweep_risk = _clamp((event_risk - volume_zscore) / 2.0)
    confidence = _clamp(1.0 - abs(event_risk), 0.0, 1.0)

    return BaseLayerSignals(
        ifvg_score=ifvg_score,
        ob_score=ob_score,
        sweep_risk=sweep_risk,
        confidence=confidence,
    )


def _meta_regime(meta: SmcMeta | dict | None) -> str:
    if isinstance(meta, SmcMeta):
        return meta.volume.value.regime
    if isinstance(meta, dict):
        volume_data = meta.get("volume")
        if isinstance(volume_data, dict):
            return str(volume_data.get("regime", "NORMAL"))
    return "NORMAL"


def _style_for_regime(regime: str) -> ZoneStyle:
    return REGIME_STYLE.get(regime, REGIME_STYLE["NORMAL"])


def apply_layering(structure: SmcStructure, meta: SmcMeta | dict) -> SmcStructure:
    # Phase-1 neutrality: derive signals but avoid strategy overfitting.
    normalized = normalize_meta(meta)
    signals = derive_base_signals(normalized)

    regime = _meta_regime(meta)
    style = _style_for_regime(regime)

    def apply_bos(item: BosEvent) -> BosEvent:
        return item

    def apply_ob(item: Orderblock) -> Orderblock:
        return item

    def apply_fvg(item: Fvg) -> Fvg:
        return item

    def apply_sweep(item: LiquiditySweep) -> LiquiditySweep:
        return item

    _ = style
    return replace(
        structure,
        bos=[apply_bos(item) for item in structure.bos],
        orderblocks=[apply_ob(item) for item in structure.orderblocks],
        fvg=[apply_fvg(item) for item in structure.fvg],
        liquidity_sweeps=[apply_sweep(item) for item in structure.liquidity_sweeps],
    )
