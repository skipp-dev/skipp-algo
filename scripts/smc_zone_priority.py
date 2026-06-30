"""C9: AI-driven zone priority ranking pipeline.

Computes a composite zone priority ranking from three dimensions:
    1. Historical performance (event family hit rates from benchmark/scoring data)
    2. Current context (market regime, session, vol regime, ensemble quality)
    3. News catalyst (news heat, sentiment, event risk)

The output flows into the generated library as ``export const`` fields,
consumed by SMC_Dashboard.pine and SMC_Core_Engine.pine to surface
"which zone has the highest probability today" to the user.

Usage::

    from scripts.smc_zone_priority import build_zone_priority, DEFAULTS

    priority = build_zone_priority(
        regime="RISK_ON",
        ensemble_score=0.72,
        news_heat=0.35,
        event_risk_level="LOW",
        session_context="RTH",
        vol_regime="NORMAL",
        zone_proj_score=3,
        htf_aligned=True,
    )
    enrichment["zone_priority"] = priority
"""
from __future__ import annotations

from typing import Any

# ── Defaults ────────────────────────────────────────────────────

DEFAULTS: dict[str, Any] = {
    "ZONE_PRIORITY_RANK": "C",          # A (best) / B / C / D (worst)
    "ZONE_PRIORITY_SCORE": 0,           # 0–100 composite score
    "ZONE_PRIORITY_TOP_FAMILY": "OB",   # OB / FVG / BOS / SWEEP
    "ZONE_PRIORITY_CATALYST": "NONE",   # NEWS / EVENT / REGIME / NONE
    "ZONE_PRIORITY_REASON": "",         # human-readable explanation
}

# ── Regime scoring weights ──────────────────────────────────────

_REGIME_SCORES: dict[str, float] = {
    "RISK_ON": 0.85,
    "NEUTRAL": 0.55,
    "ROTATION": 0.35,
    "RISK_OFF": 0.20,
}

_VOL_REGIME_SCORES: dict[str, float] = {
    "LOW_VOL": 0.60,
    "NORMAL": 0.75,
    "HIGH_VOL": 0.40,
    "EXTREME": 0.15,
}

_SESSION_SCORES: dict[str, float] = {
    "RTH": 0.80,
    "ETH": 0.50,
    "PRE_MARKET": 0.45,
    "AFTER_HOURS": 0.35,
    "OVERNIGHT": 0.30,
}

_EVENT_RISK_PENALTIES: dict[str, float] = {
    "NONE": 0.0,
    "LOW": 0.05,
    "MEDIUM": 0.15,
    "HIGH": 0.30,
    "CRITICAL": 0.50,
}

# ── Family priority (historical long-dip hit rates) ────────────

_FAMILY_BASE_PRIORITY: dict[str, float] = {
    "OB": 0.82,       # Order Blocks: highest historical hit rate for long-dips
    "FVG": 0.61,      # FVG: strong fill rate, good for entries
    "BOS": 0.81,      # BOS: directional confirmation
    "SWEEP": 0.73,    # Sweep reversals: empirically higher than initial estimate
}


def _clamp(val: float, lo: float = 0.0, hi: float = 1.0) -> float:
    # NaN is "no signal", not a high score: clamp it to ``lo`` instead of
    # letting ``max(lo, min(hi, nan))`` silently return ``hi`` (NaN compares
    # False to everything, so ``min(hi, nan)`` returns ``hi``). Without this a
    # NaN ensemble_score/news_heat would inflate the zone-priority score to its
    # maximum. ``inf``/``-inf`` already clamp correctly via max/min.
    f = float(val)
    if f != f:  # NaN
        return lo
    return max(lo, min(hi, f))


def _safe_float(val: Any, default: float = 0.0) -> float:
    if val is None:
        return default
    try:
        f = float(val)
        return f if f == f else default  # NaN check
    except (TypeError, ValueError):
        return default


def _rank_from_score(score: int) -> str:
    """Map 0–100 score to letter rank."""
    if score >= 75:
        return "A"
    if score >= 50:
        return "B"
    if score >= 25:
        return "C"
    return "D"


