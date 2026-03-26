from __future__ import annotations

import time
from typing import Literal, TypedDict

from .schema_version import SCHEMA_VERSION
from .types import (
    BosEvent,
    Fvg,
    LiquiditySweep,
    Orderblock,
    ReasonCode,
    SmcLayered,
    SmcMeta,
    SmcSnapshot,
    SmcStructure,
    VolumeRegime,
    ZoneStyle,
)


class NormalizedMeta(TypedDict):
    symbol: str
    timeframe: str
    asof_ts: float
    volume_regime: VolumeRegime
    volume_stale: bool
    thin_fraction: float
    signed_tech: float
    tech_present: bool
    tech_stale: bool
    signed_news: float
    news_present: bool
    news_stale: bool
    provenance: list[str]


class BaseLayerSignals(TypedDict):
    global_heat: float
    global_strength: float
    base_reasons: list[ReasonCode]


# Regime style anchors remain available for compact coverage checks.
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


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, float(value)))


def _signed_strength(strength: float, bias: str) -> float:
    s = _clamp(strength, 0.0, 1.0)
    if bias == "BULLISH":
        return s
    if bias == "BEARISH":
        return -s
    return 0.0


def _dedupe_reasons(reasons: list[ReasonCode]) -> list[ReasonCode]:
    seen: set[ReasonCode] = set()
    out: list[ReasonCode] = []
    for reason in reasons:
        if reason not in seen:
            seen.add(reason)
            out.append(reason)
    return out


def normalize_meta(meta: SmcMeta) -> NormalizedMeta:
    raw_regime = str(meta.volume.value.regime)
    regime: VolumeRegime
    unknown_regime = False
    if raw_regime in {"NORMAL", "LOW_VOLUME", "HOLIDAY_SUSPECT"}:
        regime = raw_regime  # type: ignore[assignment]
    else:
        # Unknown regimes degrade to neutral-normal handling instead of failing deep in layering.
        regime = "NORMAL"
        unknown_regime = True

    thin_fraction = _clamp(meta.volume.value.thin_fraction, 0.0, 1.0)
    volume_stale = bool(meta.volume.stale) or unknown_regime

    signed_tech = 0.0
    signed_news = 0.0
    tech_present = False
    tech_stale = False
    news_present = False
    news_stale = False

    if meta.technical is not None:
        tech_present = True
        tech_stale = meta.technical.stale
        if not meta.technical.stale:
            signed_tech = _signed_strength(meta.technical.value.strength, meta.technical.value.bias)

    if meta.news is not None:
        news_present = True
        news_stale = meta.news.stale
        if not meta.news.stale:
            signed_news = _signed_strength(meta.news.value.strength, meta.news.value.bias)

    return NormalizedMeta(
        symbol=meta.symbol,
        timeframe=meta.timeframe,
        asof_ts=meta.asof_ts,
        volume_regime=regime,
        volume_stale=volume_stale,
        thin_fraction=thin_fraction,
        signed_tech=_clamp(signed_tech, -1.0, 1.0),
        tech_present=tech_present,
        tech_stale=tech_stale,
        signed_news=_clamp(signed_news, -1.0, 1.0),
        news_present=news_present,
        news_stale=news_stale,
        provenance=list(meta.provenance),
    )


def derive_base_signals(nm: NormalizedMeta) -> BaseLayerSignals:
    signed_tech = nm["signed_tech"]
    signed_news = nm["signed_news"]
    thin_fraction = nm["thin_fraction"]

    global_heat = _clamp(signed_tech * 0.7 + signed_news * 0.3, -1.0, 1.0)
    if nm["volume_stale"]:
        # Missing or stale volume forces neutral fallback regardless of directional inputs.
        global_heat = 0.0
    global_strength = _clamp(max(abs(global_heat), thin_fraction), 0.0, 1.0)

    base_reasons: list[ReasonCode] = []
    regime = nm["volume_regime"]
    if regime == "LOW_VOLUME":
        base_reasons.append("REGIME_LOW_VOLUME")
    elif regime == "HOLIDAY_SUSPECT":
        base_reasons.append("REGIME_HOLIDAY_SUSPECT")
    else:
        base_reasons.append("REGIME_NORMAL")

    if nm["volume_stale"]:
        base_reasons.append("VOLUME_STALE")

    if not nm["tech_present"]:
        base_reasons.append("TECH_MISSING")
    elif nm["tech_stale"]:
        base_reasons.append("TECH_STALE")

    if not nm["news_present"]:
        base_reasons.append("NEWS_MISSING")
    elif nm["news_stale"]:
        base_reasons.append("NEWS_STALE")

    return BaseLayerSignals(
        global_heat=global_heat,
        global_strength=global_strength,
        base_reasons=_dedupe_reasons(base_reasons),
    )

def _tone_from_heat(global_heat: float) -> Literal["BULLISH", "BEARISH", "NEUTRAL"]:
    if global_heat > 0.15:
        return "BULLISH"
    if global_heat < -0.15:
        return "BEARISH"
    return "NEUTRAL"


