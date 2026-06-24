"""SMC v2 Reaction Zone detector (Phase C scaffolding, 2026-06-24).

A reaction zone is a price region where the market is likely to react
to a recent structural event (BOS/CHOCH) or liquidity sweep.  The detector
combines proximity of fresh order blocks / FVGs, recent sweep activity,
and session bias alignment.  It is gated by ``ENABLE_REACTION_ZONE`` and
safe-defaults to neutral when the flag is OFF or inputs are unavailable.
"""
from __future__ import annotations

from typing import Any

from smc_core.v2_features import reaction_zone_enabled


def detect_reaction_zone(enrichment: dict[str, Any] | None = None) -> dict[str, Any]:
    """Detect a reaction zone from enrichment data.

    Parameters
    ----------
    enrichment : dict | None
        Full enrichment dict.  Reads ``structure_state_light``,
        ``ob_context_light``, ``fvg_lifecycle_light``, ``liquidity_sweeps``,
        and ``session_context_light``.

    Returns
    -------
    dict[str, Any]
        ``{"REACTION_ZONE_DETECTED": bool, "REACTION_ZONE_CONFIDENCE": int,
        "REACTION_ZONE_DIRECTION": str}``.  Direction is ``"bull"``,
        ``"bear"`` or ``"neutral"``.  When the feature flag is OFF the
        detector returns the neutral block.
    """
    neutral = {
        "REACTION_ZONE_DETECTED": False,
        "REACTION_ZONE_CONFIDENCE": 0,
        "REACTION_ZONE_DIRECTION": "neutral",
    }

    if not reaction_zone_enabled():
        return neutral

    enr = enrichment or {}

    ssl = enr.get("structure_state_light") or {}
    last_event = str(ssl.get("STRUCTURE_LAST_EVENT", "NONE"))
    structure_fresh = bool(ssl.get("STRUCTURE_FRESH", False))

    ob_light = enr.get("ob_context_light") or {}
    ob_fresh = bool(ob_light.get("OB_FRESH", False))
    ob_distance = float(ob_light.get("PRIMARY_OB_DISTANCE", 99.0))
    ob_side = str(ob_light.get("PRIMARY_OB_SIDE", "NONE"))

    fvg_light = enr.get("fvg_lifecycle_light") or {}
    fvg_fresh = bool(fvg_light.get("FVG_FRESH", False))
    fvg_distance = float(fvg_light.get("PRIMARY_FVG_DISTANCE", 99.0))
    fvg_side = str(fvg_light.get("PRIMARY_FVG_SIDE", "NONE"))

    ls = enr.get("liquidity_sweeps") or {}
    recent_bull_sweep = ls.get("RECENT_BULL_SWEEP", False)
    recent_bear_sweep = ls.get("RECENT_BEAR_SWEEP", False)
    has_sweep = bool(recent_bull_sweep) or bool(recent_bear_sweep)
    sweep_direction = str(ls.get("SWEEP_DIRECTION", "NONE"))

    scl = enr.get("session_context_light") or {}
    sc = enr.get("session_context") or {}
    session_bias = str(
        _prefer_lean_value(scl, sc, "SESSION_DIRECTION_BIAS", "NEUTRAL")
    ).upper()

    # Need a fresh structural anchor or a recent sweep to form a zone.
    if not (structure_fresh or has_sweep):
        return neutral

    # Need a fresh OB or FVG close to price (< 3 %) to define the zone.
    has_near_support = (ob_fresh and ob_distance < 3.0) or (fvg_fresh and fvg_distance < 3.0)
    if not has_near_support:
        return neutral

    # Determine direction from the strongest nearby signal.
    direction = "neutral"
    if ob_side in ("BULL", "BEAR"):
        direction = ob_side.lower()
    elif fvg_side in ("BULL", "BEAR"):
        direction = fvg_side.lower()
    elif sweep_direction in ("BULL", "BEAR"):
        direction = sweep_direction.lower()
    elif last_event in ("BOS_BULL", "CHOCH_BULL"):
        direction = "bull"
    elif last_event in ("BOS_BEAR", "CHOCH_BEAR"):
        direction = "bear"

    # Confidence increases when session bias agrees with the zone direction.
    bias_aligned = (
        (direction == "bull" and session_bias == "BULLISH")
        or (direction == "bear" and session_bias == "BEARISH")
    )
    confidence = 60 if bias_aligned else 40

    return {
        "REACTION_ZONE_DETECTED": True,
        "REACTION_ZONE_CONFIDENCE": confidence,
        "REACTION_ZONE_DIRECTION": direction,
    }


def _prefer_lean_value(primary: dict[str, Any], fallback: dict[str, Any], key: str, default: Any) -> Any:
    if key in primary:
        return primary[key]
    return fallback.get(key, default)
