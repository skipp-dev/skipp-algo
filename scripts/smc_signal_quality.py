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

from open_prep.feature_flags import (
    any_v2_feature_enabled,
    is_confluence_score_enabled,
    is_freshness_v2_enabled,
    is_reaction_zone_enabled,
    is_smt_divergence_enabled,
    is_sweep_trap_enabled,
    signal_quality_model,
)

logger = logging.getLogger(__name__)

# ── Defaults ────────────────────────────────────────────────────────

DEFAULTS: dict[str, Any] = {
    "SIGNAL_QUALITY_SCORE": 0,
    "SIGNAL_QUALITY_TIER": "low",
    "SIGNAL_WARNINGS": "",
    "SIGNAL_BIAS_ALIGNMENT": "neutral",
    "SIGNAL_FRESHNESS": "stale",
}

# Public model IDs used by downstream modules.
_SQ_MODEL_V1: str = "v1"
_SQ_MODEL_V2: str = "v2"
_SQ_MODEL_V21: str = "v2.1"

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

# Backward-compatible v2 budget aliases used by tests and downstream imports.
_MAX_STRUCTURE_V2 = 18
_MAX_SESSION_V2 = 18
_MAX_LIQUIDITY_V2 = 12
_MAX_OB_V2 = 12
_MAX_FVG_V2 = 12
_MAX_COMPRESSION_V2 = 12
_MAX_CONFLUENCE_V2 = 12
_MAX_SMT_V2 = 4


def _prefer_lean_value(primary: dict[str, Any], fallback: dict[str, Any], key: str, default: Any) -> Any:
    if key in primary:
        return primary[key]
    return fallback.get(key, default)


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


def _freshness_label_v2(
    *,
    structure_fresh: bool,
    structure_age: int,
    fvg_fresh: bool,
    ob_fresh: bool,
    in_killzone: bool,
    has_bull_sweep: bool,
    has_bear_sweep: bool,
    atr_regime: str,
) -> str:
    """Extended freshness label used by the v2 signal-quality model.

    In addition to the v1 inputs (structure, FVG, OB), v2 freshness also
    weighs session killzone presence, recent liquidity sweep activity,
    and the ATR/compression regime.  The five-label scale gives callers
    a finer graduation than v1's ``fresh | aging | stale``.
    """
    fresh_count = sum([structure_fresh, fvg_fresh, ob_fresh])
    has_recent_sweep = has_bull_sweep or has_bear_sweep

    # Very fresh: multiple fresh components and supportive context
    if fresh_count >= 2 and in_killzone and has_recent_sweep:
        return "very_fresh"

    # Fresh: same rule as v1; killzone/sweep are handled above.
    if fresh_count >= 2 or (structure_fresh and structure_age <= 5):
        return "fresh"

    # Aging: at least one fresh component or recent structure
    if fresh_count >= 1 or structure_age <= 15 or (in_killzone and has_recent_sweep):
        return "aging"

    # Stale: nothing fresh but not clearly exhausted
    if atr_regime not in ("EXHAUSTION",):
        return "stale"

    # Expired: stale plus exhaustion regime
    return "expired"


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


