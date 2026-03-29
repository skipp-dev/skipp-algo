"""V5.3 Imbalance Lifecycle builder.

Derives an explicit lifecycle model for FVG / BPR / liquidity-void
states from microstructure data.  Replaces ad-hoc boolean FVG flags
with a structured lifecycle: creation → partial mitigation → full
mitigation, plus BPR overlap and liquidity-void detection.

All fields safe-default to neutral when inputs are unavailable.

Usage::

    from scripts.smc_imbalance_lifecycle import build_imbalance_lifecycle, DEFAULTS

    imbalance = build_imbalance_lifecycle(snapshot=base_snapshot_df)
    enrichment["imbalance_lifecycle"] = imbalance
"""
from __future__ import annotations

import logging
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)

# ── Defaults ────────────────────────────────────────────────────────

DEFAULTS: dict[str, Any] = {
    "BULL_FVG_ACTIVE": False,
    "BEAR_FVG_ACTIVE": False,
    "BULL_FVG_TOP": 0.0,
    "BULL_FVG_BOTTOM": 0.0,
    "BEAR_FVG_TOP": 0.0,
    "BEAR_FVG_BOTTOM": 0.0,
    "BULL_FVG_PARTIAL_MITIGATION": False,
    "BEAR_FVG_PARTIAL_MITIGATION": False,
    "BULL_FVG_FULL_MITIGATION": False,
    "BEAR_FVG_FULL_MITIGATION": False,
    "BULL_FVG_COUNT": 0,
    "BEAR_FVG_COUNT": 0,
    "BULL_FVG_MITIGATION_PCT": 0.0,
    "BEAR_FVG_MITIGATION_PCT": 0.0,
    "BPR_ACTIVE": False,
    "BPR_DIRECTION": "NONE",         # NONE | BULL | BEAR
    "BPR_TOP": 0.0,
    "BPR_BOTTOM": 0.0,
    "LIQ_VOID_BULL_ACTIVE": False,
    "LIQ_VOID_BEAR_ACTIVE": False,
    "LIQ_VOID_TOP": 0.0,
    "LIQ_VOID_BOTTOM": 0.0,
    "IMBALANCE_STATE": "NONE",       # NONE | FVG_BULL | FVG_BEAR | BPR | LIQ_VOID
}

# ── Thresholds ──────────────────────────────────────────────────────

PARTIAL_MIT_PCT = 0.5       # gap filled beyond this = partial mitigation
FULL_MIT_PCT = 1.0          # gap fully closed
LIQ_VOID_MIN_SIZE_PCT = 2.0  # min gap size % of price for liquidity void


