"""V5.3 Structure State builder.

Derives a first-class structure-state block from microstructure snapshot
data: BOS/CHoCH events, swing counts, directional state, and freshness.

This replaces ad-hoc qualifier-style outputs with an explicit, auditable
state machine.  ``scripts/smc_structure_qualifiers.py`` remains available
as an auxiliary context layer (PPDD, broken fractal, OB/FVG stack) but
is NOT the v5.3 end-state.

All fields safe-default to neutral when inputs are unavailable.

Usage::

    from scripts.smc_structure_state import build_structure_state, DEFAULTS

    state = build_structure_state(snapshot=base_snapshot_df)
    enrichment["structure_state"] = state
"""
from __future__ import annotations

import logging
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)

# ── Defaults ────────────────────────────────────────────────────────

DEFAULTS: dict[str, Any] = {
    "STRUCTURE_STATE": "NEUTRAL",        # BULLISH | BEARISH | NEUTRAL
    "STRUCTURE_BULL_ACTIVE": False,
    "STRUCTURE_BEAR_ACTIVE": False,
    "CHOCH_BULL": False,
    "CHOCH_BEAR": False,
    "BOS_BULL": False,
    "BOS_BEAR": False,
    "STRUCTURE_LAST_EVENT": "NONE",      # NONE | BOS_BULL | BOS_BEAR | CHOCH_BULL | CHOCH_BEAR
    "STRUCTURE_EVENT_AGE_BARS": 0,
    "STRUCTURE_FRESH": False,
    "ACTIVE_SUPPORT": 0.0,
    "ACTIVE_RESISTANCE": 0.0,
    "SUPPORT_ACTIVE": False,
    "RESISTANCE_ACTIVE": False,
}

# ── Thresholds ──────────────────────────────────────────────────────

FRESHNESS_MAX_BARS = 10         # event within this many bars = fresh
BOS_MIN_MOVE_PCT = 0.1          # min % move to qualify as BOS
CHOCH_MIN_MOVE_PCT = 0.05       # min % move to qualify as CHoCH


def build_structure_state(
    *,
    snapshot: pd.DataFrame | None = None,
    symbol: str = "",
    overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a structure-state block from a base snapshot.

    Parameters
    ----------
    snapshot : pd.DataFrame | None
        Base microstructure snapshot.  When *None* or empty, returns
        safe defaults.
    symbol : str
        Optional symbol filter — when non-empty, only rows for this
        symbol are considered.
    overrides : dict | None
        Manual field overrides for operator intervention.

    Returns
    -------
    dict[str, Any]
        Flat dict matching :class:`StructureStateBlock` from
        ``smc_enrichment_types``.
    """
    result = dict(DEFAULTS)

    if snapshot is not None and not snapshot.empty:
        df = snapshot.copy()
        if symbol and "symbol" in df.columns:
            df = df[df["symbol"] == symbol]

        if not df.empty:
            result = _derive_structure(df, result)

    if overrides:
        for key, val in overrides.items():
            if key in DEFAULTS:
                result[key] = val

    return result


def _derive_structure(df: pd.DataFrame, result: dict[str, Any]) -> dict[str, Any]:
    """Derive structure state from snapshot columns when available."""
    # Ensure numeric types for price columns
    for col in ("high", "low", "close", "open"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    if not {"high", "low", "close"}.issubset(df.columns):
        return result

    df = df.dropna(subset=["high", "low", "close"]).reset_index(drop=True)
    if len(df) < 3:
        return result

    # Detect swing highs and swing lows (simple 3-bar pivot)
    highs: list[tuple[int, float]] = []
    lows: list[tuple[int, float]] = []

    for i in range(1, len(df) - 1):
        h = float(df.iloc[i]["high"])
        h_prev = float(df.iloc[i - 1]["high"])
        h_next = float(df.iloc[i + 1]["high"])
        if h > h_prev and h > h_next:
            highs.append((i, h))

        lo = float(df.iloc[i]["low"])
        lo_prev = float(df.iloc[i - 1]["low"])
        lo_next = float(df.iloc[i + 1]["low"])
        if lo < lo_prev and lo < lo_next:
            lows.append((i, lo))

    if not highs or not lows:
        return result

    # Track BOS (Break of Structure) and CHoCH (Change of Character)
    last_event = "NONE"
    last_event_bar = 0
    bos_bull = False
    bos_bear = False
    choch_bull = False
    choch_bear = False

    # Use the last two swing highs and lows for structure analysis
    last_close = float(df.iloc[-1]["close"])

    if len(highs) >= 2:
        prev_high = highs[-2][1]
        curr_high = highs[-1][1]
        # BOS Bull: current swing high breaks previous swing high
        if curr_high > prev_high:
            move_pct = (curr_high - prev_high) / prev_high * 100
            if move_pct >= BOS_MIN_MOVE_PCT:
                bos_bull = True
                last_event = "BOS_BULL"
                last_event_bar = highs[-1][0]

    if len(lows) >= 2:
        prev_low = lows[-2][1]
        curr_low = lows[-1][1]
        # BOS Bear: current swing low breaks previous swing low
        if curr_low < prev_low:
            move_pct = (prev_low - curr_low) / prev_low * 100
            if move_pct >= BOS_MIN_MOVE_PCT:
                bos_bear = True
                last_event = "BOS_BEAR"
                last_event_bar = lows[-1][0]

    # CHoCH detection: price breaks the opposite swing
    if len(highs) >= 1 and len(lows) >= 1:
        latest_high_idx, latest_high = highs[-1]
        latest_low_idx, latest_low = lows[-1]

        # CHoCH Bull: after bearish structure, close breaks above resistance
        if latest_low_idx > latest_high_idx and last_close > latest_high:
            choch_bull = True
            last_event = "CHOCH_BULL"
            last_event_bar = len(df) - 1

        # CHoCH Bear: after bullish structure, close breaks below support
        if latest_high_idx > latest_low_idx and last_close < latest_low:
            choch_bear = True
            last_event = "CHOCH_BEAR"
            last_event_bar = len(df) - 1

    # Determine overall structure state
    if choch_bull or (bos_bull and not bos_bear):
        state = "BULLISH"
    elif choch_bear or (bos_bear and not bos_bull):
        state = "BEARISH"
    else:
        state = "NEUTRAL"

    event_age = len(df) - 1 - last_event_bar if last_event != "NONE" else 0
    fresh = last_event != "NONE" and event_age <= FRESHNESS_MAX_BARS

    # Active support/resistance from latest swings
    active_support = lows[-1][1]
    active_resistance = highs[-1][1]

    result["STRUCTURE_STATE"] = state
    result["STRUCTURE_BULL_ACTIVE"] = state == "BULLISH"
    result["STRUCTURE_BEAR_ACTIVE"] = state == "BEARISH"
    result["CHOCH_BULL"] = choch_bull
    result["CHOCH_BEAR"] = choch_bear
    result["BOS_BULL"] = bos_bull
    result["BOS_BEAR"] = bos_bear
    result["STRUCTURE_LAST_EVENT"] = last_event
    result["STRUCTURE_EVENT_AGE_BARS"] = event_age
    result["STRUCTURE_FRESH"] = fresh
    result["ACTIVE_SUPPORT"] = active_support
    result["ACTIVE_RESISTANCE"] = active_resistance
    result["SUPPORT_ACTIVE"] = active_support > 0.0
    result["RESISTANCE_ACTIVE"] = active_resistance > 0.0

    return result
