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

# Trust-state vocabulary shared with the Pine consumer. ``FRESH`` is
# the happy path; ``DEGRADED`` flags "calibrated but low-confidence"
# (sub-saturation sample or elevated smECE) and instructs Pine to
# treat per-family hit rates as unrenderable. ``STALE`` /
# ``UNAVAILABLE`` are reserved for the WS2 freshness refactor and
# currently only emitted on missing inputs.
TRUST_FRESH: str = "FRESH"
TRUST_DEGRADED: str = "DEGRADED"
TRUST_STALE: str = "STALE"
TRUST_UNAVAILABLE: str = "UNAVAILABLE"

# Sentinel propagated to Pine when confidence gating suppresses a
# family hit rate. ``-1.0`` is unambiguously outside the valid
# ``[0, 1]`` HR range; the existing Pine consumer guards (e.g.
# ``mp.ZONE_HR_FVG <= 0.0`` in SMC_Dashboard.pine) already treat
# this as "no renderable value".
HR_SENTINEL_DEGRADED: float = -1.0

DEFAULTS: dict[str, Any] = {
    "ZONE_CAL_CONFIDENCE": 0.0,
    "ZONE_HR_OB": 0.0,
    "ZONE_HR_FVG": 0.0,
    "ZONE_HR_BOS": 0.0,
    "ZONE_HR_SWEEP": 0.0,
    "ZONE_CAL_TREND": "STABLE",
    "ZONE_CAL_TRUST": TRUST_UNAVAILABLE,
}

# Canonical family list for the per-family ZONE_HR_<FAM> exports.
# Public so downstream callers (notably generate_smc_micro_profiles.py and
# tests/test_library_field_audit.py) can pin to the same single source of
# truth instead of redeclaring the tuple — see ADR 2026-04-22.
FAMILIES: tuple[str, ...] = ("OB", "FVG", "BOS", "SWEEP")

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

# Trust gating. Below this confidence the per-family HR exports are
# degraded to HR_SENTINEL_DEGRADED. The threshold 0.30 corresponds
# to ~300 events at smECE=0 on the 1000-event saturation curve —
# well above the Blasiok & Nakkiran (2023) 30-events-per-bucket
# smECE floor and safely above the 258-event Q2 baseline that
# previously leaked an overstated OB HR (0.8636) into Pine.
# Configurable per call for experiments / tests.
_TRUST_MIN_CONFIDENCE = 0.30


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
    out: dict[str, float] = {f"ZONE_HR_{fam}": 0.0 for fam in FAMILIES}
    if not isinstance(family_stats, dict):
        return out

    for fam in FAMILIES:
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
            for fam in FAMILIES:
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


# Trust state + degradation ---------------------------------------


def classify_trust_state(
    confidence: float,
    *,
    min_confidence: float = _TRUST_MIN_CONFIDENCE,
) -> str:
    """Map a confidence score to the ``ZONE_CAL_TRUST`` vocabulary.

    ``confidence >= min_confidence``    -> ``FRESH``
    ``0 < confidence <  min_confidence`` -> ``DEGRADED``
    ``confidence <= 0`` / NaN / invalid  -> ``UNAVAILABLE``

    ``STALE`` is reserved for freshness-metadata-driven decisions
    that the WS2 refactor will wire in later; this helper never
    emits it on its own.
    """
    try:
        c = float(confidence)
    except (TypeError, ValueError):
        return TRUST_UNAVAILABLE
    if c != c:  # NaN guard
        return TRUST_UNAVAILABLE
    if c <= 0.0:
        return TRUST_UNAVAILABLE
    if c < float(min_confidence):
        return TRUST_DEGRADED
    return TRUST_FRESH


def degrade_family_hit_rates(
    hit_rates: dict[str, float],
    trust_state: str,
) -> dict[str, float]:
    """Replace family HRs with :data:`HR_SENTINEL_DEGRADED` when the
    trust state is ``DEGRADED`` (data exists but is not trustworthy).

    ``FRESH`` and ``UNAVAILABLE`` are passed through: ``FRESH`` is the
    happy path, and ``UNAVAILABLE`` means "no calibration data" — the
    upstream defaults already carry neutral ``0.0`` values that Pine
    consumers guard with ``zone_hr_<fam> <= 0.0``.
    """
    if trust_state == TRUST_DEGRADED:
        return {key: HR_SENTINEL_DEGRADED for key in hit_rates}
    return dict(hit_rates)


# Aggregator used by the Pine generator ---------------------------


def build_consumer_exports(
    *,
    family_stats: dict[str, dict[str, Any]] | None,
    total_events: int | float | None,
    smooth_ece: float | None,
    history: list[dict[str, Any]] | None = None,
    min_confidence: float = _TRUST_MIN_CONFIDENCE,
) -> dict[str, Any]:
    """Combine all Phase H signals into the dict the Pine generator
    consumes. Always returns the full key set defined in
    :data:`DEFAULTS`.

    Trust gating: when ``ZONE_CAL_CONFIDENCE < min_confidence`` the
    per-family ``ZONE_HR_<FAM>`` values are replaced with
    :data:`HR_SENTINEL_DEGRADED` and ``ZONE_CAL_TRUST`` is set to
    ``DEGRADED``. This prevents the Pine consumer from displaying a
    high hit-rate number backed by an under-saturated corpus (the
    2026-04-22 symptom: 258-event smoke leaked
    ZONE_HR_OB=0.8636 while the v3 corpus n=952 showed OB HR=0.3675).
    """
    out: dict[str, Any] = dict(DEFAULTS)
    confidence = compute_calibration_confidence(
        total_events=total_events, smooth_ece=smooth_ece
    )
    out["ZONE_CAL_CONFIDENCE"] = confidence
    trust = classify_trust_state(confidence, min_confidence=min_confidence)
    out["ZONE_CAL_TRUST"] = trust
    out.update(
        degrade_family_hit_rates(
            compute_per_family_hit_rates(family_stats), trust
        )
    )
    out["ZONE_CAL_TREND"] = compute_calibration_trend(history)
    return out