def _emphasis_from_strength(global_strength: float) -> Literal["LOW", "MEDIUM", "HIGH"]:
    if global_strength >= 0.75:
        return "HIGH"
    if global_strength >= 0.4:
        return "MEDIUM"
    return "LOW"


def _base_zone_style(global_heat: float, global_strength: float, base_reasons: list[ReasonCode]) -> ZoneStyle:
    return ZoneStyle(
        opacity=_clamp(0.25 + 0.35 * global_strength, 0.0, 1.0),
        line_width=2.0,
        render_state="NORMAL",
        trade_state="DISCOURAGED",
        bias="NEUTRAL",
        strength=_clamp(global_strength, 0.0, 1.0),
        heat=_clamp(global_heat, -1.0, 1.0),
        tone=_tone_from_heat(global_heat),
        emphasis=_emphasis_from_strength(global_strength),
        reason_codes=_dedupe_reasons(list(base_reasons)),
    )


def _apply_regime_overlay(style: ZoneStyle, volume_regime: str) -> ZoneStyle:
    reasons = list(style.reason_codes)
    if volume_regime == "HOLIDAY_SUSPECT":
        reasons.append("REGIME_HOLIDAY_SUSPECT")
        return ZoneStyle(
            opacity=min(style.opacity, 0.10),
            line_width=style.line_width,
            render_state="DIMMED",
            trade_state="BLOCKED",
            bias=style.bias,
            strength=style.strength,
            heat=style.heat,
            tone="WARNING",
            emphasis=style.emphasis,
            reason_codes=_dedupe_reasons(reasons),
        )

    if volume_regime == "LOW_VOLUME":
        reasons.append("REGIME_LOW_VOLUME")
        next_trade_state: Literal["ALLOWED", "DISCOURAGED", "BLOCKED"] = style.trade_state
        if next_trade_state == "ALLOWED":
            next_trade_state = "DISCOURAGED"
        return ZoneStyle(
            opacity=min(style.opacity, 0.35),
            line_width=max(1.0, style.line_width - 1.0),
            render_state="HIDDEN" if style.render_state == "HIDDEN" else "DIMMED",
            trade_state=next_trade_state,
            bias=style.bias,
            strength=style.strength,
            heat=style.heat,
            tone=style.tone,
            emphasis=style.emphasis,
            reason_codes=_dedupe_reasons(reasons),
        )

    reasons.append("REGIME_NORMAL")
    return ZoneStyle(
        opacity=style.opacity,
        line_width=style.line_width,
        render_state=style.render_state,
        trade_state=style.trade_state,
        bias=style.bias,
        strength=style.strength,
        heat=style.heat,
        tone=style.tone,
        emphasis=style.emphasis,
        reason_codes=_dedupe_reasons(reasons),
    )


def _style_for_orderblock(item: Orderblock, normalized: NormalizedMeta, signals: BaseLayerSignals) -> ZoneStyle:
    style = _base_zone_style(signals["global_heat"], signals["global_strength"], signals["base_reasons"])
    reasons = list(style.reason_codes)
    heat = signals["global_heat"]

    bias: Literal["LONG", "SHORT", "NEUTRAL"] = "NEUTRAL"
    trade_state: Literal["ALLOWED", "DISCOURAGED", "BLOCKED"] = "DISCOURAGED"
    tone: Literal["BULLISH", "BEARISH", "NEUTRAL", "WARNING"] = style.tone

    if item.dir == "BULL":
        if heat > 0.15:
            bias = "LONG"
            trade_state = "ALLOWED"
            tone = "BULLISH"
            if normalized["signed_tech"] > 0:
                reasons.append("TECH_BULLISH")
            if normalized["signed_news"] > 0:
                reasons.append("NEWS_BULLISH")
        elif heat < -0.15:
            tone = "WARNING"
            if normalized["signed_tech"] < 0:
                reasons.append("TECH_BEARISH")
            if normalized["signed_news"] < 0:
                reasons.append("NEWS_BEARISH")
    else:
        if heat < -0.15:
            bias = "SHORT"
            trade_state = "ALLOWED"
            tone = "BEARISH"
            if normalized["signed_tech"] < 0:
                reasons.append("TECH_BEARISH")
            if normalized["signed_news"] < 0:
                reasons.append("NEWS_BEARISH")
        elif heat > 0.15:
            tone = "WARNING"
            if normalized["signed_tech"] > 0:
                reasons.append("TECH_BULLISH")
            if normalized["signed_news"] > 0:
                reasons.append("NEWS_BULLISH")

    render_state: Literal["NORMAL", "DIMMED", "HIDDEN"] = "NORMAL"
    if not item.valid:
        render_state = "DIMMED"
        trade_state = "DISCOURAGED"
        reasons.append("OB_INVALID")

    style = ZoneStyle(
        opacity=style.opacity,
        line_width=2.0,
        render_state=render_state,
        trade_state=trade_state,
        bias=bias,
        strength=style.strength,
        heat=style.heat,
        tone=tone,
        emphasis=style.emphasis,
        reason_codes=_dedupe_reasons(reasons),
    )
    return _apply_regime_overlay(style, normalized["volume_regime"])


