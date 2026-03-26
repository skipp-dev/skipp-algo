from __future__ import annotations

from typing import Any

from smc_adapters import (
    build_snapshot_from_raw,
    snapshot_to_dashboard_payload,
    snapshot_to_pine_payload,
)
from smc_core import snapshot_to_dict
from smc_core.types import SmcSnapshot

from .repo_sources import (
    discover_composite_source_plan,
    discover_structure_source_status,
    load_raw_meta_input_composite,
    load_raw_structure_input,
    select_best_structure_source,
)


def _build_snapshot_from_loaded_raw(
    raw_structure: dict[str, Any],
    raw_meta: dict[str, Any],
    *,
    generated_at: float | None = None,
) -> SmcSnapshot:
    return build_snapshot_from_raw(raw_structure, raw_meta, generated_at=generated_at)


def build_snapshot_for_symbol_timeframe(
    symbol: str,
    timeframe: str,
    *,
    source: str = "auto",
    generated_at: float | None = None,
) -> SmcSnapshot:
    composite = discover_composite_source_plan(source=source, symbol=symbol, timeframe=timeframe)
    structure_source = composite["structure"]
    structure_load_source = "auto" if source.strip().lower() == "auto" else structure_source
    raw_structure = load_raw_structure_input(
        symbol,
        timeframe,
        source=structure_load_source,
    )
    raw_meta = load_raw_meta_input_composite(
        symbol,
        timeframe,
        source=source,
    )
    return _build_snapshot_from_loaded_raw(raw_structure, raw_meta, generated_at=generated_at)


def build_dashboard_payload_for_symbol_timeframe(
    symbol: str,
    timeframe: str,
    *,
    source: str = "auto",
    generated_at: float | None = None,
) -> dict:
    snapshot = build_snapshot_for_symbol_timeframe(
        symbol,
        timeframe,
        source=source,
        generated_at=generated_at,
    )
    return snapshot_to_dashboard_payload(snapshot)


def build_pine_payload_for_symbol_timeframe(
    symbol: str,
    timeframe: str,
    *,
    source: str = "auto",
    generated_at: float | None = None,
) -> dict:
    snapshot = build_snapshot_for_symbol_timeframe(
        symbol,
        timeframe,
        source=source,
        generated_at=generated_at,
    )
    return snapshot_to_pine_payload(snapshot)


def build_snapshot_bundle_for_symbol_timeframe(
    symbol: str,
    timeframe: str,
    *,
    source: str = "auto",
    generated_at: float | None = None,
) -> dict:
    selected = select_best_structure_source() if source.strip().lower() == "auto" else None
    composite = discover_composite_source_plan(source=source, symbol=symbol, timeframe=timeframe)
    structure_status = discover_structure_source_status(source=source, symbol=symbol, timeframe=timeframe)
    snapshot = build_snapshot_for_symbol_timeframe(
        symbol,
        timeframe,
        source=source,
        generated_at=generated_at,
    )
    dashboard_payload = snapshot_to_dashboard_payload(snapshot)
    pine_payload = snapshot_to_pine_payload(snapshot)

    source_descriptor = selected if selected is not None else None
    if source_descriptor is None:
        from .repo_sources import discover_repo_sources

        by_name = {item.name: item for item in discover_repo_sources()}
        source_key = source.strip().lower()
        if source_key not in by_name:
            known = ", ".join(sorted(by_name))
            raise ValueError(f"unknown source {source}; expected one of: {known}, auto")
        source_descriptor = by_name[source_key]

    return {
        "source_plan": composite,
        "structure_status": structure_status,
        "source": source_descriptor.to_dict(),
        "snapshot": snapshot_to_dict(snapshot),
        "dashboard_payload": dashboard_payload,
        "pine_payload": pine_payload,
    }