def build_signal_quality_v1(
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
    structure_fresh = bool(_prefer_lean_value(ssl, ss, "STRUCTURE_FRESH", False))
    structure_age = int(_prefer_lean_value(ssl, ss, "STRUCTURE_EVENT_AGE_BARS", 999))
    # For bias alignment: prefer lean last_event, fallback to broad state
    last_event = str(_prefer_lean_value(ssl, ss, "STRUCTURE_LAST_EVENT", "NONE"))
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
    in_killzone = bool(_prefer_lean_value(scl, sc, "IN_KILLZONE", False))
    session_bias = str(_prefer_lean_value(scl, sc, "SESSION_DIRECTION_BIAS", "NEUTRAL"))
    session_score_raw = int(_prefer_lean_value(scl, sc, "SESSION_CONTEXT_SCORE", 0))

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
    _ob_mitigation = str(ob_light.get("OB_MITIGATION_STATE", "stale"))

    # Fallback: derive from broad OB block only if lean is absent
    if ob_side == "NONE":
        ob = enr.get("order_blocks") or {}
        if ob:
            bull_dist = float(ob.get("OB_NEAREST_DISTANCE_PCT", 99.0))
            _bear_dist = float(ob.get("OB_NEAREST_DISTANCE_PCT", 99.0))
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
    if "MARKET_EVENT_BLOCKED" in erl or "SYMBOL_EVENT_BLOCKED" in erl:
        event_blocked = bool(erl.get("MARKET_EVENT_BLOCKED", False) or erl.get("SYMBOL_EVENT_BLOCKED", False))
    else:
        event_blocked = bool(er.get("MARKET_EVENT_BLOCKED", False) or er.get("SYMBOL_EVENT_BLOCKED", False))
    event_risk_level = str(_prefer_lean_value(erl, er, "EVENT_RISK_LEVEL", "NONE"))

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


def build_signal_quality(
    *,
    enrichment: dict[str, Any] | None = None,
    overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Route to the active signal-quality implementation.

    ``SIGNAL_QUALITY_MODEL`` (from ``open_prep.feature_flags``) selects
    the implementation: ``"v1"`` (default) calls the frozen production
    scoring in :func:`build_signal_quality_v1`; ``"v2"`` and ``"v2.1"`
    delegate to :func:`build_signal_quality_v2`.

    Additionally, if any v2 feature flag is enabled (see
    :func:`open_prep.feature_flags.any_v2_feature_enabled`), the router
    always delegates to v2 so that individual features can be toggled
    without changing the model setting.
    """
    model = signal_quality_model()
    if model == "v1" and not any_v2_feature_enabled():
        return build_signal_quality_v1(enrichment=enrichment, overrides=overrides)
    return build_signal_quality_v2(enrichment=enrichment, overrides=overrides)



def _derive_confluence_direction(enr: dict[str, Any]) -> str:
    """Derive an overall confluence direction from orthogonal family signals."""
    ob_light = enr.get("ob_context_light") or {}
    fvg_light = enr.get("fvg_lifecycle_light") or {}
    ls = enr.get("liquidity_sweeps") or {}
    ob_side = str(ob_light.get("PRIMARY_OB_SIDE", "NONE")).upper()
    fvg_side = str(fvg_light.get("PRIMARY_FVG_SIDE", "NONE")).upper()
    sweep_dir = str(ls.get("SWEEP_DIRECTION", "NONE")).upper()
    bull = sum([ob_side == "BULL", fvg_side == "BULL", sweep_dir == "BULL"])
    bear = sum([ob_side == "BEAR", fvg_side == "BEAR", sweep_dir == "BEAR"])
    if bull > bear:
        return "bull"
    if bear > bull:
        return "bear"
    return "neutral"

def build_signal_quality_v2(
    *,
    enrichment: dict[str, Any] | None = None,
    overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a v2 signal-quality score.

    Budget (sum = 100):
      structure 18 | session 18 | liquidity 12 | OB 12 | FVG 12 |
      compression 12 | confluence 12 | SMT 6

    Phase A (Freshness v2): optionally uses the extended v2 freshness label.
    Phase B-D: optionally folds sweep-trap, reaction-zone, confluence and
    SMT-divergence detectors into the block.
    """
    result = dict(DEFAULTS)
    enr = enrichment or {}
    warnings: list[str] = []
    score = 0

    # ── Helpers reused from v1 ──────────────────────────────────
    ssl = enr.get("structure_state_light") or {}
    ss = enr.get("structure_state") or {}
    structure_fresh = bool(_prefer_lean_value(ssl, ss, "STRUCTURE_FRESH", False))
    structure_age = int(_prefer_lean_value(ssl, ss, "STRUCTURE_EVENT_AGE_BARS", 999))
    last_event = str(_prefer_lean_value(ssl, ss, "STRUCTURE_LAST_EVENT", "NONE"))
    if last_event in ("BOS_BULL", "CHOCH_BULL"):
        structure_state = "BULLISH"
    elif last_event in ("BOS_BEAR", "CHOCH_BEAR"):
        structure_state = "BEARISH"
    else:
        structure_state = str(ss.get("STRUCTURE_STATE", "NEUTRAL"))

    scl = enr.get("session_context_light") or {}
    sc = enr.get("session_context") or {}
    in_killzone = bool(_prefer_lean_value(scl, sc, "IN_KILLZONE", False))
    session_bias = str(_prefer_lean_value(scl, sc, "SESSION_DIRECTION_BIAS", "NEUTRAL"))
    session_score_raw = int(_prefer_lean_value(scl, sc, "SESSION_CONTEXT_SCORE", 0))

    ob_light = enr.get("ob_context_light") or {}
    ob_side = str(ob_light.get("PRIMARY_OB_SIDE", "NONE"))
    ob_fresh = bool(ob_light.get("OB_FRESH", False))
    ob_distance = float(ob_light.get("PRIMARY_OB_DISTANCE", 99.0))

    fvg_light = enr.get("fvg_lifecycle_light") or {}
    fvg_side = str(fvg_light.get("PRIMARY_FVG_SIDE", "NONE"))
    fvg_fresh = bool(fvg_light.get("FVG_FRESH", False))
    fvg_invalidated = bool(fvg_light.get("FVG_INVALIDATED", False))

    ls = enr.get("liquidity_sweeps") or {}
    has_bull_sweep = bool(ls.get("RECENT_BULL_SWEEP", False))
    has_bear_sweep = bool(ls.get("RECENT_BEAR_SWEEP", False))
    sweep_quality = int(ls.get("SWEEP_QUALITY_SCORE", 0))
    sweep_direction = str(ls.get("SWEEP_DIRECTION", "NONE"))

    cr = enr.get("compression_regime") or {}
    squeeze_on = bool(cr.get("SQUEEZE_ON", False))
    atr_regime = str(cr.get("ATR_REGIME", "NORMAL"))

    erl = enr.get("event_risk_light") or {}
    er = enr.get("event_risk") or {}
    if "MARKET_EVENT_BLOCKED" in erl or "SYMBOL_EVENT_BLOCKED" in erl:
        event_blocked = bool(erl.get("MARKET_EVENT_BLOCKED", False) or erl.get("SYMBOL_EVENT_BLOCKED", False))
    else:
        event_blocked = bool(er.get("MARKET_EVENT_BLOCKED", False) or er.get("SYMBOL_EVENT_BLOCKED", False))
    event_risk_level = str(_prefer_lean_value(erl, er, "EVENT_RISK_LEVEL", "NONE"))

    # ── Structure freshness (0-18) ──────────────────────────────
    if structure_fresh:
        score += _MAX_STRUCTURE_V2
    elif structure_age <= 15:
        score += int(_MAX_STRUCTURE_V2 * 0.6)
    elif structure_age <= 30:
        score += int(_MAX_STRUCTURE_V2 * 0.3)
    else:
        warnings.append("structure_stale")

    # ── Session alignment (0-18) ────────────────────────────────
    if in_killzone and session_score_raw >= 4:
        score += _MAX_SESSION_V2
    elif in_killzone:
        score += int(_MAX_SESSION_V2 * 0.7)
    elif session_score_raw >= 3:
        score += int(_MAX_SESSION_V2 * 0.4)
    else:
        if not in_killzone:
            warnings.append("outside_killzone")

    # ── Liquidity / sweep support (0-12) ──────────────────────────
    if has_bull_sweep or has_bear_sweep:
        sweep_contrib = min(_MAX_LIQUIDITY_V2, int(sweep_quality * _MAX_LIQUIDITY_V2 / 10))
        score += sweep_contrib

    # ── OB support (0-12) ───────────────────────────────────────
    if ob_side != "NONE" and ob_fresh and ob_distance < 2.0:
        score += _MAX_OB_V2
    elif ob_side != "NONE" and ob_distance < 3.0:
        score += int(_MAX_OB_V2 * 0.6)
    elif ob_side != "NONE":
        score += int(_MAX_OB_V2 * 0.3)

    # ── FVG support (0-12) ──────────────────────────────────────
    if fvg_side != "NONE" and fvg_fresh and not fvg_invalidated:
        score += _MAX_FVG_V2
    elif fvg_side != "NONE" and not fvg_invalidated:
        score += int(_MAX_FVG_V2 * 0.5)
    elif fvg_invalidated:
        warnings.append("fvg_invalidated")

    # ── Freshness v2 decay multiplier (Phase A) ─────────────────
    # Apply penalty to dynamic family slots (OB/FVG/Liquidity) only.
    freshness_penalty = float((enr.get("freshness_v2") or {}).get("freshness_penalty", 1.0))
    if freshness_penalty < 1.0:
        # Compute the dynamic-family portion of the current score and discount it.
        current_dynamic = 0
        if ob_side != "NONE" and ob_fresh and ob_distance < 2.0:
            current_dynamic += _MAX_OB_V2
        elif ob_side != "NONE" and ob_distance < 3.0:
            current_dynamic += int(_MAX_OB_V2 * 0.6)
        elif ob_side != "NONE":
            current_dynamic += int(_MAX_OB_V2 * 0.3)
        if fvg_side != "NONE" and fvg_fresh and not fvg_invalidated:
            current_dynamic += _MAX_FVG_V2
        elif fvg_side != "NONE" and not fvg_invalidated:
            current_dynamic += int(_MAX_FVG_V2 * 0.5)
        if has_bull_sweep or has_bear_sweep:
            current_dynamic += min(_MAX_LIQUIDITY_V2, int(sweep_quality * _MAX_LIQUIDITY_V2 / 10))
        score = score - current_dynamic + int(current_dynamic * freshness_penalty)

    # ── Compression regime (0-12) ───────────────────────────────
    if squeeze_on:
        score += int(_MAX_COMPRESSION_V2 * 0.8)
    elif atr_regime in ("COMPRESSION",):
        score += int(_MAX_COMPRESSION_V2 * 0.5)
    elif atr_regime in ("NORMAL",):
        score += int(_MAX_COMPRESSION_V2 * 0.3)
    elif atr_regime in ("EXHAUSTION",):
        warnings.append("atr_exhaustion")

    # ── Event risk penalty (0 to -15) ───────────────────────────
    if event_blocked:
        score += PENALTY_EVENT
        warnings.append("event_blocked")
    elif event_risk_level in ("HIGH", "ELEVATED"):
        score += int(PENALTY_EVENT * 0.6)
        warnings.append("event_risk_high")

    # ── Confluence (0-12) ───────────────────────────────────────
    if is_confluence_score_enabled():
        from smc_core.smc_confluence import compute_confluence

        confluence_result = compute_confluence(ob_light, fvg_light, ls)
        confluence_contribution = int(_MAX_CONFLUENCE_V2 * confluence_result.raw_confluence_score)
        score += confluence_contribution
        result["CONFLUENCE_SCORE"] = confluence_contribution
        result["CONFLUENCE_DIRECTION"] = _derive_confluence_direction(enr)
        result["CONFLUENCE_TIER"] = confluence_result.confluence_tier
        result["CONFLUENCE_OB_CONTRIBUTION"] = confluence_result.ob_contribution
        result["CONFLUENCE_FVG_CONTRIBUTION"] = confluence_result.fvg_contribution
        result["CONFLUENCE_SWEEP_CONTRIBUTION"] = confluence_result.sweep_contribution

    # ── SMT divergence (0-6) ────────────────────────────────────
    if is_smt_divergence_enabled():
        from smc_core.smt_divergence import detect_smt_divergence

        smt_block = detect_smt_divergence(enr)
        result.update(smt_block)
        if smt_block.get("SMT_DIVERGENCE_DETECTED") and smt_block.get("SMT_DIVERGENCE_CONFIDENCE", 0) >= 60:
            score += _MAX_SMT_V2

    # ── Clamp and derive tier ───────────────────────────────────
    score = max(0, min(100, score))
    tier = _score_tier(score)
    freshness = _freshness_label(structure_fresh, structure_age, fvg_fresh, ob_fresh)
    bias = _bias_alignment(structure_state, session_bias, sweep_direction, ob_side, fvg_side)

    # Phase A: optionally apply the extended v2 freshness label.
    if is_freshness_v2_enabled():
        freshness = _freshness_label_v2(
            structure_fresh=structure_fresh,
            structure_age=structure_age,
            fvg_fresh=fvg_fresh,
            ob_fresh=ob_fresh,
            in_killzone=in_killzone,
            has_bull_sweep=has_bull_sweep,
            has_bear_sweep=has_bear_sweep,
            atr_regime=atr_regime,
        )

    result["SIGNAL_QUALITY_SCORE"] = score
    result["SIGNAL_QUALITY_TIER"] = tier
    result["SIGNAL_WARNINGS"] = "|".join(warnings[:3])
    result["SIGNAL_BIAS_ALIGNMENT"] = bias
    result["SIGNAL_FRESHNESS"] = freshness

    # Phase B/C: optionally fold sweep-trap / reaction-zone detectors.
    if is_sweep_trap_enabled():
        from smc_core.sweep_trap import detect_sweep_trap

        result.update(detect_sweep_trap(enr))
    if is_reaction_zone_enabled():
        from smc_core.reaction_zone import detect_reaction_zone

        result.update(detect_reaction_zone(enr))

    # Post-detector freshness adjustment.
    freshness = result.get("SIGNAL_FRESHNESS", "stale")
    downgrade_triggered = False
    if result.get("SWEEP_TRAP_DETECTED") and result.get("SWEEP_TRAP_CONFIDENCE", 0) >= 60:
        downgrade_triggered = True
    if result.get("SMT_DIVERGENCE_DETECTED") and result.get("SMT_DIVERGENCE_CONFIDENCE", 0) >= 60:
        downgrade_triggered = True
    if downgrade_triggered and freshness not in ("stale", "expired"):
        downgrades = {"very_fresh": "fresh", "fresh": "aging", "aging": "stale"}
        result["SIGNAL_FRESHNESS"] = downgrades.get(freshness, "stale")

    # Re-apply overrides last so manual values win.
    if overrides:
        for key, value in overrides.items():
            if key in result:
                result[key] = value

    return result
