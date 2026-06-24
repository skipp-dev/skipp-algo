"""SMC v2 Confluence Score (Phase D scaffolding, 2026-06-24).

The confluence score measures how many independent SMC signals align
in the same direction at the same time.  It is gated by
``ENABLE_CONFLUENCE_SCORE`` and safe-defaults to a neutral block when
the flag is OFF or inputs are unavailable.
"""
from __future__ import annotations

from typing import Any

from smc_core.v2_features import confluence_score_enabled


def compute_confluence_score(enrichment: dict[str, Any] | None = None) -> dict[str, Any]:
    """Compute a 0–100 confluence score from enrichment data.

    Parameters
    ----------
    enrichment : dict | None
        Full enrichment dict.  Reads ``structure_state_light``,
        ``session_context_light``, ``ob_context_light``,
        ``fvg_lifecycle_light`` and ``liquidity_sweeps``.

    Returns
    -------
    dict[str, Any]
        ``{"CONFLUENCE_SCORE": int, "CONFLUENCE_DIRECTION": str}``.
        Direction is ``"bull"``, ``"bear"`` or ``"neutral"``.  When the
        feature flag is OFF the function returns the neutral block
        ``{"CONFLUENCE_SCORE": 0, "CONFLUENCE_DIRECTION": "neutral"}``.
    """
    neutral = {"CONFLUENCE_SCORE": 0, "CONFLUENCE_DIRECTION": "neutral"}

    if not confluence_score_enabled():
        return neutral

    enr = enrichment or {}

    ssl = enr.get("structure_state_light") or {}
    last_event = str(ssl.get("STRUCTURE_LAST_EVENT", "NONE"))
    structure_bull = last_event in ("BOS_BULL", "CHOCH_BULL")
    structure_bear = last_event in ("BOS_BEAR", "CHOCH_BEAR")

    scl = enr.get("session_context_light") or {}
    sc = enr.get("session_context") or {}
    session_bias = str(
        scl.get("SESSION_DIRECTION_BIAS", sc.get("SESSION_DIRECTION_BIAS", "NEUTRAL"))
    ).upper()

    ob_light = enr.get("ob_context_light") or {}
    ob_side = str(ob_light.get("PRIMARY_OB_SIDE", "NONE")).upper()
    ob_fresh = bool(ob_light.get("OB_FRESH", False))

    fvg_light = enr.get("fvg_lifecycle_light") or {}
    fvg_side = str(fvg_light.get("PRIMARY_FVG_SIDE", "NONE")).upper()
    fvg_fresh = bool(fvg_light.get("FVG_FRESH", False))

    ls = enr.get("liquidity_sweeps") or {}
    sweep_direction = str(ls.get("SWEEP_DIRECTION", "NONE")).upper()

    bull_signals = sum(
        [
            structure_bull,
            session_bias == "BULLISH",
            ob_side == "BULL" and ob_fresh,
            fvg_side == "BULL" and fvg_fresh,
            sweep_direction == "BULL",
        ]
    )
    bear_signals = sum(
        [
            structure_bear,
            session_bias == "BEARISH",
            ob_side == "BEAR" and ob_fresh,
            fvg_side == "BEAR" and fvg_fresh,
            sweep_direction == "BEAR",
        ]
    )

    total = bull_signals + bear_signals
    if total == 0:
        return neutral

    score = min(100, total * 20)
    if bull_signals > bear_signals:
        direction = "bull"
    elif bear_signals > bull_signals:
        direction = "bear"
    else:
        direction = "neutral"
        score = 0

    return {"CONFLUENCE_SCORE": score, "CONFLUENCE_DIRECTION": direction}
