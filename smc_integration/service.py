from __future__ import annotations

from typing import Any
from pathlib import Path

import pandas as pd

from smc_adapters import (
    build_meta_from_raw,
    build_structure_from_raw,
    snapshot_to_dashboard_payload,
    snapshot_to_pine_payload,
)
from smc_core import apply_layering, snapshot_to_dict
from smc_core.types import SmcSnapshot
from scripts.load_databento_export_bundle import load_export_bundle
from scripts.smc_htf_context import build_htf_bias_context
from scripts.smc_session_context import build_session_liquidity_context
from scripts.smc_structure_qualifiers import build_structure_qualifiers
from smc_integration.sources import structure_artifact_json

from .repo_sources import (
    discover_composite_source_plan,
    discover_structure_source_status,
    load_raw_meta_input_composite,
    load_raw_structure_input,
    select_best_structure_source,
)


_DEFAULT_EXPORT_DIR = Path("artifacts") / "smc_microstructure_exports"


def _load_symbol_bars_for_context(symbol: str, timeframe: str) -> pd.DataFrame:
    try:
        bundle = load_export_bundle(_DEFAULT_EXPORT_DIR, manifest_prefix="databento_volatility_production_")
    except Exception:
        return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume", "symbol"]) 

    frames = bundle.get("frames", {})
    symbol_name = str(symbol).strip().upper()
    tf = str(timeframe).strip()

    if tf == "1D":
        daily = frames.get("daily_bars")
        if isinstance(daily, pd.DataFrame) and not daily.empty:
            bars = daily.copy()
            bars["symbol"] = bars.get("symbol", "").astype(str).str.strip().str.upper()
            bars = bars.loc[bars["symbol"].eq(symbol_name)].copy()
            if bars.empty:
                return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume", "symbol"])
            bars["timestamp"] = pd.to_datetime(bars.get("trade_date"), utc=True, errors="coerce").astype("int64") // 10**9
            for col in ("open", "high", "low", "close"):
                bars[col] = pd.to_numeric(bars.get(col), errors="coerce")
            bars["volume"] = pd.to_numeric(bars.get("volume", 0.0), errors="coerce").fillna(0.0)
            return bars[["timestamp", "open", "high", "low", "close", "volume", "symbol"]].dropna().reset_index(drop=True)

    intraday = frames.get("full_universe_second_detail_open")
    if isinstance(intraday, pd.DataFrame) and not intraday.empty:
        bars = intraday.copy()
        bars["symbol"] = bars.get("symbol", "").astype(str).str.strip().str.upper()
        bars = bars.loc[bars["symbol"].eq(symbol_name)].copy()
        if bars.empty:
            return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume", "symbol"])
        bars["timestamp"] = pd.to_datetime(bars.get("timestamp"), utc=True, errors="coerce").astype("int64") // 10**9
        for col in ("open", "high", "low", "close"):
            bars[col] = pd.to_numeric(bars.get(col), errors="coerce")
        bars["volume"] = pd.to_numeric(bars.get("volume", 0.0), errors="coerce").fillna(0.0)
        return bars[["timestamp", "open", "high", "low", "close", "volume", "symbol"]].dropna().reset_index(drop=True)

    return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume", "symbol"])


def _build_snapshot_from_loaded_raw(
    raw_structure: dict[str, Any],
    raw_meta: dict[str, Any],
    *,
    generated_at: float | None = None,
) -> SmcSnapshot:
    structure = build_structure_from_raw(raw_structure)
    meta = build_meta_from_raw(raw_meta)
    return apply_layering(structure, meta, generated_at=generated_at)


def _load_structure_input_and_context(
    symbol: str,
    timeframe: str,
    *,
    source: str,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    composite = discover_composite_source_plan(source=source, symbol=symbol, timeframe=timeframe)
    structure_source = composite["structure"]
    structure_load_source = "auto" if source.strip().lower() == "auto" else structure_source

    raw_structure = load_raw_structure_input(
        symbol,
        timeframe,
        source=structure_load_source,
    )

    if structure_source == "structure_artifact_json":
        structure_context = structure_artifact_json.load_structure_context_input(symbol, timeframe)
        return raw_structure, structure_context

    return raw_structure, None


def build_snapshot_for_symbol_timeframe(
    symbol: str,
    timeframe: str,
    *,
    source: str = "auto",
    generated_at: float | None = None,
) -> SmcSnapshot:
    raw_structure, _ = _load_structure_input_and_context(symbol, timeframe, source=source)
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
    source_plan = discover_composite_source_plan(source=source, symbol=symbol, timeframe=timeframe)
    structure_status = discover_structure_source_status(source=source, symbol=symbol, timeframe=timeframe)
    snapshot = build_snapshot_for_symbol_timeframe(
        symbol,
        timeframe,
        source=source,
        generated_at=generated_at,
    )
    return snapshot_to_dashboard_payload(
        snapshot,
        source_plan=source_plan,
        structure_status=structure_status,
    )


def build_pine_payload_for_symbol_timeframe(
    symbol: str,
    timeframe: str,
    *,
    source: str = "auto",
    generated_at: float | None = None,
) -> dict:
    source_plan = discover_composite_source_plan(source=source, symbol=symbol, timeframe=timeframe)
    structure_status = discover_structure_source_status(source=source, symbol=symbol, timeframe=timeframe)
    snapshot = build_snapshot_for_symbol_timeframe(
        symbol,
        timeframe,
        source=source,
        generated_at=generated_at,
    )
    return snapshot_to_pine_payload(
        snapshot,
        source_plan=source_plan,
        structure_status=structure_status,
    )


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
    raw_structure, normalized_structure_context = _load_structure_input_and_context(symbol, timeframe, source=source)
    raw_meta = load_raw_meta_input_composite(
        symbol,
        timeframe,
        source=source,
    )
    snapshot = _build_snapshot_from_loaded_raw(raw_structure, raw_meta, generated_at=generated_at)
    dashboard_payload = snapshot_to_dashboard_payload(
        snapshot,
        source_plan=composite,
        structure_status=structure_status,
    )
    pine_payload = snapshot_to_pine_payload(
        snapshot,
        source_plan=composite,
        structure_status=structure_status,
    )

    source_descriptor = selected if selected is not None else None
    if source_descriptor is None:
        from .repo_sources import discover_repo_sources

        by_name = {item.name: item for item in discover_repo_sources()}
        source_key = source.strip().lower()
        if source_key not in by_name:
            known = ", ".join(sorted(by_name))
            raise ValueError(f"unknown source {source}; expected one of: {known}, auto")
        source_descriptor = by_name[source_key]

    bars = _load_symbol_bars_for_context(symbol, timeframe)
    if bars.empty:
        structure_qualifiers: dict[str, Any] = {}
        session_context: dict[str, Any] = {}
        htf_context: dict[str, Any] = {}
    else:
        structure_qualifiers = build_structure_qualifiers(bars, pivot_lookup=1)
        session_context = build_session_liquidity_context(bars, tz="America/New_York")
        htf_context = build_htf_bias_context(bars, timeframe=timeframe, htf_frames=None)

    structure_context = normalized_structure_context

    out = {
        "source_plan": composite,
        "structure_status": structure_status,
        "source": source_descriptor.to_dict(),
        "snapshot": snapshot_to_dict(snapshot),
        "dashboard_payload": dashboard_payload,
        "pine_payload": pine_payload,
        "structure_qualifiers": structure_qualifiers,
        "session_context": session_context,
        "htf_context": htf_context,
    }
    if structure_context is not None:
        out["structure_context"] = structure_context

    return out
