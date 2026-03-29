"""V5.5 Structure State Light adapter.

Derives 4 compact user-facing fields from the broad v5.3 structure-state
block, adding STRUCTURE_TREND_STRENGTH as a new composite.

Usage::

    from scripts.smc_structure_state_light import build_structure_state_light, DEFAULTS

    light = build_structure_state_light(structure_state=enrichment.get("structure_state", {}))
    enrichment["structure_state_light"] = light
"""
from __future__ import annotations

from typing import Any

# ── Defaults ────────────────────────────────────────────────────────

DEFAULTS: dict[str, Any] = {
    "STRUCTURE_LAST_EVENT": "NONE",
    "STRUCTURE_EVENT_AGE_BARS": 0,
    "STRUCTURE_FRESH": False,
    "STRUCTURE_TREND_STRENGTH": 0,
}


def build_structure_state_light(
    *,
    structure_state: dict[str, Any] | None = None,
    overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the v5.5 structure state light surface.

    STRUCTURE_TREND_STRENGTH is a 0-100 composite:
    - Base: structure_state directional strength (BULLISH/BEARISH = 40, NEUTRAL = 0)
    - Freshness bonus: +30 if fresh, +15 if aging
    - BOS bonus: +15 if recent BOS in trend direction
    - Support/Resistance: +15 if both active

    Parameters
    ----------
    structure_state : dict | None
        Full structure-state block.
    overrides : dict | None
        Manual field overrides.

    Returns
    -------
    dict[str, Any]
        Flat dict with 4 lean fields.
    """
    result = dict(DEFAULTS)
    ss = structure_state or {}

    # Pass-through fields
    result["STRUCTURE_LAST_EVENT"] = str(ss.get("STRUCTURE_LAST_EVENT", "NONE"))
    result["STRUCTURE_EVENT_AGE_BARS"] = int(ss.get("STRUCTURE_EVENT_AGE_BARS", 0))
    result["STRUCTURE_FRESH"] = bool(ss.get("STRUCTURE_FRESH", False))

    # Compute trend strength
    strength = 0
    state = str(ss.get("STRUCTURE_STATE", "NEUTRAL"))
    fresh = bool(ss.get("STRUCTURE_FRESH", False))
    age = int(ss.get("STRUCTURE_EVENT_AGE_BARS", 0))
    last_event = str(ss.get("STRUCTURE_LAST_EVENT", "NONE"))
    bos_bull = bool(ss.get("BOS_BULL", False))
    bos_bear = bool(ss.get("BOS_BEAR", False))
    support_active = bool(ss.get("SUPPORT_ACTIVE", False))
    resistance_active = bool(ss.get("RESISTANCE_ACTIVE", False))

    # Directional base (0-40)
    if state in ("BULLISH", "BEARISH"):
        strength += 40
    elif state == "NEUTRAL":
        strength += 10

    # Freshness bonus (0-30)
    if fresh:
        strength += 30
    elif age <= 15:
        strength += 15
    elif age <= 30:
        strength += 5

    # BOS in trend direction (0-15)
    if state == "BULLISH" and bos_bull:
        strength += 15
    elif state == "BEARISH" and bos_bear:
        strength += 15
    elif last_event.startswith("BOS_"):
        strength += 8

    # S/R active (0-15)
    if support_active and resistance_active:
        strength += 15
    elif support_active or resistance_active:
        strength += 8

    result["STRUCTURE_TREND_STRENGTH"] = min(100, max(0, strength))

    if overrides:
        for k, v in overrides.items():
            if k in result:
                result[k] = v

    return result
