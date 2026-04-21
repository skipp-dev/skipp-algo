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


def score_fvg(event: dict[str, Any]) -> FvgQualityScore:
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
    """
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
    score = (
        0.30 * components["gap_size"]
        + 0.25 * components["htf_aligned"]
        + 0.15 * components["distance"]
        + 0.10 * components["full_body"]
        + 0.20 * components["hurst"]
    )
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
