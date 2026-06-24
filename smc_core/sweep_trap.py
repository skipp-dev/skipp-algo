"""SMC v2 Sweep Trap detector (Phase B scaffolding, 2026-06-24).

A sweep trap is identified when a recent liquidity sweep is present but
no corresponding reversal has occurred and the sweep quality is poor.
The detector is gated by ``ENABLE_SWEEP_TRAP`` and safe-defaults to a
neutral result when the flag is OFF or inputs are unavailable.
"""
from __future__ import annotations

from typing import Any

from smc_core.v2_features import sweep_trap_enabled


def detect_sweep_trap(enrichment: dict[str, Any] | None = None) -> dict[str, Any]:
    """Detect a sweep-trap condition from enrichment data.

    Parameters
    ----------
    enrichment : dict | None
        Full enrichment dict.  Reads ``liquidity_sweeps`` and optional
        ``structure_state_light`` / ``session_context_light`` blocks.

    Returns
    -------
    dict[str, Any]
        ``{"SWEEP_TRAP_DETECTED": bool, "SWEEP_TRAP_CONFIDENCE": int}``
        Confidence ranges from 0–100.  When the feature flag is OFF the
        detector always returns the neutral block
        ``{"SWEEP_TRAP_DETECTED": False, "SWEEP_TRAP_CONFIDENCE": 0}``.
    """
    neutral = {"SWEEP_TRAP_DETECTED": False, "SWEEP_TRAP_CONFIDENCE": 0}

    if not sweep_trap_enabled():
        return neutral

    enr = enrichment or {}
    ls = enr.get("liquidity_sweeps") or {}

    has_bull_sweep = bool(ls.get("RECENT_BULL_SWEEP", False))
    has_bear_sweep = bool(ls.get("RECENT_BEAR_SWEEP", False))
    sweep_quality = int(ls.get("SWEEP_QUALITY_SCORE", 0))
    sweep_direction = str(ls.get("SWEEP_DIRECTION", "NONE"))

    if not (has_bull_sweep or has_bear_sweep) or sweep_direction == "NONE":
        return neutral

    # A trap is identified only when sweep quality is poor (< 4 out of 10).
    if sweep_quality >= 4:
        return neutral

    # Confidence increases as quality decreases: score 3 -> 70, 2 -> 80, etc.
    quality_factor = max(0, min(100, (10 - sweep_quality) * 10))

    return {
        "SWEEP_TRAP_DETECTED": True,
        "SWEEP_TRAP_CONFIDENCE": quality_factor,
    }