# ── F3: vol-regime / context bump combination mode ─────────────
#
# ``additive`` is the historical formula (production default).  In
# ``multiplicative`` mode every per-context bump ``b`` is applied as
# ``score *= (1 + b)`` instead of ``score += b``.  The two are equivalent
# for a single bump only when the base score is exactly 1.0; with the
# real ``_FAMILY_BASE_PRIORITY`` (0.61–0.82) multiplicative scaling
# preserves the ordering of bumps but amplifies the spread between
# strongly-favored and disfavored families, which is what the F3
# experiment in ``smc_improvement_plan_q3_q4_2026-04-20.md`` (line 397)
# asks us to A/B against the additive baseline.
#
# Default is ``additive`` so this commit is a no-op for production.  The
# rolling benchmark and zone-priority calibration scripts can flip the
# mode via the ``family_score_combination`` keyword (or the
# ``SMC_FAMILY_SCORE_COMBINATION`` env var) to run a shadow arm without
# touching any production config.
FAMILY_SCORE_COMBINATION_ADDITIVE = "additive"
FAMILY_SCORE_COMBINATION_MULTIPLICATIVE = "multiplicative"
_VALID_FAMILY_SCORE_COMBINATIONS = (
    FAMILY_SCORE_COMBINATION_ADDITIVE,
    FAMILY_SCORE_COMBINATION_MULTIPLICATIVE,
)
DEFAULT_FAMILY_SCORE_COMBINATION = FAMILY_SCORE_COMBINATION_ADDITIVE


def _resolve_family_score_combination(explicit: str | None) -> str:
    """Resolve the score-combination mode with env-var fallback.

    Precedence: explicit kwarg > ``SMC_FAMILY_SCORE_COMBINATION`` env >
    ``DEFAULT_FAMILY_SCORE_COMBINATION``.  Unknown values fall back to
    the default rather than raising, so a typo in CI never bricks the
    production scoring path.
    """
    import os
    candidate = (explicit or os.environ.get("SMC_FAMILY_SCORE_COMBINATION") or "").strip().lower()
    if candidate in _VALID_FAMILY_SCORE_COMBINATIONS:
        return candidate
    return DEFAULT_FAMILY_SCORE_COMBINATION


def _apply_bump(scores: dict[str, float], family: str, bump: float, mode: str) -> None:
    """Apply ``bump`` to ``scores[family]`` under the chosen combination mode."""
    if mode == FAMILY_SCORE_COMBINATION_MULTIPLICATIVE:
        scores[family] *= (1.0 + bump)
    else:  # additive (default)
        scores[family] += bump


def _select_top_family(
    *,
    regime: str,
    vol_regime: str,
    htf_aligned: bool,
    calibrated_family_weights: dict[str, float] | None = None,
    session_context: str | None = None,
    family_score_combination: str | None = None,
) -> str:
    """Select the most favorable event family given current context.

    ``session_context`` is one of ``"RTH"``, ``"ETH"``, ``"PRE_MARKET"``,
    ``"AFTER_HOURS"`` or *None* (unknown / no session data).

    ``family_score_combination`` is ``"additive"`` (default, production)
    or ``"multiplicative"`` (F3 experiment arm).  See module docstring
    on :data:`DEFAULT_FAMILY_SCORE_COMBINATION` for resolution rules.
    """
    mode = _resolve_family_score_combination(family_score_combination)
    # Overlay any (possibly partial) calibrated weights onto the full
    # hand-tuned base so every canonical family is always present.  A
    # calibration artifact that drops a family (older schema, truncated or
    # hand-edited JSON) must fall back to its prior, not raise KeyError when
    # a context bump targets the missing family (e.g. BOS on RISK_ON+HTF or
    # SWEEP on EXTREME vol).
    scores = {**_FAMILY_BASE_PRIORITY, **(calibrated_family_weights or {})}

    # OB favored in normal / low-vol regimes with HTF alignment
    if htf_aligned:
        _apply_bump(scores, "OB", 0.10, mode)
    if vol_regime in ("NORMAL", "LOW_VOL"):
        _apply_bump(scores, "OB", 0.05, mode)
    if regime == "RISK_ON":
        _apply_bump(scores, "OB", 0.05, mode)

    # FVG favored in trending / higher-vol regimes
    if vol_regime == "HIGH_VOL":
        _apply_bump(scores, "FVG", 0.08, mode)
    if regime in ("RISK_ON", "NEUTRAL"):
        _apply_bump(scores, "FVG", 0.03, mode)

    # R4: Session-dependent FVG adjustments (from FVG label audit data)
    # FVG performs poorly during extended/after-hours sessions (thin liquidity
    # leads to false invalidations).  Boost during RTH where fills are more
    # reliable.
    if session_context in ("ETH", "AFTER_HOURS", "PRE_MARKET"):
        _apply_bump(scores, "FVG", -0.10, mode)
    elif session_context == "RTH":
        _apply_bump(scores, "FVG", 0.05, mode)

    # BOS favored during strong trend confirmation
    if htf_aligned and regime == "RISK_ON":
        _apply_bump(scores, "BOS", 0.12, mode)

    # SWEEP favored in extreme vol for mean-reversion
    if vol_regime == "EXTREME":
        _apply_bump(scores, "SWEEP", 0.15, mode)

    return max(scores, key=lambda k: scores[k])


