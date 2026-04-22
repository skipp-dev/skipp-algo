"""Tests for the Phase H Pine consumer exports."""

from __future__ import annotations

import math

import pytest

from scripts.smc_zone_priority_consumer import (
    DEFAULTS,
    build_consumer_exports,
    compute_calibration_confidence,
    compute_calibration_trend,
    compute_per_family_hit_rates,
)


# ── Defaults ────────────────────────────────────────────────────


def test_defaults_have_required_keys() -> None:
    assert set(DEFAULTS) == {
        "ZONE_CAL_CONFIDENCE",
        "ZONE_HR_OB",
        "ZONE_HR_FVG",
        "ZONE_HR_BOS",
        "ZONE_HR_SWEEP",
        "ZONE_CAL_TREND",
    }


def test_defaults_are_neutral() -> None:
    assert DEFAULTS["ZONE_CAL_CONFIDENCE"] == 0.0
    assert DEFAULTS["ZONE_HR_OB"] == 0.0
    assert DEFAULTS["ZONE_CAL_TREND"] == "STABLE"


# ── H1: Calibration Confidence ─────────────────────────────────


def test_confidence_zero_when_no_events() -> None:
    assert compute_calibration_confidence(0, 0.05) == 0.0
    assert compute_calibration_confidence(None, 0.05) == 0.0


def test_confidence_saturates_at_1000_events_with_clean_ece() -> None:
    # Perfect case — well-calibrated and well-sampled.
    assert compute_calibration_confidence(1000, 0.0) == 1.0
    # Beyond saturation does not exceed 1.0.
    assert compute_calibration_confidence(5000, 0.0) == 1.0


def test_confidence_scales_linearly_below_saturation() -> None:
    # 250 events / 1000 saturation × no ECE penalty = 0.25
    assert compute_calibration_confidence(250, 0.0) == 0.25


def test_confidence_zeroed_by_high_smooth_ece() -> None:
    # smECE 0.20 → penalty multiplier 0.0 → confidence 0 regardless
    # of sample size. This is the "do not trust" boundary.
    assert compute_calibration_confidence(1000, 0.20) == 0.0
    assert compute_calibration_confidence(1000, 0.30) == 0.0


def test_confidence_partial_penalty_smooth_ece() -> None:
    # smECE 0.10 → penalty 1.0 - 5*0.10 = 0.50.
    # 1000 events → events_score 1.0. Confidence = 0.50.
    assert compute_calibration_confidence(1000, 0.10) == 0.50


def test_confidence_handles_invalid_inputs_gracefully() -> None:
    assert compute_calibration_confidence("not-a-number", 0.05) == 0.0
    assert compute_calibration_confidence(500, "bad") == 0.0
    assert compute_calibration_confidence(-50, 0.05) == 0.0


# ── H2: Per-family hit rates ───────────────────────────────────


_REAL_STATS = {
    "OB":    {"weighted_hit_rate": 0.8636, "simple_hit_rate": 0.8636},
    "FVG":   {"weighted_hit_rate": 0.5937, "simple_hit_rate": 0.5938},
    "BOS":   {"weighted_hit_rate": 0.913,  "simple_hit_rate": 0.913},
    "SWEEP": {"weighted_hit_rate": 0.8333, "simple_hit_rate": 0.8333},
}


def test_per_family_hit_rates_passthrough() -> None:
    out = compute_per_family_hit_rates(_REAL_STATS)
    assert out["ZONE_HR_OB"] == 0.8636
    assert out["ZONE_HR_FVG"] == 0.5937
    assert out["ZONE_HR_BOS"] == 0.913
    assert out["ZONE_HR_SWEEP"] == 0.8333


def test_per_family_hit_rates_missing_family_defaults_zero() -> None:
    out = compute_per_family_hit_rates({"OB": _REAL_STATS["OB"]})
    assert out["ZONE_HR_OB"] == 0.8636
    assert out["ZONE_HR_FVG"] == 0.0
    assert out["ZONE_HR_BOS"] == 0.0
    assert out["ZONE_HR_SWEEP"] == 0.0


def test_per_family_hit_rates_falls_back_to_simple() -> None:
    out = compute_per_family_hit_rates(
        {"OB": {"simple_hit_rate": 0.75}}
    )
    assert out["ZONE_HR_OB"] == 0.75


