"""V5.2 Liquidity Sweeps builder.

Detects recent liquidity sweep events from microstructure data
(high/low sweeps, type, direction) and scores sweep quality.

All fields safe-default to neutral when inputs are unavailable.

Usage::

    from scripts.smc_liquidity_sweeps import build_liquidity_sweeps, DEFAULTS

    sweeps = build_liquidity_sweeps(snapshot=base_snapshot_df)
    enrichment["liquidity_sweeps"] = sweeps
"""
from __future__ import annotations

import logging
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)

# ── Defaults ────────────────────────────────────────────────────

DEFAULTS: dict[str, Any] = {
    "RECENT_BULL_SWEEP": False,
    "RECENT_BEAR_SWEEP": False,
    "SWEEP_TYPE": "NONE",              # NONE | STOP_HUNT | LIQUIDITY_GRAB | INDUCEMENT
    "SWEEP_DIRECTION": "NONE",         # NONE | BULL | BEAR
    "SWEEP_ZONE_TOP": 0.0,
    "SWEEP_ZONE_BOTTOM": 0.0,
    "SWEEP_RECLAIM_ACTIVE": False,
    "LIQUIDITY_TAKEN_DIRECTION": "NONE",  # NONE | BUY_SIDE | SELL_SIDE
    "SWEEP_QUALITY_SCORE": 0,             # 0–5
}

# ── Thresholds ──────────────────────────────────────────────────

SWEEP_DEPTH_MIN_PCT = 0.1     # min depth % for a valid sweep
SWEEP_RECLAIM_MAX_BARS = 5    # bars within which reclaim must occur
SWEEP_VOLUME_RATIO_MIN = 1.2  # volume on sweep bar vs average


def build_liquidity_sweeps(
    *,
    snapshot: pd.DataFrame | None = None,
    symbol: str = "",
    overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a liquidity sweeps block from a base snapshot.

    Parameters
    ----------
    snapshot : DataFrame, optional
        Base snapshot with sweep-related columns.
    symbol : str
        Ticker to filter in snapshot.
    overrides : dict, optional
        Manual overrides — flat merge, last wins.
    """
    result = dict(DEFAULTS)

    row = _resolve_row(snapshot, symbol)
    if row is not None:
        bull_sweep = bool(row.get("recent_bull_sweep", False))
        bear_sweep = bool(row.get("recent_bear_sweep", False))

        result["RECENT_BULL_SWEEP"] = bull_sweep
        result["RECENT_BEAR_SWEEP"] = bear_sweep

        result["SWEEP_TYPE"] = _classify_sweep_type(row)

        if bull_sweep and not bear_sweep:
            result["SWEEP_DIRECTION"] = "BULL"
            result["LIQUIDITY_TAKEN_DIRECTION"] = "SELL_SIDE"
        elif bear_sweep and not bull_sweep:
            result["SWEEP_DIRECTION"] = "BEAR"
            result["LIQUIDITY_TAKEN_DIRECTION"] = "BUY_SIDE"
        elif bull_sweep and bear_sweep:
            result["SWEEP_DIRECTION"] = "BULL" if row.get("sweep_bias_bull", True) else "BEAR"
            result["LIQUIDITY_TAKEN_DIRECTION"] = "SELL_SIDE" if result["SWEEP_DIRECTION"] == "BULL" else "BUY_SIDE"

        result["SWEEP_ZONE_TOP"] = float(row.get("sweep_zone_top", 0.0))
        result["SWEEP_ZONE_BOTTOM"] = float(row.get("sweep_zone_bottom", 0.0))
        result["SWEEP_RECLAIM_ACTIVE"] = bool(row.get("sweep_reclaim_active", False))

        result["SWEEP_QUALITY_SCORE"] = _compute_quality_score(result, row)

    if overrides:
        for key, val in overrides.items():
            if key in DEFAULTS:
                result[key] = val

    return result


# ── Helpers ─────────────────────────────────────────────────────


def _resolve_row(df: pd.DataFrame | None, symbol: str) -> dict[str, Any] | None:
    if df is None or df.empty:
        return None
    if symbol and "symbol" in df.columns:
        match = df.loc[df["symbol"] == symbol]
        if not match.empty:
            return match.iloc[0].to_dict()
    if len(df) == 1:
        return df.iloc[0].to_dict()
    return None


def _classify_sweep_type(row: dict[str, Any]) -> str:
    sweep_type = str(row.get("sweep_type", "")).upper()
    if sweep_type in ("STOP_HUNT", "LIQUIDITY_GRAB", "INDUCEMENT"):
        return sweep_type
    if row.get("recent_bull_sweep") or row.get("recent_bear_sweep"):
        depth = float(row.get("sweep_depth_pct", 0))
        vol_ratio = float(row.get("sweep_volume_ratio", 0))
        if depth >= SWEEP_DEPTH_MIN_PCT * 3 and vol_ratio >= SWEEP_VOLUME_RATIO_MIN:
            return "STOP_HUNT"
        if vol_ratio >= SWEEP_VOLUME_RATIO_MIN:
            return "LIQUIDITY_GRAB"
        return "INDUCEMENT"
    return "NONE"


def _compute_quality_score(result: dict[str, Any], row: dict[str, Any]) -> int:
    score = 0
    if result["RECENT_BULL_SWEEP"] or result["RECENT_BEAR_SWEEP"]:
        score += 1
    if result["SWEEP_TYPE"] in ("STOP_HUNT", "LIQUIDITY_GRAB"):
        score += 1
    if result["SWEEP_RECLAIM_ACTIVE"]:
        score += 1
    depth = float(row.get("sweep_depth_pct", 0))
    if depth >= SWEEP_DEPTH_MIN_PCT:
        score += 1
    vol_ratio = float(row.get("sweep_volume_ratio", 0))
    if vol_ratio >= SWEEP_VOLUME_RATIO_MIN:
        score += 1
    return min(score, 5)
