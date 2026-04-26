"""Sprint C9.1 — PSI trend alert + importance-weighted PSI.

ml/drift.MLDriftDetector emits a level-based PSI alarm (>= warn / >= alarm)
on per-call probability snapshots. Two known weaknesses:

1. **Slow-creeping drift goes undetected** until a window finally
   crosses the level threshold. A 14-day climb from 0.05 → 0.24 stays
   "ok" the whole time, then jumps to "warn" out of nowhere.

2. **Per-feature PSI is noisy** when all features are weighted equally
   in dashboards/aggregates: a 0.5 PSI on a feature with importance
   0.001 should not look like a 0.5 PSI on a feature with importance
   0.30.

C9.1 ships two pure helpers:

- ``psi_trend_alert(history, slope_threshold, window)`` fits a least-
  squares slope to the most recent ``window`` PSI samples and emits
  ``trend_warn`` / ``trend_alarm`` independent of the level alert.

- ``psi_weighted(per_feature_psi, importance)`` computes an importance-
  weighted scalar from a dict of per-feature PSI values. Importance
  weights are normalised; missing keys contribute zero weight.

Roadmap: docs/IMPROVEMENTS_C2_C12_ROADMAP_2026-04-26.md#c91
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

TrendSeverity = Literal["ok", "trend_warn", "trend_alarm"]


@dataclass(frozen=True)
class PSITrendAlert:
    severity: TrendSeverity
    slope_per_day: float
    window: int
    n_samples: int
    slope_threshold_warn: float
    slope_threshold_alarm: float


def _least_squares_slope(values: Sequence[float]) -> float:
    """Slope of values vs (0, 1, 2, ...) via closed-form OLS."""
    n = len(values)
    if n < 2:
        return 0.0
    mean_x = (n - 1) / 2.0
    mean_y = sum(values) / n
    num = 0.0
    den = 0.0
    for i, y in enumerate(values):
        dx = i - mean_x
        num += dx * (y - mean_y)
        den += dx * dx
    if den <= 0.0:
        return 0.0
    return num / den


def psi_trend_alert(
    history: Sequence[float],
    *,
    window: int = 7,
    slope_warn: float = 0.005,
    slope_alarm: float = 0.015,
) -> PSITrendAlert:
    """Fit a slope to the trailing ``window`` PSI samples.

    The samples are interpreted as one observation per uniform time
    step (typically per day). Returns ``trend_alarm`` if the slope
    exceeds ``slope_alarm``, ``trend_warn`` if above ``slope_warn``,
    else ``ok``. With ``< 2`` usable samples the helper returns
    ``ok`` with slope 0 — a single sample cannot exhibit a trend.

    Defaults are chosen so a 14-day climb from 0.05 → 0.20 (slope
    ~0.011/day) lands in ``trend_warn`` and a sharper 0.20-in-7-days
    climb (slope ~0.029/day) hits ``trend_alarm``.
    """
    if window < 2:
        raise ValueError(f"window must be >= 2, got {window}")
    if not (0.0 < slope_warn < slope_alarm):
        raise ValueError("require 0 < slope_warn < slope_alarm")

    n_total = len(history)
    if n_total == 0:
        return PSITrendAlert(
            severity="ok",
            slope_per_day=0.0,
            window=window,
            n_samples=0,
            slope_threshold_warn=slope_warn,
            slope_threshold_alarm=slope_alarm,
        )
    tail = list(history[-window:])
    slope = _least_squares_slope(tail)
    if slope >= slope_alarm:
        severity: TrendSeverity = "trend_alarm"
    elif slope >= slope_warn:
        severity = "trend_warn"
    else:
        severity = "ok"
    return PSITrendAlert(
        severity=severity,
        slope_per_day=slope,
        window=window,
        n_samples=len(tail),
        slope_threshold_warn=slope_warn,
        slope_threshold_alarm=slope_alarm,
    )


def psi_weighted(
    per_feature_psi: Mapping[str, float],
    importance: Mapping[str, float] | None = None,
) -> float:
    """Importance-weighted aggregate PSI.

    Parameters
    ----------
    per_feature_psi:
        ``{feature_name: psi_value}``.
    importance:
        ``{feature_name: weight}``. Negative weights are clamped to 0.
        Missing keys are treated as zero weight (i.e. excluded).
        ``None`` falls back to equal-weighted mean of the input PSIs.

    Returns the weighted mean PSI (zero when no positive-weight overlap).
    """
    if not per_feature_psi:
        return 0.0
    if importance is None:
        return sum(per_feature_psi.values()) / len(per_feature_psi)
    total_weight = 0.0
    weighted_sum = 0.0
    for feature, psi in per_feature_psi.items():
        w = float(importance.get(feature, 0.0))
        if w <= 0.0:
            continue
        weighted_sum += w * float(psi)
        total_weight += w
    if total_weight <= 0.0:
        return 0.0
    return weighted_sum / total_weight


__all__ = [
    "PSITrendAlert",
    "TrendSeverity",
    "psi_trend_alert",
    "psi_weighted",
]
