from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Literal, cast

from smc_core import apply_layering
from smc_core.types import (
    BosDir,
    BosEvent,
    BosEventKind,
    DirectionalStrength,
    EnrichedNews,
    EventRisk,
    EventSeverity,
    EventType,
    Fvg,
    FvgDir,
    LiquiditySweep,
    MarketRegimeContext,
    ObDir,
    Orderblock,
    SmcMeta,
    SmcSnapshot,
    SmcStructure,
    SweepSide,
    TimedDirectionalStrength,
    TimedEnrichedNews,
    TimedVolumeInfo,
    VolumeRegime,
    VolumeInfo,
)


def _ensure_mapping(value: Any, context: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{context} must be a mapping")
    return value


def _require(mapping: Mapping[str, Any], key: str, context: str) -> Any:
    if key not in mapping:
        raise ValueError(f"missing required field {context}.{key}")
    return mapping[key]


def _as_float(value: Any, context: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{context} must be numeric") from exc


def _as_bool(value: Any, context: str) -> bool:
    if isinstance(value, bool):
        return value
    raise ValueError(f"{context} must be boolean")


def _as_str(value: Any, context: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{context} must be string")
    return value


def _as_list(value: Any, context: str) -> list[Any]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return list(value)
    raise ValueError(f"{context} must be a list")


def _validate_enum(value: str, allowed: set[str], context: str) -> str:
    if value not in allowed:
        raise ValueError(f"invalid {context}: {value}")
    return value


def _bos_kind(value: str, context: str) -> BosEventKind:
    return cast(BosEventKind, _validate_enum(value, {"BOS", "CHOCH"}, context))


def _bos_dir(value: str, context: str) -> BosDir:
    return cast(BosDir, _validate_enum(value, {"UP", "DOWN"}, context))


def _ob_dir(value: str, context: str) -> ObDir:
    return cast(ObDir, _validate_enum(value, {"BULL", "BEAR"}, context))


def _fvg_dir(value: str, context: str) -> FvgDir:
    return cast(FvgDir, _validate_enum(value, {"BULL", "BEAR"}, context))


def _sweep_side(value: str, context: str) -> SweepSide:
    return cast(SweepSide, _validate_enum(value, {"BUY_SIDE", "SELL_SIDE"}, context))


def _volume_regime(value: str, context: str) -> VolumeRegime:
    return cast(VolumeRegime, _validate_enum(value, {"NORMAL", "LOW_VOLUME", "HOLIDAY_SUSPECT"}, context))


def _direction_bias(value: str, context: str) -> Literal["BULLISH", "BEARISH", "NEUTRAL"]:
    return cast(Literal["BULLISH", "BEARISH", "NEUTRAL"], _validate_enum(value, {"BULLISH", "BEARISH", "NEUTRAL"}, context))


def build_structure_from_raw(raw_structure: Mapping[str, Any]) -> SmcStructure:
    raw = _ensure_mapping(raw_structure, "raw_structure")

    bos_items = _as_list(raw.get("bos", []), "raw_structure.bos")
    ob_items = _as_list(raw.get("orderblocks", []), "raw_structure.orderblocks")
    fvg_items = _as_list(raw.get("fvg", []), "raw_structure.fvg")
    sweep_items = _as_list(raw.get("liquidity_sweeps", []), "raw_structure.liquidity_sweeps")

    bos: list[BosEvent] = []
    for idx, item in enumerate(bos_items):
        row = _ensure_mapping(item, f"raw_structure.bos[{idx}]")
        bos.append(
            BosEvent(
                id=_as_str(_require(row, "id", f"raw_structure.bos[{idx}]"), f"raw_structure.bos[{idx}].id"),
                time=_as_float(_require(row, "time", f"raw_structure.bos[{idx}]"), f"raw_structure.bos[{idx}].time"),
                price=_as_float(_require(row, "price", f"raw_structure.bos[{idx}]"), f"raw_structure.bos[{idx}].price"),
                kind=_bos_kind(
                    _as_str(_require(row, "kind", f"raw_structure.bos[{idx}]"), f"raw_structure.bos[{idx}].kind"),
                    f"raw_structure.bos[{idx}].kind",
                ),
                dir=_bos_dir(
                    _as_str(_require(row, "dir", f"raw_structure.bos[{idx}]"), f"raw_structure.bos[{idx}].dir"),
                    f"raw_structure.bos[{idx}].dir",
                ),
            )
        )

    orderblocks: list[Orderblock] = []
    for idx, item in enumerate(ob_items):
        row = _ensure_mapping(item, f"raw_structure.orderblocks[{idx}]")
        orderblocks.append(
            Orderblock(
                id=_as_str(_require(row, "id", f"raw_structure.orderblocks[{idx}]"), f"raw_structure.orderblocks[{idx}].id"),
                low=_as_float(_require(row, "low", f"raw_structure.orderblocks[{idx}]"), f"raw_structure.orderblocks[{idx}].low"),
                high=_as_float(_require(row, "high", f"raw_structure.orderblocks[{idx}]"), f"raw_structure.orderblocks[{idx}].high"),
                dir=_ob_dir(
                    _as_str(_require(row, "dir", f"raw_structure.orderblocks[{idx}]"), f"raw_structure.orderblocks[{idx}].dir"),
                    f"raw_structure.orderblocks[{idx}].dir",
                ),
                valid=_as_bool(_require(row, "valid", f"raw_structure.orderblocks[{idx}]"), f"raw_structure.orderblocks[{idx}].valid"),
            )
        )

    fvg: list[Fvg] = []
    for idx, item in enumerate(fvg_items):
        row = _ensure_mapping(item, f"raw_structure.fvg[{idx}]")
        fvg.append(
            Fvg(
                id=_as_str(_require(row, "id", f"raw_structure.fvg[{idx}]"), f"raw_structure.fvg[{idx}].id"),
                low=_as_float(_require(row, "low", f"raw_structure.fvg[{idx}]"), f"raw_structure.fvg[{idx}].low"),
                high=_as_float(_require(row, "high", f"raw_structure.fvg[{idx}]"), f"raw_structure.fvg[{idx}].high"),
                dir=_fvg_dir(
                    _as_str(_require(row, "dir", f"raw_structure.fvg[{idx}]"), f"raw_structure.fvg[{idx}].dir"),
                    f"raw_structure.fvg[{idx}].dir",
                ),
                valid=_as_bool(_require(row, "valid", f"raw_structure.fvg[{idx}]"), f"raw_structure.fvg[{idx}].valid"),
            )
        )

    liquidity_sweeps: list[LiquiditySweep] = []
    for idx, item in enumerate(sweep_items):
        row = _ensure_mapping(item, f"raw_structure.liquidity_sweeps[{idx}]")
        liquidity_sweeps.append(
            LiquiditySweep(
                id=_as_str(_require(row, "id", f"raw_structure.liquidity_sweeps[{idx}]"), f"raw_structure.liquidity_sweeps[{idx}].id"),
                time=_as_float(_require(row, "time", f"raw_structure.liquidity_sweeps[{idx}]"), f"raw_structure.liquidity_sweeps[{idx}].time"),
                price=_as_float(_require(row, "price", f"raw_structure.liquidity_sweeps[{idx}]"), f"raw_structure.liquidity_sweeps[{idx}].price"),
                side=_sweep_side(
                    _as_str(_require(row, "side", f"raw_structure.liquidity_sweeps[{idx}]"), f"raw_structure.liquidity_sweeps[{idx}].side"),
                    f"raw_structure.liquidity_sweeps[{idx}].side",
                ),
            )
        )

    return SmcStructure(
        bos=bos,
        orderblocks=orderblocks,
        fvg=fvg,
        liquidity_sweeps=liquidity_sweeps,
    )


def _build_timed_directional(raw: Mapping[str, Any], context: str) -> TimedDirectionalStrength:
    value = _ensure_mapping(_require(raw, "value", context), f"{context}.value")
    strength = _as_float(_require(value, "strength", f"{context}.value"), f"{context}.value.strength")
    bias = _direction_bias(
        _as_str(_require(value, "bias", f"{context}.value"), f"{context}.value.bias"),
        f"{context}.value.bias",
    )
    return TimedDirectionalStrength(
        value=DirectionalStrength(strength=strength, bias=bias),
        asof_ts=_as_float(_require(raw, "asof_ts", context), f"{context}.asof_ts"),
        stale=_as_bool(_require(raw, "stale", context), f"{context}.stale"),
    )


_VALID_EVENT_TYPES = {"EARNINGS", "FOMC", "CPI", "NFP", "OPEX", "OTHER"}
_VALID_EVENT_SEVERITIES = {"HIGH", "MODERATE", "LOW"}
_VALID_NEWS_CATEGORIES = {"MACRO", "SECTOR", "COMPANY", "GEOPOLITICAL", "OTHER"}
_VALID_MARKET_REGIMES = {"RISK_ON", "RISK_OFF", "ROTATION", "NEUTRAL"}


def _build_event_risk(raw: Any) -> EventRisk | None:
    if not isinstance(raw, Mapping):
        return None
    et = str(raw.get("event_type", "")).upper()
    sev = str(raw.get("severity", "")).upper()
    if et not in _VALID_EVENT_TYPES or sev not in _VALID_EVENT_SEVERITIES:
        return None
    ws = raw.get("window_start")
    we = raw.get("window_end")
    if ws is None or we is None:
        return None
    return EventRisk(
        event_type=cast(EventType, et),
        severity=cast(EventSeverity, sev),
        window_start=float(ws),
        window_end=float(we),
    )


def _build_enriched_news_list(raw: Any) -> list[TimedEnrichedNews]:
    if not isinstance(raw, (list, Sequence)) or isinstance(raw, (str, bytes)):
        return []
    items: list[TimedEnrichedNews] = []
    for entry in raw:
        if not isinstance(entry, Mapping):
            continue
        val = entry.get("value")
        if not isinstance(val, Mapping):
            continue
        bias_str = str(val.get("bias", "NEUTRAL")).upper()
        if bias_str not in {"BULLISH", "BEARISH", "NEUTRAL"}:
            bias_str = "NEUTRAL"
        cat_str = str(val.get("category", "OTHER")).upper()
        if cat_str not in _VALID_NEWS_CATEGORIES:
            cat_str = "OTHER"
        try:
            en = EnrichedNews(
                strength=float(val.get("strength", 0)),
                bias=cast(Literal["BULLISH", "BEARISH", "NEUTRAL"], bias_str),
                category=cast(Any, cat_str),
                freshness_minutes=float(val.get("freshness_minutes", 0)),
                source=str(val.get("source", "")),
            )
            items.append(TimedEnrichedNews(
                value=en,
                asof_ts=float(entry.get("asof_ts", 0)),
                stale=bool(entry.get("stale", False)),
            ))
        except (TypeError, ValueError):
            continue
    return items


def _build_market_regime(raw: Any) -> MarketRegimeContext | None:
    if not isinstance(raw, Mapping):
        return None
    regime_str = str(raw.get("regime", "")).upper()
    if regime_str not in _VALID_MARKET_REGIMES:
        return None
    vix = raw.get("vix_level")
    breadth = raw.get("sector_breadth", 0.5)
    return MarketRegimeContext(
        regime=cast(Any, regime_str),
        vix_level=float(vix) if vix is not None else None,
        sector_breadth=float(breadth),
    )


def build_meta_from_raw(raw_meta: Mapping[str, Any]) -> SmcMeta:
    raw = _ensure_mapping(raw_meta, "raw_meta")

    symbol = _as_str(_require(raw, "symbol", "raw_meta"), "raw_meta.symbol").strip().upper()
    if not symbol:
        raise ValueError("raw_meta.symbol must not be empty")

    timeframe = _as_str(_require(raw, "timeframe", "raw_meta"), "raw_meta.timeframe").strip()
    if not timeframe:
        raise ValueError("raw_meta.timeframe must not be empty")

    asof_ts = _as_float(_require(raw, "asof_ts", "raw_meta"), "raw_meta.asof_ts")

    raw_volume = _ensure_mapping(_require(raw, "volume", "raw_meta"), "raw_meta.volume")
    raw_volume_value = _ensure_mapping(_require(raw_volume, "value", "raw_meta.volume"), "raw_meta.volume.value")

    regime = _volume_regime(
        _as_str(_require(raw_volume_value, "regime", "raw_meta.volume.value"), "raw_meta.volume.value.regime"),
        "raw_meta.volume.value.regime",
    )
    thin_fraction = _as_float(
        _require(raw_volume_value, "thin_fraction", "raw_meta.volume.value"),
        "raw_meta.volume.value.thin_fraction",
    )

    volume = TimedVolumeInfo(
        value=VolumeInfo(regime=regime, thin_fraction=thin_fraction),
        asof_ts=_as_float(_require(raw_volume, "asof_ts", "raw_meta.volume"), "raw_meta.volume.asof_ts"),
        stale=_as_bool(_require(raw_volume, "stale", "raw_meta.volume"), "raw_meta.volume.stale"),
    )

    technical = None
    if "technical" in raw and raw["technical"] is not None:
        technical = _build_timed_directional(_ensure_mapping(raw["technical"], "raw_meta.technical"), "raw_meta.technical")

    news = None
    if "news" in raw and raw["news"] is not None:
        news = _build_timed_directional(_ensure_mapping(raw["news"], "raw_meta.news"), "raw_meta.news")

    event_risk = _build_event_risk(raw.get("event_risk"))
    enriched_news = _build_enriched_news_list(raw.get("enriched_news"))
    market_regime = _build_market_regime(raw.get("market_regime"))

    provenance_raw = raw.get("provenance", [])
    provenance_items = _as_list(provenance_raw, "raw_meta.provenance")
    provenance: list[str] = []
    for idx, item in enumerate(provenance_items):
        provenance.append(_as_str(item, f"raw_meta.provenance[{idx}]"))

    return SmcMeta(
        symbol=symbol,
        timeframe=timeframe,
        asof_ts=asof_ts,
        volume=volume,
        technical=technical,
        news=news,
        event_risk=event_risk,
        enriched_news=enriched_news,
        market_regime=market_regime,
        provenance=provenance,
    )


def build_snapshot_from_raw(
    raw_structure: Mapping[str, Any],
    raw_meta: Mapping[str, Any],
    *,
    generated_at: float | None = None,
) -> SmcSnapshot:
    structure = build_structure_from_raw(raw_structure)
    meta = build_meta_from_raw(raw_meta)
    return apply_layering(structure, meta, generated_at=generated_at)