def _style_for_fvg(item: Fvg, normalized: NormalizedMeta, signals: BaseLayerSignals) -> ZoneStyle:
    style = _style_for_orderblock(
        Orderblock(id=item.id, low=item.low, high=item.high, dir=item.dir, valid=item.valid),
        normalized,
        signals,
    )
    reasons = list(style.reason_codes)
    if not item.valid:
        reasons.append("FVG_INVALID")
        style = ZoneStyle(
            opacity=style.opacity,
            line_width=style.line_width,
            render_state="DIMMED",
            trade_state="DISCOURAGED" if style.trade_state != "BLOCKED" else "BLOCKED",
            bias=style.bias,
            strength=style.strength,
            heat=style.heat,
            tone=style.tone,
            emphasis=style.emphasis,
            reason_codes=_dedupe_reasons(reasons),
        )
    return style


def _style_for_bos(item: BosEvent, normalized: NormalizedMeta, signals: BaseLayerSignals) -> ZoneStyle:
    base = _base_zone_style(signals["global_heat"], signals["global_strength"], signals["base_reasons"])
    heat = signals["global_heat"]
    reasons = list(base.reason_codes)
    reasons.append("BOS" if item.kind == "BOS" else "CHOCH")

    bias: Literal["LONG", "SHORT", "NEUTRAL"] = "NEUTRAL"
    tone: Literal["BULLISH", "BEARISH", "NEUTRAL", "WARNING"] = "NEUTRAL"
    if item.dir == "UP" and heat > 0.15:
        bias = "LONG"
        tone = "BULLISH"
    elif item.dir == "DOWN" and heat < -0.15:
        bias = "SHORT"
        tone = "BEARISH"
    elif abs(heat) > 0.15:
        tone = "WARNING"

    style = ZoneStyle(
        opacity=_clamp(base.opacity * 0.8, 0.0, 1.0),
        line_width=1.0,
        render_state="NORMAL",
        trade_state="ALLOWED" if bias != "NEUTRAL" else "DISCOURAGED",
        bias=bias,
        strength=base.strength,
        heat=base.heat,
        tone=tone,
        emphasis=base.emphasis,
        reason_codes=_dedupe_reasons(reasons),
    )
    return _apply_regime_overlay(style, normalized["volume_regime"])


def _style_for_sweep(item: LiquiditySweep, normalized: NormalizedMeta, signals: BaseLayerSignals) -> ZoneStyle:
    base = _base_zone_style(signals["global_heat"], signals["global_strength"], signals["base_reasons"])
    reasons = list(base.reason_codes)
    reasons.append("SWEEP_BUY_SIDE" if item.side == "BUY_SIDE" else "SWEEP_SELL_SIDE")

    style = ZoneStyle(
        opacity=_clamp(base.opacity * 0.9, 0.0, 0.6),
        line_width=1.0,
        render_state="NORMAL",
        trade_state="DISCOURAGED",
        bias="NEUTRAL",
        strength=base.strength,
        heat=base.heat,
        tone="WARNING",
        emphasis=base.emphasis,
        reason_codes=_dedupe_reasons(reasons),
    )
    return _apply_regime_overlay(style, normalized["volume_regime"])


def apply_layering(
    structure: SmcStructure,
    meta: SmcMeta,
    *,
    generated_at: float | None = None,
) -> SmcSnapshot:
    normalized = normalize_meta(meta)
    signals = derive_base_signals(normalized)
    structure_ids = {
        *(item.id for item in structure.orderblocks),
        *(item.id for item in structure.fvg),
        *(item.id for item in structure.bos),
        *(item.id for item in structure.liquidity_sweeps),
    }

    # Keep deterministic style generation order across entity types.
    zone_styles: dict[str, ZoneStyle] = {}
    for item_ob in structure.orderblocks:
        zone_styles[item_ob.id] = _style_for_orderblock(item_ob, normalized, signals)
    for item_fvg in structure.fvg:
        zone_styles[item_fvg.id] = _style_for_fvg(item_fvg, normalized, signals)
    for item_bos in structure.bos:
        zone_styles[item_bos.id] = _style_for_bos(item_bos, normalized, signals)
    for item_sweep in structure.liquidity_sweeps:
        zone_styles[item_sweep.id] = _style_for_sweep(item_sweep, normalized, signals)

    style_ids = set(zone_styles.keys())
    missing = structure_ids - style_ids
    orphan = style_ids - structure_ids
    if missing:
        missing_preview = ", ".join(sorted(missing)[:5])
        raise ValueError(f"layering missing zone styles for ids: {missing_preview}")
    if orphan:
        orphan_preview = ", ".join(sorted(orphan)[:5])
        raise ValueError(f"layering produced orphan zone styles for ids: {orphan_preview}")

    return SmcSnapshot(
        symbol=meta.symbol,
        timeframe=meta.timeframe,
        generated_at=generated_at if generated_at is not None else time.time(),
        schema_version=SCHEMA_VERSION,
        structure=structure,
        meta=meta,
        layered=SmcLayered(zone_styles=zone_styles),
    )
