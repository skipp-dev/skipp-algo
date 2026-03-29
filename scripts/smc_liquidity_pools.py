"""V5.2 Liquidity Pools builder.

Identifies buy-side and sell-side liquidity pools, their proximity to
price, clustering density, and untested pool counts.

All fields safe-default to neutral when inputs are unavailable.

Usage::

    from scripts.smc_liquidity_pools import build_liquidity_pools, DEFAULTS

    pools = build_liquidity_pools(snapshot=base_snapshot_df)
    enrichment["liquidity_pools"] = pools
"""
from __future__ import annotations

import logging
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)

# ── Defaults ────────────────────────────────────────────────────

DEFAULTS: dict[str, Any] = {
    "BUY_SIDE_POOL_LEVEL": 0.0,
    "SELL_SIDE_POOL_LEVEL": 0.0,
    "BUY_SIDE_POOL_STRENGTH": 0,        # 0–5
    "SELL_SIDE_POOL_STRENGTH": 0,        # 0–5
    "POOL_PROXIMITY_PCT": 0.0,
    "POOL_CLUSTER_DENSITY": 0,           # 0–5, how tightly pools are clustered
    "UNTESTED_BUY_POOLS": 0,
    "UNTESTED_SELL_POOLS": 0,
    "POOL_IMBALANCE": 0.0,              # -1..+1  (positive = more buy-side)
    "POOL_MAGNET_DIRECTION": "NONE",     # NONE | UP | DOWN
    "POOL_QUALITY_SCORE": 0,             # 0–5
}

# ── Thresholds ──────────────────────────────────────────────────

PROXIMITY_NEAR_PCT = 1.0         # within 1% of price = near
CLUSTER_STRONG_COUNT = 3         # 3+ pools close together = dense cluster
IMBALANCE_SIG_THRESHOLD = 0.3   # abs imbalance above this = directional


def build_liquidity_pools(
    *,
    snapshot: pd.DataFrame | None = None,
    symbol: str = "",
    overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a liquidity pools block from a base snapshot.

    Parameters
    ----------
    snapshot : DataFrame, optional
        Base snapshot with pool-related columns.
    symbol : str
        Ticker to filter in snapshot.
    overrides : dict, optional
        Manual overrides — flat merge, last wins.
    """
    result = dict(DEFAULTS)

    row = _resolve_row(snapshot, symbol)
    if row is not None:
        result["BUY_SIDE_POOL_LEVEL"] = float(row.get("buy_side_pool_level", 0.0))
        result["SELL_SIDE_POOL_LEVEL"] = float(row.get("sell_side_pool_level", 0.0))
        result["BUY_SIDE_POOL_STRENGTH"] = _clamp(int(row.get("buy_side_pool_strength", 0)), 0, 5)
        result["SELL_SIDE_POOL_STRENGTH"] = _clamp(int(row.get("sell_side_pool_strength", 0)), 0, 5)
        result["POOL_PROXIMITY_PCT"] = round(float(row.get("pool_proximity_pct", 0.0)), 4)
        result["POOL_CLUSTER_DENSITY"] = _clamp(int(row.get("pool_cluster_density", 0)), 0, 5)
        result["UNTESTED_BUY_POOLS"] = max(0, int(row.get("untested_buy_pools", 0)))
        result["UNTESTED_SELL_POOLS"] = max(0, int(row.get("untested_sell_pools", 0)))

        result["POOL_IMBALANCE"] = _compute_imbalance(result)
        result["POOL_MAGNET_DIRECTION"] = _magnet_direction(result)
        result["POOL_QUALITY_SCORE"] = _quality_score(result)

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


def _compute_imbalance(r: dict[str, Any]) -> float:
    buy = r["BUY_SIDE_POOL_STRENGTH"] + r["UNTESTED_BUY_POOLS"]
    sell = r["SELL_SIDE_POOL_STRENGTH"] + r["UNTESTED_SELL_POOLS"]
    total = buy + sell
    if total == 0:
        return 0.0
    return round((buy - sell) / total, 4)


def _magnet_direction(r: dict[str, Any]) -> str:
    imb = r["POOL_IMBALANCE"]
    if imb >= IMBALANCE_SIG_THRESHOLD:
        return "UP"
    if imb <= -IMBALANCE_SIG_THRESHOLD:
        return "DOWN"
    return "NONE"


def _quality_score(r: dict[str, Any]) -> int:
    score = 0
    if r["BUY_SIDE_POOL_LEVEL"] > 0 or r["SELL_SIDE_POOL_LEVEL"] > 0:
        score += 1
    if r["BUY_SIDE_POOL_STRENGTH"] >= 3 or r["SELL_SIDE_POOL_STRENGTH"] >= 3:
        score += 1
    if r["POOL_PROXIMITY_PCT"] > 0 and r["POOL_PROXIMITY_PCT"] <= PROXIMITY_NEAR_PCT:
        score += 1
    if r["POOL_CLUSTER_DENSITY"] >= 3:
        score += 1
    if abs(r["POOL_IMBALANCE"]) >= IMBALANCE_SIG_THRESHOLD:
        score += 1
    return min(score, 5)
