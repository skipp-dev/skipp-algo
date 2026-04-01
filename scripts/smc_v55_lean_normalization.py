"""Normalize v5.5b lean blocks for generator-facing enrichment payloads.

This is the production normalization step that derives the six lean blocks
from broad enrichment blocks before Pine export and manifest publication.
Existing lean blocks are preserved via builder overrides, so explicit values
remain authoritative while missing fields are backfilled deterministically.
"""

from __future__ import annotations

from typing import Any, cast

import pandas as pd

from scripts.smc_enrichment_types import EnrichmentDict
from scripts.smc_event_risk_light import build_event_risk_light
from scripts.smc_fvg_lifecycle_light import build_fvg_lifecycle_light
from scripts.smc_ob_context_light import build_ob_context_light
from scripts.smc_session_context_light import build_session_context_light
from scripts.smc_signal_quality import build_signal_quality
from scripts.smc_structure_state_light import build_structure_state_light

_PRICE_FIELDS = (
    "current_price",
    "day_close",
    "close",
    "last",
    "previous_close",
    "day_open",
    "open",
)


def _resolve_row(snapshot: pd.DataFrame | None, symbol: str) -> dict[str, Any] | None:
    if snapshot is None or snapshot.empty:
        return None

    df = snapshot
    if symbol and "symbol" in df.columns:
        symbols = df["symbol"].astype(str).str.strip().str.upper()
        match = df.loc[symbols.eq(symbol.strip().upper())]
        if not match.empty:
            return cast(dict[str, Any], match.iloc[0].to_dict())

    if len(df) == 1:
        return cast(dict[str, Any], df.iloc[0].to_dict())

    return None


def infer_current_price(snapshot: pd.DataFrame | None, *, symbol: str = "") -> float:
    """Resolve a best-effort current price from the snapshot row."""
    row = _resolve_row(snapshot, symbol)
    if row is None:
        return 0.0

    for field in _PRICE_FIELDS:
        value = pd.to_numeric(pd.Series([row.get(field)]), errors="coerce").iloc[0]
        if pd.notna(value) and float(value) > 0:
            return float(value)

    return 0.0


def normalize_v55_lean_enrichment(
    enrichment: EnrichmentDict | None,
    *,
    snapshot: pd.DataFrame | None = None,
    symbol: str = "",
) -> EnrichmentDict | None:
    """Return *enrichment* with v5.5b lean blocks fully populated when possible."""
    if enrichment is None:
        return None

    normalized: dict[str, Any] = dict(enrichment)
    current_price = infer_current_price(snapshot, symbol=symbol)

    existing_event_risk_light = cast(dict[str, Any], normalized.get("event_risk_light") or {})
    if "event_risk" in normalized or existing_event_risk_light:
        normalized["event_risk_light"] = build_event_risk_light(
            event_risk=cast(dict[str, Any] | None, normalized.get("event_risk")),
            overrides=existing_event_risk_light,
        )

    existing_session_context_light = cast(dict[str, Any], normalized.get("session_context_light") or {})
    if "session_context" in normalized or "compression_regime" in normalized or existing_session_context_light:
        normalized["session_context_light"] = build_session_context_light(
            session_context=cast(dict[str, Any] | None, normalized.get("session_context")),
            compression_regime=cast(dict[str, Any] | None, normalized.get("compression_regime")),
            overrides=existing_session_context_light,
        )

    existing_ob_context_light = cast(dict[str, Any], normalized.get("ob_context_light") or {})
    if "order_blocks" in normalized or existing_ob_context_light:
        normalized["ob_context_light"] = build_ob_context_light(
            order_blocks=cast(dict[str, Any] | None, normalized.get("order_blocks")),
            current_price=current_price,
            overrides=existing_ob_context_light,
        )

    existing_fvg_lifecycle_light = cast(dict[str, Any], normalized.get("fvg_lifecycle_light") or {})
    if "imbalance_lifecycle" in normalized or existing_fvg_lifecycle_light:
        normalized["fvg_lifecycle_light"] = build_fvg_lifecycle_light(
            imbalance=cast(dict[str, Any] | None, normalized.get("imbalance_lifecycle")),
            current_price=current_price,
            overrides=existing_fvg_lifecycle_light,
        )

    existing_structure_state_light = cast(dict[str, Any], normalized.get("structure_state_light") or {})
    if "structure_state" in normalized or existing_structure_state_light:
        normalized["structure_state_light"] = build_structure_state_light(
            structure_state=cast(dict[str, Any] | None, normalized.get("structure_state")),
            overrides=existing_structure_state_light,
        )

    existing_signal_quality = cast(dict[str, Any], normalized.get("signal_quality") or {})
    signal_quality_inputs = (
        "event_risk",
        "event_risk_light",
        "session_context",
        "session_context_light",
        "order_blocks",
        "ob_context_light",
        "imbalance_lifecycle",
        "fvg_lifecycle_light",
        "structure_state",
        "structure_state_light",
        "liquidity_sweeps",
        "compression_regime",
    )
    if existing_signal_quality or any(key in normalized for key in signal_quality_inputs):
        normalized["signal_quality"] = build_signal_quality(
            enrichment=cast(dict[str, Any], normalized),
            overrides=existing_signal_quality,
        )

    return cast(EnrichmentDict, normalized)
