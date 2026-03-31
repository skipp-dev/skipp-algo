"""V5.5b Signal Quality builder — lean-first.

Produces a compact, explainable quality assessment.  Primary inputs
come from the 5 lean support families; broad blocks serve as fallback
only when lean data is absent.

Non-lean support inputs (Admission Rule — Design Principle 14):

  A non-lean support block is admitted when it provides scoring data
  that cannot be derived from the 5 lean families, safe-defaults to
  neutral on absence, and does not introduce gating or blocking logic.

  Admitted blocks:
  - liquidity_sweeps  — sweep direction & quality for scoring (0-15 pts)
  - compression_regime — squeeze/ATR for expansion potential (0-15 pts)
  Both safe-default to zero contribution when absent.

  See: docs/v5_5_lean_contract.md § Support Block Inputs
  See: docs/v5_5b_architecture.md § Signal Quality — Support Block Inputs

Score composition (0-100):

- Structure freshness (0-20)  — from Structure State Light
- Session alignment   (0-20)  — from Session Context Light
- Liquidity/sweep support (0-15) — from liquidity_sweeps (support block)
- Primary OB support  (0-15)  — from OB Context Light
- Primary FVG support (0-15)  — from FVG Lifecycle Light
- Event risk penalty  (-15 to 0) — from Event Risk Light
- Compression regime  (0-15)  — squeeze/ATR-based expansion potential

Tier mapping:
- 0-25:  low
- 26-50: ok
- 51-75: good
- 76-100: high

All fields safe-default to neutral when inputs are unavailable.

Usage::

    from scripts.smc_signal_quality import build_signal_quality, DEFAULTS

    sq = build_signal_quality(enrichment=enrichment)
    enrichment["signal_quality"] = sq
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# ── Defaults ────────────────────────────────────────────────────────

DEFAULTS: dict[str, Any] = {
    "SIGNAL_QUALITY_SCORE": 0,
    "SIGNAL_QUALITY_TIER": "low",
    "SIGNAL_WARNINGS": "",
    "SIGNAL_BIAS_ALIGNMENT": "neutral",
    "SIGNAL_FRESHNESS": "stale",
}

# ── Tier boundaries ─────────────────────────────────────────────────

TIER_LOW = 25
TIER_OK = 50
TIER_GOOD = 75

# ── Component weights (max contribution) ────────────────────────────

MAX_STRUCTURE = 20
MAX_SESSION = 20
MAX_LIQUIDITY = 15
MAX_OB = 15
MAX_FVG = 15
MAX_COMPRESSION = 15
PENALTY_EVENT = -15


def _score_tier(score: int) -> str:
    if score <= TIER_LOW:
        return "low"
    if score <= TIER_OK:
        return "ok"
    if score <= TIER_GOOD:
        return "good"
    return "high"


def _freshness_label(structure_fresh: bool, structure_age: int, fvg_fresh: bool, ob_fresh: bool) -> str:
    """Determine overall signal freshness from component freshness."""
    fresh_count = sum([structure_fresh, fvg_fresh, ob_fresh])
    if fresh_count >= 2 or (structure_fresh and structure_age <= 5):
        return "fresh"
    if fresh_count >= 1 or structure_age <= 15:
        return "aging"
    return "stale"


def _bias_alignment(
    structure_state: str,
    session_bias: str,
    sweep_direction: str,
    ob_side: str,
    fvg_side: str,
) -> str:
    """Determine consensus bias from multiple directional signals."""
    bull_votes = 0
    bear_votes = 0

    # Structure state
    if structure_state in ("BULLISH",):
        bull_votes += 2
    elif structure_state in ("BEARISH",):
        bear_votes += 2

    # Session bias
    if session_bias in ("BULLISH",):
        bull_votes += 1
    elif session_bias in ("BEARISH",):
        bear_votes += 1

    # Sweep direction
    if sweep_direction in ("BULL", "BUY_SIDE"):
        bull_votes += 1
    elif sweep_direction in ("BEAR", "SELL_SIDE"):
        bear_votes += 1

    # OB side
    if ob_side == "BULL":
        bull_votes += 1
    elif ob_side == "BEAR":
        bear_votes += 1

    # FVG side
    if fvg_side == "BULL":
        bull_votes += 1
    elif fvg_side == "BEAR":
        bear_votes += 1

    total = bull_votes + bear_votes
    if total == 0:
        return "neutral"
    if bull_votes > 0 and bear_votes > 0:
        if bull_votes >= bear_votes * 2:
            return "bull"
        if bear_votes >= bull_votes * 2:
            return "bear"
        return "mixed"
    if bull_votes > 0:
        return "bull"
    return "bear"


def build_signal_quality(
    *,
    enrichment: dict[str, Any] | None = None,
    overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a signal-quality block from existing enrichment data.

    Parameters
    ----------
    enrichment : dict | None
        Full enrichment dict containing structure_state, session_context,
        liquidity_sweeps, order_blocks, imbalance_lifecycle, event_risk, etc.
    overrides : dict | None
        Manual field overrides.

    Returns
    -------
    dict[str, Any]
        Flat dict matching :class:`SignalQualityBlock`.
    """
    result = dict(DEFAULTS)
    enr = enrichment or {}
    warnings: list[str] = []
    score = 0

    # ── Structure freshness (0-20) — lean: structure_state_light ─
    ssl = enr.get("structure_state_light") or {}
    ss = enr.get("structure_state") or {}  # fallback-only
    structure_fresh = bool(ssl.get("STRUCTURE_FRESH") or ss.get("STRUCTURE_FRESH", False))
    structure_age = int(ssl.get("STRUCTURE_EVENT_AGE_BARS") or ss.get("STRUCTURE_EVENT_AGE_BARS", 999))
    # For bias alignment: prefer lean last_event, fallback to broad state
    last_event = str(ssl.get("STRUCTURE_LAST_EVENT", "NONE"))
    if last_event in ("BOS_BULL", "CHOCH_BULL"):
        structure_state = "BULLISH"
    elif last_event in ("BOS_BEAR", "CHOCH_BEAR"):
        structure_state = "BEARISH"
    else:
        structure_state = str(ss.get("STRUCTURE_STATE", "NEUTRAL"))

    if structure_fresh:
        score += MAX_STRUCTURE
    elif structure_age <= 15:
        score += int(MAX_STRUCTURE * 0.6)
    elif structure_age <= 30:
        score += int(MAX_STRUCTURE * 0.3)
    else:
        warnings.append("structure_stale")

    # ── Session alignment (0-20) — lean: session_context_light ──
    scl = enr.get("session_context_light") or {}
    sc = enr.get("session_context") or {}  # fallback-only
    in_killzone = bool(scl.get("SESSION_LIGHT_IN_KILLZONE") or scl.get("IN_KILLZONE") or sc.get("IN_KILLZONE", False))
    session_bias = str(scl.get("SESSION_LIGHT_DIRECTION_BIAS") or scl.get("SESSION_DIRECTION_BIAS") or sc.get("SESSION_DIRECTION_BIAS", "NEUTRAL"))
    session_score_raw = int(scl.get("SESSION_LIGHT_CONTEXT_SCORE") or scl.get("SESSION_CONTEXT_SCORE") or sc.get("SESSION_CONTEXT_SCORE", 0))

    if in_killzone and session_score_raw >= 4:
        score += MAX_SESSION
    elif in_killzone:
        score += int(MAX_SESSION * 0.7)
    elif session_score_raw >= 3:
        score += int(MAX_SESSION * 0.4)
    else:
        if not in_killzone:
            warnings.append("outside_killzone")

    # ── Liquidity / sweep support (0-15) ────────────────────────
    ls = enr.get("liquidity_sweeps") or {}
    has_bull_sweep = bool(ls.get("RECENT_BULL_SWEEP", False))
    has_bear_sweep = bool(ls.get("RECENT_BEAR_SWEEP", False))
    sweep_quality = int(ls.get("SWEEP_QUALITY_SCORE", 0))
    sweep_direction = str(ls.get("SWEEP_DIRECTION", "NONE"))

    if has_bull_sweep or has_bear_sweep:
        sweep_contrib = min(MAX_LIQUIDITY, int(sweep_quality * MAX_LIQUIDITY / 10))
        score += sweep_contrib
    # No warning for missing sweep — it's optional support

    # ── OB support (0-15) — lean: ob_context_light ────────────────
    ob_light = enr.get("ob_context_light") or {}
    ob_side = str(ob_light.get("PRIMARY_OB_SIDE", "NONE"))
    ob_fresh = bool(ob_light.get("OB_FRESH", False))
    ob_distance = float(ob_light.get("PRIMARY_OB_DISTANCE", 99.0))
    ob_mitigation = str(ob_light.get("OB_MITIGATION_STATE", "stale"))

    # Fallback: derive from broad OB block only if lean is absent
    if ob_side == "NONE":
        ob = enr.get("order_blocks") or {}
        if ob:
            bull_dist = float(ob.get("OB_NEAREST_DISTANCE_PCT", 99.0))
            bear_dist = float(ob.get("OB_NEAREST_DISTANCE_PCT", 99.0))
            bull_fresh = int(ob.get("BULL_OB_FRESHNESS", 0))
            bear_fresh = int(ob.get("BEAR_OB_FRESHNESS", 0))
            if bull_fresh > bear_fresh:
                ob_side = "BULL"
                ob_fresh = bull_fresh <= 10
            elif bear_fresh > 0:
                ob_side = "BEAR"
                ob_fresh = bear_fresh <= 10
            ob_distance = bull_dist

    if ob_side != "NONE" and ob_fresh and ob_distance < 2.0:
        score += MAX_OB
    elif ob_side != "NONE" and ob_distance < 3.0:
        score += int(MAX_OB * 0.6)
    elif ob_side != "NONE":
        score += int(MAX_OB * 0.3)

    # ── FVG support (0-15) — lean: fvg_lifecycle_light ────────────
    fvg_light = enr.get("fvg_lifecycle_light") or {}
    fvg_side = str(fvg_light.get("PRIMARY_FVG_SIDE", "NONE"))
    fvg_fresh = bool(fvg_light.get("FVG_FRESH", False))
    fvg_fill = float(fvg_light.get("FVG_FILL_PCT", 0.0))
    fvg_invalidated = bool(fvg_light.get("FVG_INVALIDATED", False))

    # Fallback: derive from broad imbalance block only if lean is absent
    if fvg_side == "NONE":
        il = enr.get("imbalance_lifecycle") or {}
        if il:
            if il.get("BULL_FVG_ACTIVE"):
                fvg_side = "BULL"
                fvg_fill = float(il.get("BULL_FVG_MITIGATION_PCT", 0.0))
                fvg_fresh = fvg_fill < 0.3
                fvg_invalidated = bool(il.get("BULL_FVG_FULL_MITIGATION", False))
            elif il.get("BEAR_FVG_ACTIVE"):
                fvg_side = "BEAR"
                fvg_fill = float(il.get("BEAR_FVG_MITIGATION_PCT", 0.0))
                fvg_fresh = fvg_fill < 0.3
                fvg_invalidated = bool(il.get("BEAR_FVG_FULL_MITIGATION", False))

    if fvg_side != "NONE" and fvg_fresh and not fvg_invalidated:
        score += MAX_FVG
    elif fvg_side != "NONE" and not fvg_invalidated:
        score += int(MAX_FVG * 0.5)
    elif fvg_invalidated:
        warnings.append("fvg_invalidated")

    # ── Event risk penalty (0 to -15) — lean: event_risk_light ──
    erl = enr.get("event_risk_light") or {}
    er = enr.get("event_risk") or {}  # fallback-only
    event_blocked = bool(erl.get("MARKET_EVENT_BLOCKED") or erl.get("SYMBOL_EVENT_BLOCKED") or er.get("MARKET_EVENT_BLOCKED", False) or er.get("SYMBOL_EVENT_BLOCKED", False))
    event_risk_level = str(erl.get("EVENT_RISK_LEVEL") or er.get("EVENT_RISK_LEVEL", "NONE"))

    if event_blocked:
        score += PENALTY_EVENT
        warnings.append("event_blocked")
    elif event_risk_level in ("HIGH", "ELEVATED"):
        score += int(PENALTY_EVENT * 0.6)
        warnings.append("event_risk_high")

    # ── Compression regime (0-15) ───────────────────────────────
    # Scores expansion potential from squeeze/ATR data (not price headroom)
    cr = enr.get("compression_regime") or {}
    squeeze_on = bool(cr.get("SQUEEZE_ON", False))
    atr_regime = str(cr.get("ATR_REGIME", "NORMAL"))

    if squeeze_on:
        score += int(MAX_COMPRESSION * 0.8)  # squeeze = good expansion potential
    elif atr_regime in ("COMPRESSION",):
        score += int(MAX_COMPRESSION * 0.5)
    elif atr_regime in ("NORMAL",):
        score += int(MAX_COMPRESSION * 0.3)
    elif atr_regime in ("EXHAUSTION",):
        warnings.append("atr_exhaustion")

    # ── Clamp and derive tier ───────────────────────────────────
    score = max(0, min(100, score))
    tier = _score_tier(score)
    freshness = _freshness_label(structure_fresh, structure_age, fvg_fresh, ob_fresh)
    bias = _bias_alignment(structure_state, session_bias, sweep_direction, ob_side, fvg_side)

    # Limit warnings to 3
    warning_str = "|".join(warnings[:3])

    result["SIGNAL_QUALITY_SCORE"] = score
    result["SIGNAL_QUALITY_TIER"] = tier
    result["SIGNAL_WARNINGS"] = warning_str
    result["SIGNAL_BIAS_ALIGNMENT"] = bias
    result["SIGNAL_FRESHNESS"] = freshness

    # Apply overrides last
    if overrides:
        for key, value in overrides.items():
            if key in result:
                result[key] = value

    return result