def _identify_catalyst(
    *,
    news_heat: float,
    event_risk_level: str,
    regime: str,
) -> str:
    """Identify the primary catalyst driving zone priority."""
    if news_heat >= 0.3:
        return "NEWS"
    if event_risk_level in ("HIGH", "CRITICAL"):
        return "EVENT"
    if regime in ("RISK_ON", "RISK_OFF"):
        return "REGIME"
    return "NONE"


def _build_reason(
    *,
    rank: str,
    top_family: str,
    catalyst: str,
    regime: str,
    ensemble_score: float,
    news_heat: float,
) -> str:
    """Build a concise human-readable reason string."""
    parts: list[str] = []

    if rank in ("A", "B"):
        parts.append(f"{top_family} zones favored")
    else:
        parts.append(f"{top_family} zones neutral")

    if catalyst == "NEWS":
        parts.append(f"news catalyst active ({news_heat:.0%})")
    elif catalyst == "EVENT":
        parts.append("event risk caution")
    elif catalyst == "REGIME":
        regime_label = regime.replace("_", " ").title()
        parts.append(f"regime: {regime_label}")

    if ensemble_score >= 0.7:
        parts.append("high confidence")
    elif ensemble_score < 0.3:
        parts.append("low confidence")

    return "; ".join(parts)


