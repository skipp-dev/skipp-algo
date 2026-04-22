"""Plan §2.1 D4 — FVG quality scoring (scaffold).

Pure, deterministic quality score for Fair Value Gap (FVG) events.
The score is **not yet wired** into the gate logic — per the W1
planning decision, the Pine input for an FVG quality minimum is held
until the Phase E sample expansion (n ≥ 300 FVG events). This module
gives D4 a runnable scorer today so the calibration report can
stratify events by quality tier ahead of that decision.

Design
------

The scoring function takes a dictionary of per-event features and
returns a ``FvgQualityScore`` with:

- ``score`` ∈ [0.0, 1.0] — calibrated via fixed, explicit weights.
- ``tier`` ∈ {``"HIGH"``, ``"MEDIUM"``, ``"LOW"``, ``"INSUFFICIENT"``}.
- ``multiplier`` ∈ [0.5, 1.5] — the conservative deployment mode
  from the plan. A score-only callsite ignores the multiplier; a
  future gate-on-quality callsite uses it as a family-weight
  multiplier instead of a hard cut.

Feature weights (sum = 1.0, pinned for reproducibility):

=================================  =======
feature                             weight
=================================  =======
``gap_size_atr`` (logistic-scaled)    0.30
``htf_aligned`` (bool)                0.25
``distance_to_price_atr`` (inverse)   0.15
``is_full_body`` (bool)               0.10
``hurst`` (persistence, centred)      0.20
=================================  =======

The Hurst exponent in particular comes from Friday et al. 2026 —
persistent regimes (H > 0.5) are cited as a precondition for the
FVG + OB confluence working well. We use a cheap Rescaled-Range
(R/S) approximation suitable for short Pine-sized windows (≥ 16
samples); SciPy is not a dependency of this repo.

Every feature is clamped to a safe range before weighting so a
malformed upstream payload can never drive the score outside
``[0.0, 1.0]``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any


_TIER_THRESHOLDS: tuple[tuple[str, float], ...] = (
    ("HIGH", 0.70),
    ("MEDIUM", 0.50),
    ("LOW", 0.0),
)

# Conservative deployment — the multiplier range the plan lists for
# gate-on-quality wiring. A score of 0.5 (neutral) maps to 1.0; 0.0 →
# 0.5; 1.0 → 1.5. Linear interpolation keeps the mapping auditable.
_MULTIPLIER_MIN = 0.5
_MULTIPLIER_MAX = 1.5


# --- Weight versioning (Q3 D3 promotion, 2026-04-22) -------------------
#
# Two weight regimes coexist so a caller can pick the semantic it
# wants without touching the function body:
#
# * LENIENT_WEIGHTS — the original D4-scaffold weights. Tuned for the
#   "outcome" label (full hit). Higher feature values lift the score.
# * STRICT_V1_NO_HURST_WEIGHTS — promoted from the L2-logreg
#   recalibration on the strict ``partial_50`` label (≥50% partial
#   fill). Re-normalised after dropping ``hurst_50`` (audit §1.5: null
#   signal). Pairs with ``STRICT_V1_NO_HURST_DIRECTIONS`` (all -1
#   except hurst=0) and ``STRICT_V1_NO_HURST_MEANS`` (component-space
#   neutral = 0.5).
#
# Production default flips to STRICT in this commit. Callers that need
# the old behaviour for a back-compat path can pass LENIENT_WEIGHTS +
# LENIENT_DIRECTIONS + LENIENT_MEANS explicitly.

LENIENT_WEIGHTS: dict[str, float] = {
    "gap_size_atr": 0.30,
    "htf_aligned": 0.25,
    "distance_to_price_atr": 0.15,
    "is_full_body": 0.10,
    "hurst_50": 0.20,
}
LENIENT_DIRECTIONS: dict[str, int] = {k: 1 for k in LENIENT_WEIGHTS}
LENIENT_MEANS: dict[str, float] = {k: 0.0 for k in LENIENT_WEIGHTS}

STRICT_V1_NO_HURST_WEIGHTS: dict[str, float] = {
    "gap_size_atr": 0.45,
    "htf_aligned": 0.0735,
    "distance_to_price_atr": 0.45,
    "is_full_body": 0.0515,
    "hurst_50": 0.0,
}
STRICT_V1_NO_HURST_DIRECTIONS: dict[str, int] = {
    "gap_size_atr": -1,
    "htf_aligned": -1,
    "distance_to_price_atr": -1,
    "is_full_body": -1,
    "hurst_50": 0,  # 0 = unused (audit §1.5: hurst is null-signal under strict)
}
STRICT_V1_NO_HURST_MEANS: dict[str, float] = {k: 0.5 for k in STRICT_V1_NO_HURST_WEIGHTS}

WEIGHT_VERSION = "strict_v1_no_hurst"
DEFAULT_WEIGHTS = STRICT_V1_NO_HURST_WEIGHTS
DEFAULT_DIRECTIONS = STRICT_V1_NO_HURST_DIRECTIONS
DEFAULT_MEANS = STRICT_V1_NO_HURST_MEANS

# Component name → feature name map. Components live in [0,1] after
# the per-component transform; the directions/means dicts above are
# keyed by *feature* name, so we need to translate when applying the
# signed formula.
_COMPONENT_TO_FEATURE: dict[str, str] = {
    "gap_size": "gap_size_atr",
    "htf_aligned": "htf_aligned",
    "distance": "distance_to_price_atr",
    "full_body": "is_full_body",
    "hurst": "hurst_50",
}


@dataclass(slots=True, frozen=True)
class FvgQualityScore:
    score: float
    tier: str
    multiplier: float
    components: dict[str, float]


def _clamp(value: float, lo: float, hi: float) -> float:
    if value < lo:
        return lo
    if value > hi:
        return hi
    return value


def _logistic(x: float) -> float:
    # Soft saturation: gap size is rewarded up to ~2 ATR and plateaus.
    # Numerically safe for any finite input.
    try:
        return 1.0 / (1.0 + math.exp(-x))
    except OverflowError:
        return 0.0 if x < 0 else 1.0


def rolling_hurst(closes: list[float]) -> float | None:
    """Rescaled-Range (R/S) Hurst estimate for a short return series.

    Returns ``None`` for samples smaller than 16 or for a flat series
    where the range collapses to zero — both would produce meaningless
    estimates. Deterministic, allocation-free beyond the local
    intermediates so it can be reused inside a per-event loop.
    """
    if len(closes) < 16:
        return None
    # Log returns — avoids the "divide by zero" pitfall when a close
    # happens to equal the previous one by a cent in an illiquid bar.
    returns: list[float] = []
    for i in range(1, len(closes)):
        prev = closes[i - 1]
        curr = closes[i]
        if prev <= 0 or curr <= 0:
            continue
        returns.append(math.log(curr / prev))
    n = len(returns)
    if n < 16:
        return None
    mean = sum(returns) / n
    deviations = [r - mean for r in returns]
    running = 0.0
    cumulative: list[float] = []
    for d in deviations:
        running += d
        cumulative.append(running)
    rng = max(cumulative) - min(cumulative)
    if rng <= 0:
        return None
    variance = sum(d * d for d in deviations) / n
    std = math.sqrt(variance)
    if std <= 0:
        return None
    rs = rng / std
    # H = log(R/S) / log(n) — classical form.
    hurst = math.log(rs) / math.log(n)
    return _clamp(hurst, 0.0, 1.0)


def _component_gap(gap_size_atr: float) -> float:
    # Centre the logistic at 1 ATR so ~1 ATR maps to 0.5, 2 ATR to
    # ~0.73, 0.3 ATR to ~0.32. Matches the Friday-style "meaningful
    # gap" intuition.
    return _logistic(2.0 * (gap_size_atr - 1.0))


def _component_distance(distance_to_price_atr: float) -> float:
    # Closer zones score higher — 0 ATR away → 1.0, 3 ATR → ~0.25.
    return _clamp(1.0 / (1.0 + distance_to_price_atr), 0.0, 1.0)


def _component_hurst(hurst: float | None) -> float:
    # Centred around 0.5 — a persistent series (H > 0.5) scores above
    # neutral, a mean-reverting one below. None → neutral 0.5 so we
    # neither reward nor penalise an unmeasurable sample.
    if hurst is None:
        return 0.5
    # Linear map: 0.5 → 0.5, 0.7 → 0.8, 0.3 → 0.2. Clipped.
    return _clamp(0.5 + 1.5 * (hurst - 0.5), 0.0, 1.0)


def _score_with_directions(
    components: dict[str, float],
    weights: dict[str, float],
    directions: dict[str, int],
    means: dict[str, float],
) -> float:
    """Signed weighted sum honouring per-feature direction.

    Mirrors :func:`scripts.fvg_quality_recalibration._score_with_directions`
    but operates on *components* (already in ``[0, 1]``) instead of
    raw features. Each component is centred at its supplied mean
    before the sign is applied. ``direction == 0`` disables the
    feature entirely (e.g. ``hurst_50`` under ``strict_v1_no_hurst``).

    Score is ``0.5 + Σ w·d·(comp − mean)`` clamped to ``[0, 1]``.
    Means default to ``0.5`` (component midpoint) so a component value
    of ``0.5`` always contributes zero — neutral.
    """
    raw = 0.0
    for comp_key, feature_key in _COMPONENT_TO_FEATURE.items():
        d = directions.get(feature_key, 1)
        if d == 0:
            continue
        w = weights.get(feature_key, 0.0)
        m = means.get(feature_key, 0.5)
        raw += w * d * (components[comp_key] - m)
    return _clamp(0.5 + raw, 0.0, 1.0)


def score_fvg(
    event: dict[str, Any],
    *,
    weights: dict[str, float] | None = None,
    directions: dict[str, int] | None = None,
    means: dict[str, float] | None = None,
) -> FvgQualityScore:
    """Compute the quality score for one FVG event.

    The event is expected to expose:

    - ``gap_size_atr`` (float, ATR-normalised gap height),
    - ``htf_aligned`` (truthy if the FVG direction matches the HTF bias),
    - ``distance_to_price_atr`` (float, >= 0),
    - ``is_full_body`` (truthy if the anchor candle is a full-body one),
    - ``hurst`` (float in [0,1] or ``None``).

    Missing keys are treated as worst-case (0 / False / None) rather
    than silently skipped — the score is only useful if every feature
    is accounted for. Downstream callers can inspect the ``components``
    dict to see which feature drove the final number.

    Mode semantics
    --------------
    Default (production, since Q3 D3 promotion 2026-04-22):
        ``weights = STRICT_V1_NO_HURST_WEIGHTS``,
        ``directions = STRICT_V1_NO_HURST_DIRECTIONS`` (all -1, hurst=0),
        ``means = STRICT_V1_NO_HURST_MEANS`` (all 0.5).
        **Minimal** features → HIGH tier (score → 1.0). Maxed features
        → LOW tier. Tier semantics are inverted relative to the
        legacy lenient regime — see audit §2–3 for the empirical
        basis (HR 0.943 in Q4 of the strict-label fit).

    Legacy back-compat (lenient label):
        Pass ``weights=LENIENT_WEIGHTS, directions=LENIENT_DIRECTIONS,
        means=LENIENT_MEANS``. Maxed features → HIGH tier. Used only
        by callers that haven't migrated to the strict label yet.
    """
    weights = weights if weights is not None else DEFAULT_WEIGHTS
    directions = directions if directions is not None else DEFAULT_DIRECTIONS
    means = means if means is not None else DEFAULT_MEANS

    gap = float(event.get("gap_size_atr", 0.0) or 0.0)
    htf = bool(event.get("htf_aligned", False))
    dist = float(event.get("distance_to_price_atr", 10.0) or 10.0)
    full_body = bool(event.get("is_full_body", False))
    hurst = event.get("hurst")
    if hurst is not None:
        try:
            hurst = float(hurst)
        except (TypeError, ValueError):
            hurst = None
        else:
            if not math.isfinite(hurst):
                hurst = None

    components = {
        "gap_size": _component_gap(gap),
        "htf_aligned": 1.0 if htf else 0.0,
        "distance": _component_distance(max(dist, 0.0)),
        "full_body": 1.0 if full_body else 0.0,
        "hurst": _component_hurst(hurst),
    }

    # Fast-path: pure lenient regime (all directions +1, all means 0)
    # uses the original weighted-sum formula so the legacy pin in
    # ``test_components_sum_weighted_to_score`` and any historical
    # callers see byte-identical scores.
    if (
        all(directions.get(k, 1) == 1 for k in weights)
        and all(abs(means.get(k, 0.0)) < 1e-9 for k in weights)
    ):
        score = sum(
            weights.get(feature_key, 0.0) * components[comp_key]
            for comp_key, feature_key in _COMPONENT_TO_FEATURE.items()
        )
    else:
        score = _score_with_directions(components, weights, directions, means)

    score = round(_clamp(score, 0.0, 1.0), 4)

    tier = "LOW"
    for candidate, threshold in _TIER_THRESHOLDS:
        if score >= threshold:
            tier = candidate
            break

    multiplier = round(
        _MULTIPLIER_MIN + (_MULTIPLIER_MAX - _MULTIPLIER_MIN) * score,
        4,
    )
    return FvgQualityScore(
        score=score,
        tier=tier,
        multiplier=multiplier,
        components={k: round(v, 4) for k, v in components.items()},
    )


def score_events(events: list[dict[str, Any]]) -> list[FvgQualityScore]:
    """Vectorised convenience wrapper — preserves input order."""
    return [score_fvg(event) for event in events]
