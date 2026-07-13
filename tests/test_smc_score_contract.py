"""Contract enforcement for public SMC score fields.

Guards two boundaries where a score could escape its documented range:

* manual ``overrides`` on the score builders (a test/manual affordance) that were
  previously applied verbatim — so ``SIGNAL_QUALITY_SCORE=500`` or
  ``ZONE_PRIORITY_SCORE=-20`` reached the Pine / Trust consumers unchecked; and
* the profile-context rate reads, which took DataFrame cells with only ``round()``
  so a ``NaN`` (thin-history symbol) or an out-of-[0,1] value flowed into
  ``PROFILE_CLEAN_SCORE`` → ticker grade.
"""
from __future__ import annotations

import math

import pandas as pd

from scripts.smc_score_contract import (
    apply_bounded_override,
    clamp_finite,
    clamp_finite_01,
    clamp_override,
)


# ── helper unit tests ──────────────────────────────────────────────────────
def test_clamp_finite_01_bounds_and_nonfinite() -> None:
    assert clamp_finite_01(0.5) == 0.5
    assert clamp_finite_01(1.5) == 1.0
    assert clamp_finite_01(-0.2) == 0.0
    assert clamp_finite_01(float("nan")) == 0.0
    assert clamp_finite_01(float("inf")) == 0.0
    assert clamp_finite_01(float("-inf")) == 0.0
    assert clamp_finite_01(float("nan"), default=0.3) == 0.3


def test_clamp_finite_arbitrary_range() -> None:
    assert clamp_finite(7.0, 0.0, 5.0) == 5.0
    assert clamp_finite(-1.0, 0.0, 5.0) == 0.0
    assert clamp_finite(3.0, 0.0, 5.0) == 3.0
    assert clamp_finite(float("nan"), 0.0, 5.0) == 0.0


def test_clamp_override_clamps_in_range() -> None:
    assert clamp_override(500, 0.0, 100.0, as_int=True) == 100
    assert clamp_override(-20, 0.0, 100.0, as_int=True) == 0
    assert clamp_override(99, 0.0, 100.0, as_int=True) == 99
    assert clamp_override(3.7, 0.0, 5.0, as_int=False) == 3.7
    assert clamp_override(1.5, 0.0, 1.0, as_int=False) == 1.0


def test_clamp_override_rejects_nonnumeric_and_nonfinite() -> None:
    assert clamp_override("high", 0.0, 100.0, as_int=True) is None
    assert clamp_override(None, 0.0, 100.0, as_int=True) is None
    assert clamp_override(float("nan"), 0.0, 100.0, as_int=True) is None
    assert clamp_override(float("inf"), 0.0, 100.0, as_int=True) is None
    # bool is an int subclass but never a meaningful score -> rejected.
    assert clamp_override(True, 0.0, 100.0, as_int=True) is None


def test_apply_bounded_override_clamp_reject_passthrough() -> None:
    bounds = {"SCORE": (0.0, 100.0, True)}
    # in-range clamp
    result = {"SCORE": 40, "TIER": "low"}
    apply_bounded_override(result, "SCORE", 500, bounds)
    assert result["SCORE"] == 100
    # rejected override keeps the computed value
    result = {"SCORE": 40}
    apply_bounded_override(result, "SCORE", float("nan"), bounds)
    assert result["SCORE"] == 40
    # non-bounded (string) field passes through unchanged
    result = {"TIER": "low"}
    apply_bounded_override(result, "TIER", "high", bounds)
    assert result["TIER"] == "high"


# ── builder override clamping ──────────────────────────────────────────────
def test_signal_quality_override_clamped_to_0_100() -> None:
    from scripts.smc_signal_quality import build_signal_quality

    hi = build_signal_quality(enrichment={}, overrides={"SIGNAL_QUALITY_SCORE": 500})
    assert hi["SIGNAL_QUALITY_SCORE"] == 100
    lo = build_signal_quality(enrichment={}, overrides={"SIGNAL_QUALITY_SCORE": -20})
    assert lo["SIGNAL_QUALITY_SCORE"] == 0
    # a non-finite override is rejected; the computed score stands (not NaN).
    nan_ovr = build_signal_quality(enrichment={}, overrides={"SIGNAL_QUALITY_SCORE": float("nan")})
    assert isinstance(nan_ovr["SIGNAL_QUALITY_SCORE"], int)
    assert 0 <= nan_ovr["SIGNAL_QUALITY_SCORE"] <= 100
    # string field override still passes through.
    tier = build_signal_quality(enrichment={}, overrides={"SIGNAL_QUALITY_TIER": "high"})
    assert tier["SIGNAL_QUALITY_TIER"] == "high"