def test_per_family_hit_rates_handles_nan_and_invalid() -> None:
    out = compute_per_family_hit_rates(
        {
            "OB":    {"weighted_hit_rate": float("nan")},
            "FVG":   {"weighted_hit_rate": "bad"},
            "BOS":   {"weighted_hit_rate": 1.5},   # clamped to 1.0
            "SWEEP": {"weighted_hit_rate": -0.2},  # clamped to 0.0
        }
    )
    assert out["ZONE_HR_OB"] == 0.0
    assert out["ZONE_HR_FVG"] == 0.0
    assert out["ZONE_HR_BOS"] == 1.0
    assert out["ZONE_HR_SWEEP"] == 0.0


def test_per_family_hit_rates_none_input() -> None:
    out = compute_per_family_hit_rates(None)
    assert out == {f"ZONE_HR_{f}": 0.0 for f in ("OB", "FVG", "BOS", "SWEEP")}


# ── H3: Calibration trend ──────────────────────────────────────


def test_trend_stable_with_too_few_runs() -> None:
    history = [
        {"weighted_hit_rate": 0.60},
        {"weighted_hit_rate": 0.80},
    ]
    assert compute_calibration_trend(history) == "STABLE"


def test_trend_improving() -> None:
    history = [
        {"weighted_hit_rate": 0.60},
        {"weighted_hit_rate": 0.65},
        {"weighted_hit_rate": 0.70},
    ]
    assert compute_calibration_trend(history) == "IMPROVING"


def test_trend_degrading() -> None:
    history = [
        {"weighted_hit_rate": 0.80},
        {"weighted_hit_rate": 0.75},
        {"weighted_hit_rate": 0.70},
    ]
    assert compute_calibration_trend(history) == "DEGRADING"


def test_trend_stable_within_delta() -> None:
    # Delta < 0.02 across the window → STABLE.
    history = [
        {"weighted_hit_rate": 0.700},
        {"weighted_hit_rate": 0.705},
        {"weighted_hit_rate": 0.715},
    ]
    assert compute_calibration_trend(history) == "STABLE"


def test_trend_derives_avg_from_family_stats_when_top_level_missing() -> None:
    # Three runs, each only carrying family_stats — IMPROVING from 0.6
    # avg → 0.85 avg (mocking what the calibration JSON ships).
    history = [
        {"family_stats": {fam: {"weighted_hit_rate": 0.60} for fam in ("OB", "FVG", "BOS", "SWEEP")}},
        {"family_stats": {fam: {"weighted_hit_rate": 0.72} for fam in ("OB", "FVG", "BOS", "SWEEP")}},
        {"family_stats": {fam: {"weighted_hit_rate": 0.85} for fam in ("OB", "FVG", "BOS", "SWEEP")}},
    ]
    assert compute_calibration_trend(history) == "IMPROVING"


def test_trend_handles_none_and_empty() -> None:
    assert compute_calibration_trend(None) == "STABLE"
    assert compute_calibration_trend([]) == "STABLE"


# ── Aggregator ──────────────────────────────────────────────────


def test_build_consumer_exports_full_payload() -> None:
    out = build_consumer_exports(
        family_stats=_REAL_STATS,
        total_events=258,           # the Q2 baseline corpus size
        smooth_ece=0.05,
        history=[
            {"weighted_hit_rate": 0.70},
            {"weighted_hit_rate": 0.74},
            {"weighted_hit_rate": 0.78},
        ],
    )
    # Keys complete.
    assert set(out) == set(DEFAULTS)
    # 258/1000 events × (1 - 5*0.05=0.75) penalty = 0.1935
    assert out["ZONE_CAL_CONFIDENCE"] == pytest.approx(0.1935, abs=1e-4)
    # Hit rates pass through.
    assert out["ZONE_HR_OB"] == 0.8636
    # Trend captured.
    assert out["ZONE_CAL_TREND"] == "IMPROVING"


def test_build_consumer_exports_defaults_on_empty() -> None:
    out = build_consumer_exports(
        family_stats=None, total_events=None, smooth_ece=None, history=None
    )
    assert out == DEFAULTS
