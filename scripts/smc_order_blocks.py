"""V5.2 Order Block Layer builder.

Derives order block context from microstructure data: nearest
bull/bear OB levels, freshness, mitigation status, confluence
with FVG, and quality scoring.

All fields safe-default to neutral when inputs are unavailable.

Usage::

    from scripts.smc_order_blocks import build_order_blocks, DEFAULTS

    ob = build_order_blocks(snapshot=base_snapshot_df)
    enrichment["order_blocks"] = ob
"""
from __future__ import annotations

import logging
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)

# ── Defaults ────────────────────────────────────────────────────

DEFAULTS: dict[str, Any] = {
    "NEAREST_BULL_OB_LEVEL": 0.0,
    "NEAREST_BEAR_OB_LEVEL": 0.0,
    "BULL_OB_FRESHNESS": 0,             # 0–5: how recent (5 = very fresh)
    "BEAR_OB_FRESHNESS": 0,             # 0–5
    "BULL_OB_MITIGATED": False,
    "BEAR_OB_MITIGATED": False,
    "BULL_OB_FVG_CONFLUENCE": False,
    "BEAR_OB_FVG_CONFLUENCE": False,
    "OB_DENSITY": 0,                    # 0–5: count of nearby OBs
    "OB_BIAS": "NEUTRAL",              # BULLISH | BEARISH | NEUTRAL
    "OB_NEAREST_DISTANCE_PCT": 0.0,    # distance to nearest OB as %
    "OB_STRENGTH_SCORE": 0,            # 0–5: strongest OB quality
    "OB_CONTEXT_SCORE": 0,             # 0–5: overall OB context quality
}

# ── Thresholds ──────────────────────────────────────────────────

FRESHNESS_MAX_BARS = 50    # OB older than this = stale
NEAR_DISTANCE_PCT = 1.5    # within 1.5% = near
DENSITY_STRONG = 3          # 3+ OBs nearby = dense


def build_order_blocks(
    *,
    snapshot: pd.DataFrame | None = None,
    symbol: str = "",
    overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build an order block context block from a base snapshot.

    Parameters
    ----------
    snapshot : DataFrame, optional
        Base snapshot with OB-related columns.
    symbol : str
        Ticker to filter in snapshot.
    overrides : dict, optional
        Manual overrides — flat merge, last wins.
    """
    result = dict(DEFAULTS)

    row = _resolve_row(snapshot, symbol)
    if row is not None:
        result["NEAREST_BULL_OB_LEVEL"] = float(row.get("nearest_bull_ob_level", 0.0))
        result["NEAREST_BEAR_OB_LEVEL"] = float(row.get("nearest_bear_ob_level", 0.0))
        result["BULL_OB_FRESHNESS"] = _clamp(int(row.get("bull_ob_freshness", 0)), 0, 5)
        result["BEAR_OB_FRESHNESS"] = _clamp(int(row.get("bear_ob_freshness", 0)), 0, 5)
        result["BULL_OB_MITIGATED"] = bool(row.get("bull_ob_mitigated", False))
        result["BEAR_OB_MITIGATED"] = bool(row.get("bear_ob_mitigated", False))
        result["BULL_OB_FVG_CONFLUENCE"] = bool(row.get("bull_ob_fvg_confluence", False))
        result["BEAR_OB_FVG_CONFLUENCE"] = bool(row.get("bear_ob_fvg_confluence", False))
        result["OB_DENSITY"] = _clamp(int(row.get("ob_density", 0)), 0, 5)
        result["OB_NEAREST_DISTANCE_PCT"] = round(float(row.get("ob_nearest_distance_pct", 0.0)), 4)
        result["OB_STRENGTH_SCORE"] = _clamp(int(row.get("ob_strength_score", 0)), 0, 5)

        result["OB_BIAS"] = _compute_ob_bias(result)
        result["OB_CONTEXT_SCORE"] = _compute_context_score(result)

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


def _clamp(val: int, lo: int, hi: int) -> int:
    return max(lo, min(val, hi))


def _compute_ob_bias(r: dict[str, Any]) -> str:
    bull_score = 0
    bear_score = 0
    if r["NEAREST_BULL_OB_LEVEL"] > 0 and not r["BULL_OB_MITIGATED"]:
        bull_score += r["BULL_OB_FRESHNESS"]
    if r["NEAREST_BEAR_OB_LEVEL"] > 0 and not r["BEAR_OB_MITIGATED"]:
        bear_score += r["BEAR_OB_FRESHNESS"]
    if r["BULL_OB_FVG_CONFLUENCE"]:
        bull_score += 2
    if r["BEAR_OB_FVG_CONFLUENCE"]:
        bear_score += 2
    if bull_score > bear_score:
        return "BULLISH"
    if bear_score > bull_score:
        return "BEARISH"
    return "NEUTRAL"


def _compute_context_score(r: dict[str, Any]) -> int:
    score = 0
    if r["NEAREST_BULL_OB_LEVEL"] > 0 or r["NEAREST_BEAR_OB_LEVEL"] > 0:
        score += 1
    if r["BULL_OB_FRESHNESS"] >= 3 or r["BEAR_OB_FRESHNESS"] >= 3:
        score += 1
    if r["BULL_OB_FVG_CONFLUENCE"] or r["BEAR_OB_FVG_CONFLUENCE"]:
        score += 1
    if r["OB_DENSITY"] >= DENSITY_STRONG:
        score += 1
    if r["OB_STRENGTH_SCORE"] >= 3:
        score += 1
    return min(score, 5)