def build_imbalance_lifecycle(
    *,
    snapshot: pd.DataFrame | None = None,
    symbol: str = "",
    overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build an imbalance lifecycle block from a base snapshot.

    Parameters
    ----------
    snapshot : pd.DataFrame | None
        Base microstructure snapshot with OHLC columns.
    symbol : str
        Optional symbol filter.
    overrides : dict | None
        Manual field overrides for operator intervention.

    Returns
    -------
    dict[str, Any]
        Flat dict matching the imbalance lifecycle contract.
    """
    result = dict(DEFAULTS)

    if snapshot is not None and not snapshot.empty:
        df = snapshot.copy()
        if symbol and "symbol" in df.columns:
            df = df[df["symbol"] == symbol]

        if not df.empty:
            result = _derive_imbalance(df, result)

    if overrides:
        for key, val in overrides.items():
            if key in DEFAULTS:
                result[key] = val

    return result


def _derive_imbalance(df: pd.DataFrame, result: dict[str, Any]) -> dict[str, Any]:
    """Derive imbalance lifecycle from OHLC bars."""
    for col in ("high", "low", "close", "open"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    if not {"high", "low", "close", "open"}.issubset(df.columns):
        return result

    df = df.dropna(subset=["high", "low", "close", "open"]).reset_index(drop=True)
    if len(df) < 3:
        return result

    # Detect FVGs (3-bar pattern: gap between bar[i-2].high/low and bar[i].low/high)
    bull_fvgs: list[tuple[int, float, float]] = []   # (bar_idx, top, bottom)
    bear_fvgs: list[tuple[int, float, float]] = []

    for i in range(2, len(df)):
        bar_prev2_high = float(df.iloc[i - 2]["high"])
        bar_curr_low = float(df.iloc[i]["low"])
        bar_prev2_low = float(df.iloc[i - 2]["low"])
        bar_curr_high = float(df.iloc[i]["high"])

        # Bullish FVG: gap up — bar[i].low > bar[i-2].high
        if bar_curr_low > bar_prev2_high:
            bull_fvgs.append((i, bar_curr_low, bar_prev2_high))

        # Bearish FVG: gap down — bar[i].high < bar[i-2].low
        if bar_curr_high < bar_prev2_low:
            bear_fvgs.append((i, bar_prev2_low, bar_curr_high))

    last_close = float(df.iloc[-1]["close"])
    last_high = float(df.iloc[-1]["high"])
    last_low = float(df.iloc[-1]["low"])

    # Process bullish FVGs
    active_bull_count = 0
    newest_bull_fvg = None
    for idx, top, bottom in bull_fvgs:
        gap_size = top - bottom
        if gap_size <= 0:
            continue
        # Check mitigation: price has come back down into the gap
        fill_depth = max(0.0, top - last_low) if last_low < top else 0.0
        mit_pct = min(fill_depth / gap_size, 1.0) if gap_size > 0 else 0.0

        if mit_pct < FULL_MIT_PCT:
            active_bull_count += 1
            if newest_bull_fvg is None or idx > newest_bull_fvg[0]:
                newest_bull_fvg = (idx, top, bottom, mit_pct)

    if newest_bull_fvg is not None:
        _, top, bottom, mit_pct = newest_bull_fvg
        result["BULL_FVG_ACTIVE"] = True
        result["BULL_FVG_TOP"] = top
        result["BULL_FVG_BOTTOM"] = bottom
        result["BULL_FVG_MITIGATION_PCT"] = round(mit_pct, 4)
        result["BULL_FVG_PARTIAL_MITIGATION"] = mit_pct >= PARTIAL_MIT_PCT
        result["BULL_FVG_FULL_MITIGATION"] = False  # still active
    elif bull_fvgs:
        # All were fully mitigated
        _, top, bottom = bull_fvgs[-1]
        result["BULL_FVG_FULL_MITIGATION"] = True
        result["BULL_FVG_MITIGATION_PCT"] = 1.0

    result["BULL_FVG_COUNT"] = active_bull_count

    # Process bearish FVGs
    active_bear_count = 0
    newest_bear_fvg = None
    for idx, top, bottom in bear_fvgs:
        gap_size = top - bottom
        if gap_size <= 0:
            continue
        fill_depth = max(0.0, last_high - bottom) if last_high > bottom else 0.0
        mit_pct = min(fill_depth / gap_size, 1.0) if gap_size > 0 else 0.0

        if mit_pct < FULL_MIT_PCT:
            active_bear_count += 1
            if newest_bear_fvg is None or idx > newest_bear_fvg[0]:
                newest_bear_fvg = (idx, top, bottom, mit_pct)

    if newest_bear_fvg is not None:
        _, top, bottom, mit_pct = newest_bear_fvg
        result["BEAR_FVG_ACTIVE"] = True
        result["BEAR_FVG_TOP"] = top
        result["BEAR_FVG_BOTTOM"] = bottom
        result["BEAR_FVG_MITIGATION_PCT"] = round(mit_pct, 4)
        result["BEAR_FVG_PARTIAL_MITIGATION"] = mit_pct >= PARTIAL_MIT_PCT
        result["BEAR_FVG_FULL_MITIGATION"] = False
    elif bear_fvgs:
        result["BEAR_FVG_FULL_MITIGATION"] = True
        result["BEAR_FVG_MITIGATION_PCT"] = 1.0

    result["BEAR_FVG_COUNT"] = active_bear_count

    # BPR detection: overlapping bull + bear FVGs
    if result["BULL_FVG_ACTIVE"] and result["BEAR_FVG_ACTIVE"]:
        overlap_top = min(result["BULL_FVG_TOP"], result["BEAR_FVG_TOP"])
        overlap_bottom = max(result["BULL_FVG_BOTTOM"], result["BEAR_FVG_BOTTOM"])
        if overlap_top > overlap_bottom:
            result["BPR_ACTIVE"] = True
            result["BPR_TOP"] = overlap_top
            result["BPR_BOTTOM"] = overlap_bottom
            result["BPR_DIRECTION"] = "BULL" if last_close > (overlap_top + overlap_bottom) / 2 else "BEAR"

    # Liquidity void: very large FVG (> LIQ_VOID_MIN_SIZE_PCT of price)
    mid_price = (last_high + last_low) / 2 if (last_high + last_low) > 0 else 1.0
    for idx, top, bottom in bull_fvgs:
        gap_pct = (top - bottom) / mid_price * 100
        if gap_pct >= LIQ_VOID_MIN_SIZE_PCT:
            result["LIQ_VOID_BULL_ACTIVE"] = True
            result["LIQ_VOID_TOP"] = top
            result["LIQ_VOID_BOTTOM"] = bottom
            break

    for idx, top, bottom in bear_fvgs:
        gap_pct = (top - bottom) / mid_price * 100
        if gap_pct >= LIQ_VOID_MIN_SIZE_PCT:
            result["LIQ_VOID_BEAR_ACTIVE"] = True
            if not result["LIQ_VOID_BULL_ACTIVE"]:
                result["LIQ_VOID_TOP"] = top
                result["LIQ_VOID_BOTTOM"] = bottom
            break

    # Composite state
    if result["BPR_ACTIVE"]:
        result["IMBALANCE_STATE"] = "BPR"
    elif result["LIQ_VOID_BULL_ACTIVE"] or result["LIQ_VOID_BEAR_ACTIVE"]:
        result["IMBALANCE_STATE"] = "LIQ_VOID"
    elif result["BULL_FVG_ACTIVE"]:
        result["IMBALANCE_STATE"] = "FVG_BULL"
    elif result["BEAR_FVG_ACTIVE"]:
        result["IMBALANCE_STATE"] = "FVG_BEAR"

    return result
