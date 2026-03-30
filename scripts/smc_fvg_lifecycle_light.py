"""V5.5 FVG / Imbalance Lifecycle Light adapter.

Derives 6 compact user-facing fields from the broad v5.3 imbalance
lifecycle block.  Picks the *primary* (most relevant) FVG and surfaces
its key attributes.

Note: FVG_MATURITY_LEVEL is a fill-derived proxy (0-3), not actual bar age.
True bar-age is not available from the broad block.  The proxy levels are:
  0 = minimal fill (<20%)  → likely fresh
  1 = moderate fill (20-50%) → aging
  2 = heavy fill (50-80%)   → mature
  3 = near-full fill (≥80%) → expiring

Usage::

    from scripts.smc_fvg_lifecycle_light import build_fvg_lifecycle_light, DEFAULTS

    light = build_fvg_lifecycle_light(imbalance=enrichment.get("imbalance_lifecycle", {}))
    enrichment["fvg_lifecycle_light"] = light
"""
from __future__ import annotations

from typing import Any

# ── Defaults ────────────────────────────────────────────────────────

DEFAULTS: dict[str, Any] = {
    "PRIMARY_FVG_SIDE": "NONE",        # BULL | BEAR | NONE
    "PRIMARY_FVG_DISTANCE": 0.0,       # pct distance from price
    "FVG_FILL_PCT": 0.0,               # 0.0-1.0
    "FVG_MATURITY_LEVEL": 0,           # 0-3 fill-derived maturity proxy
    "FVG_FRESH": False,
    "FVG_INVALIDATED": False,
}

# Maturity thresholds (fill-based)
MATURITY_FRESH_MAX = 1  # maturity 0-1 = fresh
FRESHNESS_MAX_BARS = 10  # kept for backward compat in tests


def build_fvg_lifecycle_light(
    *,
    imbalance: dict[str, Any] | None = None,
    current_price: float = 0.0,
    overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the v5.5 FVG lifecycle light surface.

    Selection logic for *primary* FVG:
    1. Prefer active (not fully mitigated) FVGs
    2. Among active, prefer the one closer to current price
    3. If both bull and bear are active, pick the nearest

    Parameters
    ----------
    imbalance : dict | None
        Full imbalance-lifecycle block from :func:`build_imbalance_lifecycle`.
    current_price : float
        Current price for distance calculation.
    overrides : dict | None
        Manual field overrides.

    Returns
    -------
    dict[str, Any]
        Flat dict with 6 lean fields.
    """
    result = dict(DEFAULTS)
    il = imbalance or {}

    bull_active = bool(il.get("BULL_FVG_ACTIVE", False))
    bear_active = bool(il.get("BEAR_FVG_ACTIVE", False))

    if not bull_active and not bear_active:
        if overrides:
            for k, v in overrides.items():
                if k in result:
                    result[k] = v
        return result

    # Calculate distances and pick primary
    bull_mid = 0.0
    bear_mid = 0.0
    bull_dist = float("inf")
    bear_dist = float("inf")

    if bull_active:
        bull_top = float(il.get("BULL_FVG_TOP", 0.0))
        bull_bottom = float(il.get("BULL_FVG_BOTTOM", 0.0))
        bull_mid = (bull_top + bull_bottom) / 2.0 if (bull_top + bull_bottom) > 0 else 0.0
        if current_price > 0 and bull_mid > 0:
            bull_dist = abs(current_price - bull_mid) / current_price * 100.0
        else:
            bull_dist = 0.0

    if bear_active:
        bear_top = float(il.get("BEAR_FVG_TOP", 0.0))
        bear_bottom = float(il.get("BEAR_FVG_BOTTOM", 0.0))
        bear_mid = (bear_top + bear_bottom) / 2.0 if (bear_top + bear_bottom) > 0 else 0.0
        if current_price > 0 and bear_mid > 0:
            bear_dist = abs(current_price - bear_mid) / current_price * 100.0
        else:
            bear_dist = 0.0

    # Pick primary: nearest active FVG
    if bull_active and (not bear_active or bull_dist <= bear_dist):
        side = "BULL"
        mit_pct = float(il.get("BULL_FVG_MITIGATION_PCT", 0.0))
        full_mit = bool(il.get("BULL_FVG_FULL_MITIGATION", False))
        distance = round(bull_dist, 4)
    else:
        side = "BEAR"
        mit_pct = float(il.get("BEAR_FVG_MITIGATION_PCT", 0.0))
        full_mit = bool(il.get("BEAR_FVG_FULL_MITIGATION", False))
        distance = round(bear_dist, 4)

    # FVG maturity: fill-derived proxy (not actual bar age)
    maturity = 0
    if mit_pct >= 0.8:
        maturity = 3  # near-full → expiring
    elif mit_pct >= 0.5:
        maturity = 2  # heavy fill → mature
    elif mit_pct >= 0.2:
        maturity = 1  # moderate fill → aging
    else:
        maturity = 0  # minimal fill → likely fresh

    fresh = maturity <= MATURITY_FRESH_MAX and not full_mit
    invalidated = full_mit

    result["PRIMARY_FVG_SIDE"] = side
    result["PRIMARY_FVG_DISTANCE"] = distance
    result["FVG_FILL_PCT"] = round(mit_pct, 4)
    result["FVG_MATURITY_LEVEL"] = maturity
    result["FVG_FRESH"] = fresh
    result["FVG_INVALIDATED"] = invalidated

    if overrides:
        for k, v in overrides.items():
            if k in result:
                result[k] = v

    return result
