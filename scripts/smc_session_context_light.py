"""V5.5 Session Context Light adapter.

Passes through 4 existing fields and derives SESSION_VOLATILITY_STATE.

Usage::

    from scripts.smc_session_context_light import build_session_context_light, DEFAULTS

    light = build_session_context_light(
        session_context=enrichment.get("session_context", {}),
        compression_regime=enrichment.get("compression_regime", {}),
    )
    enrichment["session_context_light"] = light
"""
from __future__ import annotations

from typing import Any

# ── Defaults ────────────────────────────────────────────────────────

DEFAULTS: dict[str, Any] = {
    "SESSION_CONTEXT": "NONE",
    "IN_KILLZONE": False,
    "SESSION_DIRECTION_BIAS": "NEUTRAL",
    "SESSION_CONTEXT_SCORE": 0,
    "SESSION_VOLATILITY_STATE": "NORMAL",
}


def build_session_context_light(
    *,
    session_context: dict[str, Any] | None = None,
    compression_regime: dict[str, Any] | None = None,
    overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the v5.5 session context light surface.

    Parameters
    ----------
    session_context : dict | None
        Full session-context block.
    compression_regime : dict | None
        ATR/compression regime for volatility derivation.
    overrides : dict | None
        Manual field overrides.

    Returns
    -------
    dict[str, Any]
        Flat dict with 5 lean fields.
    """
    result = dict(DEFAULTS)
    sc = session_context or {}
    cr = compression_regime or {}

    # Pass-through
    result["SESSION_CONTEXT"] = str(sc.get("SESSION_CONTEXT", "NONE"))
    result["IN_KILLZONE"] = bool(sc.get("IN_KILLZONE", False))
    result["SESSION_DIRECTION_BIAS"] = str(sc.get("SESSION_DIRECTION_BIAS", "NEUTRAL"))
    result["SESSION_CONTEXT_SCORE"] = int(sc.get("SESSION_CONTEXT_SCORE", 0))

    # Derive volatility state from ATR regime
    atr_regime = str(cr.get("ATR_REGIME", "NORMAL"))
    atr_ratio = float(cr.get("ATR_RATIO", 1.0))
    squeeze_on = bool(cr.get("SQUEEZE_ON", False))

    if squeeze_on or atr_regime == "COMPRESSION":
        vol_state = "LOW"
    elif atr_regime == "EXPANSION" and atr_ratio >= 2.0:
        vol_state = "EXTREME"
    elif atr_regime == "EXPANSION" or atr_regime == "EXHAUSTION":
        vol_state = "HIGH"
    else:
        vol_state = "NORMAL"

    result["SESSION_VOLATILITY_STATE"] = vol_state

    if overrides:
        for k, v in overrides.items():
            if k in result:
                result[k] = v

    return result
