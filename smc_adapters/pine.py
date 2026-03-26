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


def _bos_entry(snapshot: SmcSnapshot, item: BosEvent) -> dict:
    return {
        "id": item.id,
        "time": item.time,
        "price": item.price,
        "kind": item.kind,
        "dir": item.dir,
        "style": _style_dict(_require_style(snapshot, item.id)),
    }


def _ob_entry(snapshot: SmcSnapshot, item: Orderblock) -> dict:
    return {
        "id": item.id,
        "low": item.low,
        "high": item.high,
        "dir": item.dir,
        "valid": item.valid,
        "style": _style_dict(_require_style(snapshot, item.id)),
    }


def _fvg_entry(snapshot: SmcSnapshot, item: Fvg) -> dict:
    return {
        "id": item.id,
        "low": item.low,
        "high": item.high,
        "dir": item.dir,
        "valid": item.valid,
        "style": _style_dict(_require_style(snapshot, item.id)),
    }


def _sweep_entry(snapshot: SmcSnapshot, item: LiquiditySweep) -> dict:
    return {
        "id": item.id,
        "time": item.time,
        "price": item.price,
        "side": item.side,
        "style": _style_dict(_require_style(snapshot, item.id)),
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

    return {
        "available_categories": [name for name, available in category_pairs if available],
        "missing_categories": [name for name, available in category_pairs if not available],
        "has_bos": has_bos,
        "has_orderblocks": has_orderblocks,
        "has_fvg": has_fvg,
        "has_liquidity_sweeps": has_liquidity_sweeps,
    }


def snapshot_to_pine_payload(
    snapshot: SmcSnapshot,
    *,
    source_plan: dict[str, Any] | None = None,
    structure_status: dict[str, Any] | None = None,
) -> dict:
    bos = [_bos_entry(snapshot, item) for item in snapshot.structure.bos]
    orderblocks = [_ob_entry(snapshot, item) for item in snapshot.structure.orderblocks]
    fvg = [_fvg_entry(snapshot, item) for item in snapshot.structure.fvg]
    liquidity_sweeps = [_sweep_entry(snapshot, item) for item in snapshot.structure.liquidity_sweeps]

    bos.sort(key=lambda x: x["id"])
    orderblocks.sort(key=lambda x: x["id"])
    fvg.sort(key=lambda x: x["id"])
    liquidity_sweeps.sort(key=lambda x: x["id"])

    payload = {
        "symbol": snapshot.symbol,
        "timeframe": snapshot.timeframe,
        "generated_at": snapshot.generated_at,
        "schema_version": snapshot.schema_version,
        "structure_coverage": _structure_coverage(snapshot),
        "bos": bos,
        "orderblocks": orderblocks,
        "fvg": fvg,
        "liquidity_sweeps": liquidity_sweeps,
    }

    if source_plan is not None:
        payload["source_plan"] = dict(source_plan)
    if structure_status is not None:
        payload["structure_status"] = dict(structure_status)

    return payload
