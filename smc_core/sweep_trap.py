"""SMC v2 Sweep Trap detector (Phase B hardening, 2026-06-24).

A sweep trap is identified when a recent liquidity sweep is present but
no corresponding reversal has occurred and the sweep quality is poor.
The detector is gated by ``ENABLE_SWEEP_TRAP`` and safe-defaults to a
neutral result when the flag is OFF or inputs are unavailable.

Hardening rules:
- Base confidence scales inversely with sweep quality (0-5 scale).
- Confidence is boosted when only one sweep direction is present.
- Confidence is reduced when the structure shows a reversal event
  opposite to the sweep direction, because the trap has already played
  out.
"""

from __future__ import annotations

from typing import Any

from smc_core.v2_config import sweep_trap_config
from smc_core.v2_features import sweep_trap_enabled


def detect_sweep_trap(enrichment: dict[str, Any] | None = None) -> dict[str, Any]:
    """Detect a sweep-trap condition from enrichment data.

    Parameters
    ----------
    enrichment : dict | None
        Full enrichment dict.  Reads ``liquidity_sweeps`` and optional
        ``structure_state_light`` / ``structure_state`` blocks.

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
    sweep_direction = str(ls.get("SWEEP_DIRECTION", "NONE")).upper()

    if not (has_bull_sweep or has_bear_sweep) or sweep_direction == "NONE":
        return neutral

    # Quality must be poor for a trap.
    if sweep_quality >= sweep_trap_config.quality_threshold:
        return neutral

    # Base confidence: inversely proportional to quality on the 0-5 scale.
    quality_factor = max(0, min(100, (5 - sweep_quality) * 20))

    # Boost when only one direction swept (lopsided liquidity grab).
    both_sides = has_bull_sweep and has_bear_sweep
    direction_boost = 0 if both_sides else sweep_trap_config.lopsided_boost

    # Reduce confidence if structure already reversed against the sweep.
    ssl = enr.get("structure_state_light") or {}
    ss = enr.get("structure_state") or {}
    last_event = str(ssl.get("STRUCTURE_LAST_EVENT", ss.get("STRUCTURE_LAST_EVENT", "NONE"))).upper()

    reversal_penalty = 0
    if sweep_direction == "BULL" and last_event in ("BOS_BEAR", "CHOCH_BEAR"):
        reversal_penalty = sweep_trap_config.reversal_penalty
    elif sweep_direction == "BEAR" and last_event in ("BOS_BULL", "CHOCH_BULL"):
        reversal_penalty = 40

    confidence = max(0, min(100, quality_factor + direction_boost - reversal_penalty))

    # If quality is poor but structure already reversed, the trap is no
    # longer active.
    if confidence == 0:
        return neutral

    return {
        "SWEEP_TRAP_DETECTED": True,
        "SWEEP_TRAP_CONFIDENCE": confidence,
    }
