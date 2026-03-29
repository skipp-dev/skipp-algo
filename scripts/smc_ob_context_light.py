"""V5.5 Order Block Context Light adapter.

Derives 5 compact user-facing fields from the broad v5.2 order-blocks
block.  Picks the *primary* (most relevant) OB and surfaces its key
attributes.

Usage::

    from scripts.smc_ob_context_light import build_ob_context_light, DEFAULTS

    light = build_ob_context_light(order_blocks=enrichment.get("order_blocks", {}))
    enrichment["ob_context_light"] = light
"""
from __future__ import annotations

from typing import Any

# ── Defaults ────────────────────────────────────────────────────────

DEFAULTS: dict[str, Any] = {
    "PRIMARY_OB_SIDE": "NONE",            # BULL | BEAR | NONE
    "PRIMARY_OB_DISTANCE": 0.0,           # pct distance from price
    "OB_FRESH": False,
    "OB_AGE_BARS": 0,
    "OB_MITIGATION_STATE": "stale",       # fresh | touched | mitigated | stale
}

FRESHNESS_MAX_BARS = 10


def _mitigation_state(freshness_bars: int, mitigated: bool) -> str:
    """Derive mitigation state from freshness and mitigation flag."""
    if mitigated:
        return "mitigated"
    if freshness_bars <= FRESHNESS_MAX_BARS:
        return "fresh"
    if freshness_bars <= 30:
        return "touched"
    return "stale"


def build_ob_context_light(
    *,
    order_blocks: dict[str, Any] | None = None,
    current_price: float = 0.0,
    overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the v5.5 OB context light surface.

    Selection logic for *primary* OB:
    1. Pick the side with higher freshness (lower bar count = fresher)
    2. Among equal freshness, pick the one closer to price
    3. Prefer unmitigated OBs

    Parameters
    ----------
    order_blocks : dict | None
        Full order-blocks block from :func:`build_order_blocks`.
    current_price : float
        Current price for distance calculation.
    overrides : dict | None
        Manual field overrides.

    Returns
    -------
    dict[str, Any]
        Flat dict with 5 lean fields.
    """
    result = dict(DEFAULTS)
    ob = order_blocks or {}

    bull_freshness = int(ob.get("BULL_OB_FRESHNESS", 0))
    bear_freshness = int(ob.get("BEAR_OB_FRESHNESS", 0))
    bull_mitigated = bool(ob.get("BULL_OB_MITIGATED", False))
    bear_mitigated = bool(ob.get("BEAR_OB_MITIGATED", False))
    bull_level = float(ob.get("NEAREST_BULL_OB_LEVEL", 0.0))
    bear_level = float(ob.get("NEAREST_BEAR_OB_LEVEL", 0.0))

    # No OBs at all
    if bull_freshness == 0 and bear_freshness == 0 and bull_level == 0.0 and bear_level == 0.0:
        if overrides:
            for k, v in overrides.items():
                if k in result:
                    result[k] = v
        return result

    # Calculate distances
    bull_dist = 0.0
    bear_dist = 0.0
    if current_price > 0:
        if bull_level > 0:
            bull_dist = abs(current_price - bull_level) / current_price * 100.0
        if bear_level > 0:
            bear_dist = abs(current_price - bear_level) / current_price * 100.0

    # Pick primary: prefer fresh + unmitigated + close
    bull_score = 0
    bear_score = 0

    if bull_freshness > 0 and not bull_mitigated:
        bull_score = 100 - min(bull_freshness, 100)
    elif bull_freshness > 0:
        bull_score = max(0, 50 - min(bull_freshness, 50))

    if bear_freshness > 0 and not bear_mitigated:
        bear_score = 100 - min(bear_freshness, 100)
    elif bear_freshness > 0:
        bear_score = max(0, 50 - min(bear_freshness, 50))

    if bull_score == 0 and bear_score == 0:
        # Fall back to distance-based if no freshness data
        if bull_level > 0 and (bear_level == 0 or bull_dist <= bear_dist):
            bull_score = 1
        elif bear_level > 0:
            bear_score = 1

    if bull_score >= bear_score and bull_score > 0:
        side = "BULL"
        age = bull_freshness
        mitigated = bull_mitigated
        distance = round(bull_dist, 4)
    elif bear_score > 0:
        side = "BEAR"
        age = bear_freshness
        mitigated = bear_mitigated
        distance = round(bear_dist, 4)
    else:
        if overrides:
            for k, v in overrides.items():
                if k in result:
                    result[k] = v
        return result

    state = _mitigation_state(age, mitigated)
    fresh = age <= FRESHNESS_MAX_BARS and not mitigated

    result["PRIMARY_OB_SIDE"] = side
    result["PRIMARY_OB_DISTANCE"] = distance
    result["OB_FRESH"] = fresh
    result["OB_AGE_BARS"] = age
    result["OB_MITIGATION_STATE"] = state

    if overrides:
        for k, v in overrides.items():
            if k in result:
                result[k] = v

    return result