def test_zone_priority_override_clamped_and_valid_preserved() -> None:
    from scripts.smc_zone_priority import build_zone_priority

    assert build_zone_priority(overrides={"ZONE_PRIORITY_SCORE": 999})["ZONE_PRIORITY_SCORE"] == 100
    assert build_zone_priority(overrides={"ZONE_PRIORITY_SCORE": -5})["ZONE_PRIORITY_SCORE"] == 0
    # a valid in-range override (existing contract) is preserved exactly.
    ok = build_zone_priority(overrides={"ZONE_PRIORITY_RANK": "A", "ZONE_PRIORITY_SCORE": 99})
    assert ok["ZONE_PRIORITY_RANK"] == "A"
    assert ok["ZONE_PRIORITY_SCORE"] == 99


def test_liquidity_sweeps_override_clamped_to_0_5() -> None:
    from scripts.smc_liquidity_sweeps import build_liquidity_sweeps

    assert build_liquidity_sweeps(overrides={"SWEEP_QUALITY_SCORE": 99})["SWEEP_QUALITY_SCORE"] == 5
    assert build_liquidity_sweeps(overrides={"SWEEP_QUALITY_SCORE": -3})["SWEEP_QUALITY_SCORE"] == 0


def test_profile_context_override_clamped_to_contract() -> None:
    from scripts.smc_profile_context import build_profile_context

    clean = build_profile_context(overrides={"PROFILE_CLEAN_SCORE": 5.0})
    assert clean["PROFILE_CLEAN_SCORE"] == 1.0
    ctx = build_profile_context(overrides={"PROFILE_CONTEXT_SCORE": 50})
    assert ctx["PROFILE_CONTEXT_SCORE"] == 5
    # string grade override still passes through.
    grade = build_profile_context(overrides={"PROFILE_TICKER_GRADE": "A"})
    assert grade["PROFILE_TICKER_GRADE"] == "A"


# ── profile-context rate-input validation (#4) ─────────────────────────────
def _make_snapshot(**kwargs) -> pd.DataFrame:
    defaults = {
        "symbol": "AAPL",
        "avg_spread_bps_rth_20d": 2.5,
        "rth_active_minutes_share_20d": 0.90,
        "pm_dollar_share_20d": 0.10,
        "ah_dollar_share_20d": 0.08,
        "midday_efficiency_20d": 0.80,
        "setup_decay_half_life_bars_20d": 25.0,
        "consistency_score_20d": 0.85,
        "wickiness_20d": 0.10,
        "clean_intraday_score_20d": 0.80,
        "reclaim_respect_rate_20d": 0.75,
        "stop_hunt_rate_20d": 0.08,
    }
    defaults.update(kwargs)
    return pd.DataFrame([defaults])


def test_profile_clean_score_nan_input_is_zeroed_not_propagated() -> None:
    from scripts.smc_profile_context import build_profile_context

    result = build_profile_context(snapshot=_make_snapshot(clean_intraday_score_20d=float("nan")), symbol="AAPL")
    assert result["PROFILE_CLEAN_SCORE"] == 0.0
    assert math.isfinite(result["PROFILE_CLEAN_SCORE"])
    # ticker grade must be a finite categorical, never derived from NaN.
    assert result["PROFILE_TICKER_GRADE"] in {"A", "B", "C", "D"}


def test_profile_rate_inputs_out_of_range_are_clamped_to_unit_interval() -> None:
    from scripts.smc_profile_context import build_profile_context

    result = build_profile_context(
        snapshot=_make_snapshot(
            clean_intraday_score_20d=1.5,
            consistency_score_20d=2.0,
            reclaim_respect_rate_20d=-0.4,
            stop_hunt_rate_20d=9.0,
            wickiness_20d=float("inf"),
        ),
        symbol="AAPL",
    )
    assert result["PROFILE_CLEAN_SCORE"] == 1.0
    assert result["PROFILE_CONSISTENCY"] == 1.0
    assert result["PROFILE_RECLAIM_RATE"] == 0.0
    assert result["PROFILE_STOP_HUNT_RATE"] == 1.0
    assert result["PROFILE_WICKINESS"] == 0.0  # inf -> default 0.0


def test_profile_valid_rates_unchanged() -> None:
    from scripts.smc_profile_context import build_profile_context

    result = build_profile_context(snapshot=_make_snapshot(clean_intraday_score_20d=0.80), symbol="AAPL")
    assert result["PROFILE_CLEAN_SCORE"] == 0.80
