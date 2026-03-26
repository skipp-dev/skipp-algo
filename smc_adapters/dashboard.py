from __future__ import annotations

from typing import Any

from smc_core.types import BosEvent, Fvg, LiquiditySweep, Orderblock, SmcSnapshot, ZoneStyle


def _style_dict(style: ZoneStyle) -> dict:
    return {
        "render_state": style.render_state,
        "trade_state": style.trade_state,
        "bias": style.bias,
        "strength": style.strength,
        "heat": style.heat,
        "tone": style.tone,
        "emphasis": style.emphasis,
        "reason_codes": list(style.reason_codes),
    }


def _require_style(snapshot: SmcSnapshot, entity_id: str) -> ZoneStyle:
    if entity_id not in snapshot.layered.zone_styles:
        raise ValueError(f"missing style for entity id {entity_id}")
    return snapshot.layered.zone_styles[entity_id]


def _zone_from_orderblock(snapshot: SmcSnapshot, item: Orderblock) -> dict:
    style = _require_style(snapshot, item.id)
    return {
        "id": item.id,
        "kind": "ORDERBLOCK",
        "dir": item.dir,
        "valid": item.valid,
        "low": item.low,
        "high": item.high,
        "style": _style_dict(style),
    }


def _zone_from_fvg(snapshot: SmcSnapshot, item: Fvg) -> dict:
    style = _require_style(snapshot, item.id)
    return {
        "id": item.id,
        "kind": "FVG",
        "dir": item.dir,
        "valid": item.valid,
        "low": item.low,
        "high": item.high,
        "style": _style_dict(style),
    }


def _marker_from_bos(snapshot: SmcSnapshot, item: BosEvent) -> dict:
    style = _require_style(snapshot, item.id)
    return {
        "id": item.id,
        "kind": item.kind,
        "dir": item.dir,
        "time": item.time,
        "price": item.price,
        "style": _style_dict(style),
    }


def _marker_from_sweep(snapshot: SmcSnapshot, item: LiquiditySweep) -> dict:
    style = _require_style(snapshot, item.id)
    return {
        "id": item.id,
        "kind": "LIQUIDITY_SWEEP",
        "side": item.side,
        "time": item.time,
        "price": item.price,
        "style": _style_dict(style),
    }


def _structure_coverage(snapshot: SmcSnapshot) -> dict[str, Any]:
    has_bos = bool(snapshot.structure.bos)
    has_choch = any(item.kind == "CHOCH" for item in snapshot.structure.bos)
    has_orderblocks = bool(snapshot.structure.orderblocks)
    has_fvg = bool(snapshot.structure.fvg)
    has_liquidity_sweeps = bool(snapshot.structure.liquidity_sweeps)

    category_pairs = [
        ("bos", has_bos),
        ("choch", has_choch),
        ("orderblocks", has_orderblocks),
        ("fvg", has_fvg),
        ("liquidity_sweeps", has_liquidity_sweeps),
    ]

    available_categories = [name for name, available in category_pairs if available]
    missing_categories = [name for name, available in category_pairs if not available]

    return {
        "available_categories": available_categories,
        "missing_categories": missing_categories,
        "has_bos": has_bos,
        "has_orderblocks": has_orderblocks,
        "has_fvg": has_fvg,
        "has_liquidity_sweeps": has_liquidity_sweeps,
    }


def snapshot_to_dashboard_payload(
    snapshot: SmcSnapshot,
    *,
    source_plan: dict[str, Any] | None = None,
    structure_status: dict[str, Any] | None = None,
) -> dict:
    zones = [
        *[_zone_from_orderblock(snapshot, item) for item in snapshot.structure.orderblocks],
        *[_zone_from_fvg(snapshot, item) for item in snapshot.structure.fvg],
    ]
    markers = [
        *[_marker_from_bos(snapshot, item) for item in snapshot.structure.bos],
        *[_marker_from_sweep(snapshot, item) for item in snapshot.structure.liquidity_sweeps],
    ]

    zones.sort(key=lambda x: (x["kind"], x["id"]))
    markers.sort(key=lambda x: (x["kind"], x["id"]))

    all_styles = list(snapshot.layered.zone_styles.values())
    summary = {
        "zone_count": len(zones),
        "marker_count": len(markers),
        "blocked_count": sum(1 for s in all_styles if s.trade_state == "BLOCKED"),
        "discouraged_count": sum(1 for s in all_styles if s.trade_state == "DISCOURAGED"),
        "long_bias_count": sum(1 for s in all_styles if s.bias == "LONG"),
        "short_bias_count": sum(1 for s in all_styles if s.bias == "SHORT"),
        "neutral_bias_count": sum(1 for s in all_styles if s.bias == "NEUTRAL"),
    }

    payload = {
        "symbol": snapshot.symbol,
        "timeframe": snapshot.timeframe,
        "generated_at": snapshot.generated_at,
        "schema_version": snapshot.schema_version,
        "structure_coverage": _structure_coverage(snapshot),
        "summary": summary,
        "zones": zones,
        "markers": markers,
    }

    if source_plan is not None:
        payload["source_plan"] = dict(source_plan)
    if structure_status is not None:
        payload["structure_status"] = dict(structure_status)

    return payload
