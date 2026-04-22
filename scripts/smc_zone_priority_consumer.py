"""Phase H — Pine Consumer Maturity exports for Zone Priority.

This module derives the consumer-facing calibration signals that the
Pine dashboard surfaces alongside the existing ``ZONE_CAL_<FAM>`` /
``ZONE_PRIORITY_*`` exports:

* ``ZONE_CAL_CONFIDENCE`` (H1) — a single 0–1 score combining sample
  size and calibration drift, so the user immediately sees how much
  to trust the calibrated weights.
* ``ZONE_HR_<FAM>`` (H2) — per-family weighted hit rates lifted
  straight out of ``zone_priority_calibration.json::family_stats``.
* ``ZONE_CAL_TREND`` (H3) — ``IMPROVING`` / ``STABLE`` / ``DEGRADING``
  derived from the last few calibration runs.

All three helpers are pure, deterministic, and tolerant of missing
inputs — they fall back to ``DEFAULTS`` so the Pine layer always gets
a renderable value.
"""

from __future__ import annotations

from typing import Any

# Public surface --------------------------------------------------

DEFAULTS: dict[str, Any] = {
    "ZONE_CAL_CONFIDENCE": 0.0,
    "ZONE_HR_OB": 0.0,
    "ZONE_HR_FVG": 0.0,
    "ZONE_HR_BOS": 0.0,
    "ZONE_HR_SWEEP": 0.0,
    "ZONE_CAL_TREND": "STABLE",
}

_FAMILIES: tuple[str, ...] = ("OB", "FVG", "BOS", "SWEEP")

# H1 confidence tuning. The 1000-event saturation point matches the Q3
# success-target ("Total Events ≥ 1.000") in docs/STRATEGY_2026_Q3.md.
# The smECE penalty zeroes the confidence at smECE >= 0.20 — the
# heuristic threshold the F3 follow-on smoke flagged as "drift
# candidate" (LONDON 0.233, ASIA 0.202).
_EVENTS_SATURATION = 1000
_ECE_PENALTY_SLOPE = 5.0  # smECE 0.20 → penalty 1.0 → confidence 0

# H3 trend tuning. ``min_runs=3`` matches
# ``ContextualCalibrationPromotionPolicy.min_history_runs`` so trend
# only fires once the promotion policy itself would consider history
# usable. The +/-2 % delta on the average weighted hit rate is the
# same threshold that promotes a contextual calibration to live.
_TREND_MIN_RUNS = 3
_TREND_DELTA = 0.02


# H1 — Calibration Confidence -------------------------------------


def compute_calibration_confidence(
    total_events: int | float | None,
    smooth_ece: float | None,
) -> float:
    """Return a 0–1 confidence score from sample size and smECE drift.

    ``total_events`` saturates at :data:`_EVENTS_SATURATION` (1000)
    events. ``smooth_ece`` is penalised linearly with slope
    :data:`_ECE_PENALTY_SLOPE` so smECE ≥ 0.20 zeroes the score.
    Either input being ``None`` / non-finite returns ``0.0``.
    """
    try:
        n = float(total_events) if total_events is not None else 0.0
    except (TypeError, ValueError):
        return 0.0
    try:
        ece = float(smooth_ece) if smooth_ece is not None else 0.0
    except (TypeError, ValueError):
        return 0.0

    if n <= 0.0:
        return 0.0

    events_score = min(1.0, n / float(_EVENTS_SATURATION))
    ece_penalty = max(0.0, 1.0 - _ECE_PENALTY_SLOPE * ece)
    return round(max(0.0, min(1.0, events_score * ece_penalty)), 4)


# H2 — Per-family hit rates ---------------------------------------


def compute_per_family_hit_rates(
    family_stats: dict[str, dict[str, Any]] | None,
) -> dict[str, float]:
    """Return ``{"ZONE_HR_<FAM>": weighted_hit_rate}`` for the four
    families. Missing / malformed stats default to ``0.0`` so the
    Pine consumer always sees a renderable float.
    """
    out: dict[str, float] = {f"ZONE_HR_{fam}": 0.0 for fam in _FAMILIES}
    if not isinstance(family_stats, dict):
        return out

    for fam in _FAMILIES:
        stats = family_stats.get(fam)
        if not isinstance(stats, dict):
            continue
        # Prefer the weighted hit rate (matches the calibration JSON).
        hr_raw = stats.get("weighted_hit_rate")
        if hr_raw is None:
            hr_raw = stats.get("simple_hit_rate")
        if hr_raw is None:
            continue
        try:
            hr = float(hr_raw)
        except (TypeError, ValueError):
            continue
        if hr != hr:  # NaN guard
            continue
        out[f"ZONE_HR_{fam}"] = round(max(0.0, min(1.0, hr)), 4)
    return out


# H3 — Calibration trend ------------------------------------------


def compute_calibration_trend(
    history: list[dict[str, Any]] | None,
    *,
    min_runs: int = _TREND_MIN_RUNS,
    delta: float = _TREND_DELTA,
) -> str:
    """Classify the calibration trajectory across recent runs.

    ``history`` is expected to be ordered oldest → newest. Each entry
    must expose either ``weighted_hit_rate`` (corpus-level) or a
    ``family_stats`` dict from which an unweighted family average is
    derived.

    Returns:
        - ``"IMPROVING"`` when ``last - first > delta``
        - ``"DEGRADING"`` when ``first - last > delta``
        - ``"STABLE"``   otherwise (also for fewer than ``min_runs``).
    """
    if not history or len(history) < min_runs:
        return "STABLE"

    series: list[float] = []
    for entry in history:
        if not isinstance(entry, dict):
            continue
        raw = entry.get("weighted_hit_rate")
        if raw is None:
            stats = entry.get("family_stats") or {}
            family_hrs = []
            for fam in _FAMILIES:
                fs = stats.get(fam)
                if isinstance(fs, dict):
                    fhr = fs.get("weighted_hit_rate")
                    if fhr is None:
                        fhr = fs.get("simple_hit_rate")
                    if fhr is not None:
                        try:
                            family_hrs.append(float(fhr))
                        except (TypeError, ValueError):
                            continue
            if not family_hrs:
                continue
            raw = sum(family_hrs) / len(family_hrs)
        try:
            value = float(raw)
        except (TypeError, ValueError):
            continue
        if value != value:  # NaN guard
            continue
        series.append(value)

    if len(series) < min_runs:
        return "STABLE"

    diff = series[-1] - series[0]
    if diff > delta:
        return "IMPROVING"
    if diff < -delta:
        return "DEGRADING"
    return "STABLE"


# Aggregator used by the Pine generator ---------------------------


def build_consumer_exports(
    *,
    family_stats: dict[str, dict[str, Any]] | None,
    total_events: int | float | None,
    smooth_ece: float | None,
    history: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Combine all Phase H signals into the dict the Pine generator
    consumes. Always returns the full key set defined in
    :data:`DEFAULTS`.
    """
    out: dict[str, Any] = dict(DEFAULTS)
    out["ZONE_CAL_CONFIDENCE"] = compute_calibration_confidence(
        total_events=total_events, smooth_ece=smooth_ece
    )
    out.update(compute_per_family_hit_rates(family_stats))
    out["ZONE_CAL_TREND"] = compute_calibration_trend(history)
    return out
