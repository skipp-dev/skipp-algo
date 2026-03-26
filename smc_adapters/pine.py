from __future__ import annotations

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


def snapshot_to_pine_payload(snapshot: SmcSnapshot) -> dict:
    bos = [_bos_entry(snapshot, item) for item in snapshot.structure.bos]
    orderblocks = [_ob_entry(snapshot, item) for item in snapshot.structure.orderblocks]
    fvg = [_fvg_entry(snapshot, item) for item in snapshot.structure.fvg]
    liquidity_sweeps = [_sweep_entry(snapshot, item) for item in snapshot.structure.liquidity_sweeps]

    bos.sort(key=lambda x: x["id"])
    orderblocks.sort(key=lambda x: x["id"])
    fvg.sort(key=lambda x: x["id"])
    liquidity_sweeps.sort(key=lambda x: x["id"])

    return {
        "symbol": snapshot.symbol,
        "timeframe": snapshot.timeframe,
        "generated_at": snapshot.generated_at,
        "schema_version": snapshot.schema_version,
        "bos": bos,
        "orderblocks": orderblocks,
        "fvg": fvg,
        "liquidity_sweeps": liquidity_sweeps,
    }