def build_zone_priority(
    *,
    regime: str = "NEUTRAL",
    ensemble_score: float = 0.0,
    news_heat: float = 0.0,
    event_risk_level: str = "NONE",
    session_context: str = "",
    vol_regime: str = "NORMAL",
    zone_proj_score: int = 0,
    htf_aligned: bool = False,
    overrides: dict[str, Any] | None = None,
    calibrated_family_weights: dict[str, float] | None = None,
    contextual_calibration: Any | None = None,
    session_calibration: dict[str, dict[str, float]] | None = None,
) -> dict[str, Any]:
    """Build a zone priority block from current context signals.

    Parameters
    ----------
    regime : str
        Market regime (RISK_ON / RISK_OFF / ROTATION / NEUTRAL).
    ensemble_score : float
        Ensemble quality score (0.0–1.0) from ensemble_quality enrichment.
    news_heat : float
        Global news heat (0.0–1.0) from news enrichment.
    event_risk_level : str
        Event risk level (NONE / LOW / MEDIUM / HIGH / CRITICAL).
    session_context : str
        Current session (RTH / ETH / PRE_MARKET / AFTER_HOURS / OVERNIGHT).
    vol_regime : str
        Volatility regime label (LOW_VOL / NORMAL / HIGH_VOL / EXTREME).
    zone_proj_score : int
        Zone projection score (0–5) from zone_projection enrichment.
    htf_aligned : bool
        Whether the zone is aligned with HTF trend.
    overrides : dict, optional
        Manual overrides — flat merge, last wins.
    calibrated_family_weights : dict, optional
        Calibrated family base-priority weights from
        :func:`smc_zone_priority_calibration.calibrate_from_benchmark`.
        When provided, replaces the hand-tuned ``_FAMILY_BASE_PRIORITY``.
    contextual_calibration : ContextualCalibrationResult, optional
        Phase F contextual calibration.  When provided, family weights are
        resolved per session/vol_regime context using
        :func:`resolve_contextual_weight`, overriding both global calibration
        and hand-tuned defaults.  Falls back to ``calibrated_family_weights``
        when no promoted bucket matches.
    session_calibration : dict, optional
        Phase F2 ergonomic shortcut: ``{session_label: {family: weight}}``
        mapping that injects session-bucket weights without requiring a full
        ``ContextualCalibrationResult``.  Wins over ``contextual_calibration``
        and ``calibrated_family_weights`` only when ``session_context``
        resolves to a key in the dict; otherwise the existing precedence
        (contextual → global → hand-tuned) applies.
    """
    result = dict(DEFAULTS)

    # ── Phase F: Resolve context-aware family weights ───────────
    effective_weights = calibrated_family_weights
    if contextual_calibration is not None:
        from scripts.smc_zone_priority_calibration import resolve_contextual_weight

        ctx_weights: dict[str, float] = {}
        for fam in ("OB", "FVG", "BOS", "SWEEP"):
            ctx_weights[fam] = resolve_contextual_weight(
                contextual_calibration,
                fam,
                session_context=session_context or None,
                vol_regime=vol_regime or None,
            )
        effective_weights = ctx_weights

    # ── Phase F2: Session-only injection (ergonomic shortcut) ────
    # Only fires when the active session bucket is present in the dict;
    # missing/unknown sessions silently fall back to the precedence
    # established above so callers can pass a partial map.
    if session_calibration and session_context:
        bucket = session_calibration.get(session_context.upper())
        if bucket:
            merged = dict(effective_weights or _FAMILY_BASE_PRIORITY)
            for fam, weight in bucket.items():
                if fam in merged:
                    merged[fam] = float(weight)
            effective_weights = merged

    # ── Dimension 1: Historical performance context ─────────────
    # Ensemble score proxies historical performance (scoring + history components)
    perf_score = _clamp(ensemble_score) * 30.0  # 0–30 points

    # ── Dimension 2: Current context alignment ──────────────────
    regime_factor = _REGIME_SCORES.get(regime.upper(), 0.55)
    vol_factor = _VOL_REGIME_SCORES.get(vol_regime.upper(), 0.55)
    session_factor = _SESSION_SCORES.get(session_context.upper(), 0.55)

    context_score = (
        regime_factor * 15.0       # 0–15 points
        + vol_factor * 10.0        # 0–10 points
        + session_factor * 10.0    # 0–10 points
    )

    # Zone projection bonus (0–5 → 0–10 points)
    proj_bonus = _clamp(zone_proj_score / 5.0) * 10.0

    # HTF alignment bonus
    htf_bonus = 5.0 if htf_aligned else 0.0

    # ── Dimension 3: News catalyst / event risk ─────────────────
    news_boost = _clamp(news_heat) * 10.0        # 0–10 points
    event_penalty = _EVENT_RISK_PENALTIES.get(
        event_risk_level.upper(), 0.0
    ) * 100.0                                     # 0–50 penalty

    # ── Composite score ─────────────────────────────────────────
    raw_score = perf_score + context_score + proj_bonus + htf_bonus + news_boost
    final_score = int(_clamp(raw_score - event_penalty, 0.0, 100.0))

    # ── Derived fields ──────────────────────────────────────────
    rank = _rank_from_score(final_score)
    top_family = _select_top_family(
        regime=regime.upper(),
        vol_regime=vol_regime.upper(),
        htf_aligned=htf_aligned,
        calibrated_family_weights=effective_weights,
        session_context=session_context.upper() if session_context else None,
    )
    catalyst = _identify_catalyst(
        news_heat=news_heat,
        event_risk_level=event_risk_level.upper(),
        regime=regime.upper(),
    )
    reason = _build_reason(
        rank=rank,
        top_family=top_family,
        catalyst=catalyst,
        regime=regime.upper(),
        ensemble_score=ensemble_score,
        news_heat=news_heat,
    )

    result["ZONE_PRIORITY_RANK"] = rank
    result["ZONE_PRIORITY_SCORE"] = final_score
    result["ZONE_PRIORITY_TOP_FAMILY"] = top_family
    result["ZONE_PRIORITY_CATALYST"] = catalyst
    result["ZONE_PRIORITY_REASON"] = reason

    if overrides:
        for key, val in overrides.items():
            if key in DEFAULTS:
                result[key] = val

    return result
