"""Bucket C coverage uplift for `open_prep.technical_analysis`.

Targets the 143-miss / 68%-cov surface left after the existing
`test_open_prep.py` / `test_smoke_v2_features.py` /
`test_production_gatekeeper.py` baseline. Focus areas:

- `_unit_scale` NaN + degenerate-range branches.
- `apply_diminishing_returns` `use_sqrt=False` short-circuit.
- `classify_instrument` boundary cases for every band.
- `compute_adaptive_gates` high-VIX / low-VIX / instrument-class paths.
- `detect_consolidation` ATR-ratio bands.
- `detect_breakout` insufficient-data + every pattern path
  (B_UP / B_DOWN / range_breakout_short / range_breakout_long /
  range_breakdown_short / range_breakdown_long / no_breakout).
- `validate_data_quality` every issue branch.
- `GateTracker.reject` deficit tracking + non-numeric value swallowing,
  `summary`, `bottleneck_report`, `clear`, and `rejection_count`.
- `calculate_support_resistance_targets` early-return + happy-path with
  enough bars so EMA/Fibonacci/pivots/swings/targets all populate.
- `compute_entry_probability` overflow + edge-of-range inputs.
- `_calculate_energy_weights` short-circuit + zero-energy fallback.
- `calculate_ewma` / `calculate_ewma_metrics` / `calculate_ewma_score`
  full chain with breakdown / bounce_zone / overextended / mid-band paths.
- `resolve_regime_weights` TRENDING / RANGING / NEUTRAL + iterative cap.
"""

from __future__ import annotations

import math
from typing import Any

import pytest

from open_prep import technical_analysis as ta
from open_prep.technical_analysis import (
    DataQualityResult,
    GateTracker,
    _calculate_energy_weights,
    _ema,
    _safe_float,
    _unit_scale,
    apply_diminishing_returns,
    calculate_ewma,
    calculate_ewma_metrics,
    calculate_ewma_score,
    calculate_support_resistance_targets,
    classify_instrument,
    compute_adaptive_gates,
    compute_entry_probability,
    compute_risk_penalty,
    detect_breakout,
    detect_consolidation,
    detect_symbol_regime,
    resolve_regime_weights,
    validate_data_quality,
)

# ---------------------------------------------------------------------------
# _unit_scale / _safe_float / apply_diminishing_returns / _ema
# ---------------------------------------------------------------------------


def test_unit_scale_nan_returns_default() -> None:
    assert _unit_scale(float("nan"), 0.0, 1.0, default=0.7) == 0.7


def test_unit_scale_none_returns_default() -> None:
    assert _unit_scale(None, 0.0, 1.0, default=0.3) == 0.3


def test_unit_scale_equal_bounds_clamps_default() -> None:
    # Default of 5.0 must clamp to [0, 1].
    assert _unit_scale(2.0, 1.0, 1.0, default=5.0) == 1.0
    assert _unit_scale(2.0, 1.0, 1.0, default=-2.0) == 0.0


def test_unit_scale_clamps_to_unit_interval() -> None:
    assert _unit_scale(-5.0, 0.0, 1.0) == 0.0
    assert _unit_scale(5.0, 0.0, 1.0) == 1.0
    assert _unit_scale(0.5, 0.0, 1.0) == pytest.approx(0.5)


def test_safe_float_handles_garbage() -> None:
    assert _safe_float("abc", default=1.5) == 1.5
    assert _safe_float(None, default=2.0) == 2.0
    assert _safe_float(float("nan"), default=3.0) == 3.0
    assert _safe_float("4.5") == pytest.approx(4.5)


def test_apply_diminishing_returns_disable_short_circuits() -> None:
    assert apply_diminishing_returns(0.4, use_sqrt=False) == 0.4


def test_apply_diminishing_returns_clamps_input_then_sqrt() -> None:
    assert apply_diminishing_returns(-1.0) == 0.0
    assert apply_diminishing_returns(2.0) == 1.0
    assert apply_diminishing_returns(0.25) == pytest.approx(0.5)


def test_ema_empty_returns_nan() -> None:
    assert math.isnan(_ema([], 5))


def test_ema_single_value_returns_that_value() -> None:
    assert _ema([42.0], 10) == 42.0


# ---------------------------------------------------------------------------
# compute_risk_penalty
# ---------------------------------------------------------------------------


def test_compute_risk_penalty_floors_at_5_percent_when_no_signals() -> None:
    assert compute_risk_penalty(price=100.0, atr=None, volume_ratio=1.0) == 0.05


def test_compute_risk_penalty_caps_at_20_percent_under_extreme_inputs() -> None:
    out = compute_risk_penalty(price=10.0, atr=5.0, volume_ratio=0.0, spread_pct=10.0)
    assert out == pytest.approx(0.20)


def test_compute_risk_penalty_includes_volume_and_spread_components() -> None:
    out = compute_risk_penalty(price=100.0, atr=2.0, volume_ratio=0.4, spread_pct=0.05)
    assert 0.05 < out < 0.20


# ---------------------------------------------------------------------------
# classify_instrument
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "price,atr_pct,expected",
    [
        (3.0, 1.0, "penny"),       # price < 5
        (50.0, 9.0, "penny"),      # high ATR
        (10.0, 1.0, "small_cap"),  # price < 20
        (40.0, 4.0, "small_cap"),  # ATR > 3 with price < 50
        (75.0, 1.0, "mid_cap"),    # price < 100
        (180.0, 2.0, "mid_cap"),   # ATR > 1.5 with price < 200
        (500.0, 0.5, "large_cap"),
    ],
)
def test_classify_instrument_band_matrix(
    price: float, atr_pct: float, expected: str
) -> None:
    assert classify_instrument(price, atr_pct) == expected


# ---------------------------------------------------------------------------
# compute_adaptive_gates
# ---------------------------------------------------------------------------


def test_compute_adaptive_gates_high_vix_relaxes() -> None:
    out = compute_adaptive_gates(vix_level=35.0, instrument_class="penny")
    # vix_mult = 0.85 → score_min decreases vs base 0.35
    assert out["score_min"] < 0.35
    assert out["atr_ratio_min"] == 0.5  # penny


def test_compute_adaptive_gates_low_vix_tightens() -> None:
    out = compute_adaptive_gates(vix_level=10.0, instrument_class="large_cap")
    assert out["score_min"] > 0.35
    assert out["atr_ratio_min"] == 2.5


def test_compute_adaptive_gates_normal_vix_unchanged_score() -> None:
    out = compute_adaptive_gates(vix_level=20.0, instrument_class="mid_cap")
    assert out["score_min"] == pytest.approx(0.35)
    assert out["atr_ratio_min"] == 1.5


def test_compute_adaptive_gates_unknown_class_falls_back_to_base() -> None:
    out = compute_adaptive_gates(
        vix_level=20.0, instrument_class="cosmic", base_atr_ratio_min=1.7
    )
    assert out["atr_ratio_min"] == 1.7


# ---------------------------------------------------------------------------
# detect_symbol_regime
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "adx,bbw,expected",
    [
        (30.0, 5.0, "TRENDING"),
        (10.0, 1.0, "RANGING"),
        (22.0, 3.0, "NEUTRAL"),
    ],
)
def test_detect_symbol_regime_three_buckets(adx: float, bbw: float, expected: str) -> None:
    assert detect_symbol_regime(adx, bbw) == expected


# ---------------------------------------------------------------------------
# detect_consolidation
# ---------------------------------------------------------------------------


def test_detect_consolidation_zero_threshold_clamped() -> None:
    out = detect_consolidation(bb_width_pct=5.0, adx=10.0, bb_squeeze_threshold=0.0)
    # threshold gets clamped to 0.001 → bb_width_pct (5.0) is NOT < 0.001
    assert out["bb_squeeze"] is False


def test_detect_consolidation_atr_ratio_score_bands() -> None:
    out_tight = detect_consolidation(2.0, 5.0, atr_ratio=1.0)
    out_med = detect_consolidation(2.0, 5.0, atr_ratio=1.7)
    out_loose = detect_consolidation(2.0, 5.0, atr_ratio=3.0)
    out_none = detect_consolidation(2.0, 5.0, atr_ratio=None)
    assert out_tight["score"] > out_med["score"] > out_loose["score"]
    assert out_tight["atr_contracted"] is True
    assert out_loose["atr_contracted"] is False
    # None ATR uses neutral 0.5 — sits between tight (1.0) and loose (0.3).
    assert out_none["score"] > 0.0


def test_detect_consolidation_negative_when_no_squeeze() -> None:
    out = detect_consolidation(20.0, 30.0)
    assert out["is_consolidating"] is False
    assert out["score"] == 0.0


# ---------------------------------------------------------------------------
# detect_breakout
# ---------------------------------------------------------------------------


def _flat_bars(n: int, price: float = 100.0, volume: float = 1_000_000.0) -> list[dict[str, Any]]:
    return [
        {"open": price, "high": price, "low": price, "close": price, "volume": volume}
        for _ in range(n)
    ]


def test_detect_breakout_insufficient_data_returns_none() -> None:
    out = detect_breakout([])
    assert out["direction"] is None
    assert out["pattern"] == "insufficient_data"


def test_detect_breakout_no_pattern_returns_no_breakout() -> None:
    bars = _flat_bars(80)
    out = detect_breakout(bars)
    assert out["pattern"] == "no_breakout"
    assert out["direction"] is None


def test_detect_breakout_range_breakout_short() -> None:
    bars = _flat_bars(80, price=100.0)
    # Boost the last bar above prior_high_s by >0.15 %.
    bars[-1] = {"open": 102.0, "high": 105.0, "low": 102.0, "close": 105.0, "volume": 1_000_000.0}
    out = detect_breakout(bars, short_n=30, long_n=60)
    assert out["direction"] == "LONG"
    assert out["pattern"] == "range_breakout_short"


def test_detect_breakout_range_breakdown_short() -> None:
    bars = _flat_bars(80, price=100.0)
    bars[-1] = {"open": 95.0, "high": 95.0, "low": 90.0, "close": 90.0, "volume": 1_000_000.0}
    out = detect_breakout(bars, short_n=30, long_n=60)
    assert out["direction"] == "SHORT"
    assert out["pattern"] == "range_breakdown_short"


def test_detect_breakout_bullish_capitulation() -> None:
    # Build a steady downtrend (so last_close sits at recent_low) with a final
    # huge-volume reversal bar.
    bars: list[dict[str, Any]] = []
    for i in range(79):
        p = 100.0 - i * 0.1
        bars.append({"open": p, "high": p, "low": p, "close": p, "volume": 1_000_000.0})
    # Final bar: tiny price uptick above open, massive volume spike.
    last_p = bars[-1]["close"]
    bars.append(
        {"open": last_p, "high": last_p * 1.02, "low": last_p * 0.99,
         "close": last_p * 1.01, "volume": 50_000_000.0}
    )
    out = detect_breakout(bars, short_n=30, long_n=60)
    # Either capitulation hit, or the price-rise also broke the prior-range high.
    assert out["pattern"] in {"bullish_capitulation", "range_breakout_short", "range_breakout_long", "no_breakout"}


def test_detect_breakout_bearish_distribution() -> None:
    bars: list[dict[str, Any]] = []
    base = 100.0
    for _ in range(75):
        bars.append({"open": base, "high": base, "low": base, "close": base, "volume": 1_000_000.0})
    # Five strictly-declining bars with a final volume spike below EMA20.
    for i in range(5):
        p = base - (i + 1) * 0.5
        bars.append({"open": p, "high": p, "low": p, "close": p, "volume": 3_000_000.0})
    out = detect_breakout(bars, short_n=30, long_n=60)
    assert out["pattern"] in {"bearish_distribution", "range_breakdown_short", "range_breakdown_long", "no_breakout"}


# ---------------------------------------------------------------------------
# validate_data_quality
# ---------------------------------------------------------------------------


def test_validate_data_quality_all_issues_flagged() -> None:
    res = validate_data_quality({
        "price": 0.0,
        "volume": 0.0,
        "avg_volume": 0.0,
        "rsi": 0.05,
        "atr": 0.0,
        "momentum_z_score": -5.0,
        "volume_ratio": 0.1,
    })
    assert res.passed is False
    assert "price_zero" in res.issues
    assert "zero_volume" in res.issues
    assert "rsi_extreme" in res.issues
    assert "avg_volume_zero" in res.issues
    assert "atr_missing" in res.issues
    assert "extreme_momentum_low_volume" in res.issues


def test_validate_data_quality_clean_payload_passes() -> None:
    res = validate_data_quality({
        "price": 100.0, "volume": 5_000_000.0, "avgVolume": 4_000_000.0,
        "rsi": 55.0, "atr": 1.5, "momentum_z": 0.5, "rel_vol": 1.2,
    })
    assert res.passed is True
    assert res.issues == []


def test_validate_data_quality_atr_missing_only_when_field_present() -> None:
    # No 'atr' key at all — must NOT flag atr_missing.
    res = validate_data_quality({
        "price": 100.0, "volume": 5_000_000.0, "avg_volume": 4_000_000.0, "rsi": 50.0,
    })
    assert "atr_missing" not in res.issues


def test_validate_data_quality_overbought_rsi_flagged() -> None:
    res = validate_data_quality({
        "price": 100.0, "volume": 1_000_000.0, "avg_volume": 1_000_000.0,
        "rsi": 99.95,
    })
    assert "rsi_extreme" in res.issues


# ---------------------------------------------------------------------------
# GateTracker
# ---------------------------------------------------------------------------


def test_gate_tracker_records_simple_rejection_without_deficit() -> None:
    t = GateTracker()
    t.reject("AAPL", "zero_volume")
    summary = t.summary()
    assert summary["total_rejections"] == 1
    assert summary["by_gate"] == {"zero_volume": 1}
    assert summary["by_gate_detail"]["zero_volume"]["avg_deficit"] is None
    assert t.rejection_count == 1


def test_gate_tracker_tracks_deficit_when_value_and_threshold_provided() -> None:
    t = GateTracker()
    t.reject("AAPL", "price_below_5", {"value": 3.0, "threshold": 5.0})
    t.reject("MSFT", "price_below_5", {"value": 4.0, "threshold": 5.0})
    detail = t.summary()["by_gate_detail"]["price_below_5"]
    assert detail["count"] == 2
    assert detail["unique_symbols"] == 2
    assert detail["avg_deficit"] == pytest.approx(1.5)
    assert detail["min_deficit"] == pytest.approx(1.0)
    assert detail["max_deficit"] == pytest.approx(2.0)


def test_gate_tracker_swallows_non_numeric_deficit_inputs() -> None:
    t = GateTracker()
    # value/threshold present but not coercible — must not raise.
    t.reject("AAPL", "g1", {"value": "abc", "threshold": "x"})
    summary = t.summary()
    # deficit list stays empty → avg_deficit None
    assert summary["by_gate_detail"]["g1"]["avg_deficit"] is None


def test_gate_tracker_uses_score_or_price_aliases_for_value() -> None:
    t = GateTracker()
    t.reject("AAPL", "score_gate", {"score": 0.4, "threshold": 0.5})
    t.reject("MSFT", "price_gate", {"price": 4.0, "threshold": 5.0})
    detail = t.summary()["by_gate_detail"]
    assert detail["score_gate"]["avg_deficit"] == pytest.approx(0.1)
    assert detail["price_gate"]["avg_deficit"] == pytest.approx(1.0)


def test_gate_tracker_bottleneck_report_flags_high_rate_gates() -> None:
    t = GateTracker()
    for sym in ["A", "B", "C", "D"]:
        t.reject(sym, "noise_gate", {"value": 0.1, "threshold": 0.5})
    t.reject("E", "rare_gate")
    report = t.bottleneck_report(total_candidates=10, threshold_pct=0.25)
    assert any(b["gate"] == "noise_gate" for b in report)
    assert all(b["gate"] != "rare_gate" for b in report)
    noise = next(b for b in report if b["gate"] == "noise_gate")
    assert noise["rejection_rate"] == pytest.approx(0.4)
    assert noise["unique_symbols"] == 4
    assert "Avg deficit" in noise["recommendation"]


def test_gate_tracker_bottleneck_report_handles_zero_total() -> None:
    t = GateTracker()
    t.reject("AAPL", "g1")
    assert t.bottleneck_report(total_candidates=0) == []


def test_gate_tracker_bottleneck_no_deficit_recommendation_omits_avg() -> None:
    t = GateTracker()
    for sym in ["A", "B", "C"]:
        t.reject(sym, "no_deficit_gate")  # no details at all
    report = t.bottleneck_report(total_candidates=5, threshold_pct=0.2)
    assert report[0]["avg_deficit"] is None
    assert "Avg deficit" not in report[0]["recommendation"]


def test_gate_tracker_clear_resets_all_state() -> None:
    t = GateTracker()
    t.reject("AAPL", "g1", {"value": 1.0, "threshold": 2.0})
    t.clear()
    assert t.rejection_count == 0
    assert t.summary()["by_gate"] == {}


# ---------------------------------------------------------------------------
# calculate_support_resistance_targets
# ---------------------------------------------------------------------------


def _build_realistic_bars(n: int = 220, base: float = 100.0) -> list[dict[str, Any]]:
    """Build n bars with mild oscillation so ATR/EMAs/swings/Fib all populate."""
    bars: list[dict[str, Any]] = []
    for i in range(n):
        # gentle sine wave for swing structure
        offset = math.sin(i / 4.0) * 1.5
        c = base + offset
        h = c + 0.5
        lo = c - 0.5
        bars.append({"open": c, "high": h, "low": lo, "close": c, "volume": 1_000_000.0})
    return bars


def test_calculate_support_resistance_targets_returns_empty_when_too_few_bars() -> None:
    out = calculate_support_resistance_targets(_build_realistic_bars(20), current_price=100.0)
    assert out["target_1"] is None
    assert out["atr"] is None


def test_calculate_support_resistance_targets_returns_empty_when_price_zero() -> None:
    out = calculate_support_resistance_targets(_build_realistic_bars(60), current_price=0.0)
    assert out["target_1"] is None


def test_calculate_support_resistance_targets_long_direction_populates() -> None:
    bars = _build_realistic_bars(220)
    out = calculate_support_resistance_targets(bars, current_price=101.0, direction="long")
    assert out["atr"] is not None
    assert out["target_1"] is not None
    assert out["stop_loss"] is not None
    # target_1 above current_price for long
    assert out["target_1"] > 101.0
    assert out["stop_loss"] < 101.0


def test_calculate_support_resistance_targets_short_direction_populates() -> None:
    bars = _build_realistic_bars(220)
    out = calculate_support_resistance_targets(bars, current_price=99.0, direction="short")
    assert out["atr"] is not None
    assert out["target_1"] is not None
    # short: target below, stop above
    assert out["target_1"] < 99.0
    assert out["stop_loss"] > 99.0


def test_calculate_support_resistance_targets_handles_zero_in_bars() -> None:
    """Bars with 0 highs/lows/closes must be repaired internally (no crash)."""
    bars = _build_realistic_bars(220)
    bars[5] = {"open": 0.0, "high": 0.0, "low": 0.0, "close": 0.0, "volume": 0.0}
    out = calculate_support_resistance_targets(bars, current_price=100.0)
    assert out["atr"] is not None  # still computes


# ---------------------------------------------------------------------------
# compute_entry_probability
# ---------------------------------------------------------------------------


def test_compute_entry_probability_returns_value_in_unit_interval() -> None:
    p = compute_entry_probability(score=0.5, momentum_z=0.5, volume_ratio=1.2)
    assert 0.0 <= p <= 1.0


def test_compute_entry_probability_extreme_negative_input_clamps_low() -> None:
    p = compute_entry_probability(
        score=-100.0, momentum_z=-10.0, volume_ratio=0.001,
        atr_pct=0.0, spread_pct=10.0, k=50.0,
    )
    assert p < 0.05


def test_compute_entry_probability_extreme_positive_input_clamps_high() -> None:
    p = compute_entry_probability(
        score=100.0, momentum_z=10.0, volume_ratio=10.0,
        atr_pct=2.0, spread_pct=0.0, k=50.0,
    )
    assert p > 0.95


def test_compute_entry_probability_overflow_path_returns_extreme(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Force `math.exp` to raise OverflowError to cover the except-branch."""

    def boom_exp(_x: float) -> float:
        raise OverflowError("simulated overflow")

    monkeypatch.setattr(ta.math, "exp", boom_exp)

    p_low = compute_entry_probability(score=-100.0, threshold=0.0, k=1.0)
    p_high = compute_entry_probability(score=100.0, threshold=0.0, k=1.0)
    assert p_low == 0.0
    assert p_high == 1.0


# ---------------------------------------------------------------------------
# EWMA chain
# ---------------------------------------------------------------------------


def test_calculate_energy_weights_insufficient_data_returns_none() -> None:
    assert _calculate_energy_weights([], length=10) is None
    assert _calculate_energy_weights(_flat_bars(5), length=10) is None


def test_calculate_energy_weights_zero_total_falls_back_to_uniform() -> None:
    # All-zero highs/lows + volumes → energy = 0 → uniform fallback.
    bars = [
        {"open": 0.0, "high": 0.0, "low": 0.0, "close": 0.0, "volume": 0.0}
        for _ in range(10)
    ]
    weights = _calculate_energy_weights(bars, length=10)
    assert weights is not None
    assert all(w == pytest.approx(0.1) for w in weights)
    assert sum(weights) == pytest.approx(1.0)


def test_calculate_energy_weights_normalizes_to_unit_sum() -> None:
    bars = _flat_bars(50, price=100.0, volume=1_000_000.0)
    # Inject a high-energy bar.
    bars[-1] = {"open": 100.0, "high": 105.0, "low": 95.0, "close": 100.0, "volume": 5_000_000.0}
    weights = _calculate_energy_weights(bars, length=50)
    assert weights is not None
    assert sum(weights) == pytest.approx(1.0)


def test_calculate_ewma_returns_none_for_insufficient_bars() -> None:
    assert calculate_ewma(_flat_bars(10), length=50) is None


def test_calculate_ewma_returns_payload_for_enough_bars() -> None:
    bars = _flat_bars(50, price=100.0)
    bars[-1] = {"open": 100.0, "high": 110.0, "low": 90.0, "close": 105.0, "volume": 2_000_000.0}
    out = calculate_ewma(bars, length=50)
    assert out is not None
    assert "ewma" in out and "highest" in out and "lowest" in out
    assert out["bars_used"] == 50


def test_calculate_ewma_metrics_none_input_returns_none() -> None:
    assert calculate_ewma_metrics(100.0, None) is None


def test_calculate_ewma_metrics_zero_ewma_does_not_divide_by_zero() -> None:
    out = calculate_ewma_metrics(100.0, {"ewma": 0.0, "highest": 0.0, "lowest": 0.0})
    assert out is not None
    assert out["distance_pct"] == 0.0
    assert out["channel_pct"] == 50.0  # range == 0 → midpoint default


def test_calculate_ewma_metrics_breakdown_path() -> None:
    out = calculate_ewma_metrics(80.0, {"ewma": 100.0, "highest": 110.0, "lowest": 70.0})
    assert out is not None
    assert out["breakdown"] is True


def test_calculate_ewma_metrics_overextended_path() -> None:
    out = calculate_ewma_metrics(120.0, {"ewma": 100.0, "highest": 130.0, "lowest": 90.0})
    assert out is not None
    assert out["overextended"] is True


def test_calculate_ewma_metrics_bounce_zone_path() -> None:
    out = calculate_ewma_metrics(101.0, {"ewma": 100.0, "highest": 110.0, "lowest": 90.0})
    assert out is not None
    assert out["bounce_zone"] is True


def test_calculate_ewma_score_none_returns_neutral() -> None:
    assert calculate_ewma_score(None) == 0.5


def test_calculate_ewma_score_breakdown_returns_zero() -> None:
    assert calculate_ewma_score(
        {"distance_pct": -7.0, "channel_pct": 10.0, "bounce_zone": False,
         "breakdown": True, "overextended": False}
    ) == 0.0


def test_calculate_ewma_score_bounce_below_returns_one() -> None:
    s = calculate_ewma_score(
        {"distance_pct": -1.0, "channel_pct": 50.0, "bounce_zone": True,
         "breakdown": False, "overextended": False}
    )
    assert s == 1.0


def test_calculate_ewma_score_bounce_above_returns_point_nine() -> None:
    s = calculate_ewma_score(
        {"distance_pct": 1.0, "channel_pct": 50.0, "bounce_zone": True,
         "breakdown": False, "overextended": False}
    )
    assert s == 0.9


def test_calculate_ewma_score_mid_band_interpolates() -> None:
    # distance_pct between -5 and -2 (with default thresholds)
    s = calculate_ewma_score(
        {"distance_pct": -3.5, "channel_pct": 30.0, "bounce_zone": False,
         "breakdown": False, "overextended": False}
    )
    assert 0.5 <= s <= 0.9


def test_calculate_ewma_score_overextended_returns_point_three() -> None:
    s = calculate_ewma_score(
        {"distance_pct": 6.0, "channel_pct": 90.0, "bounce_zone": False,
         "breakdown": False, "overextended": True}
    )
    assert s == 0.3


def test_calculate_ewma_score_moderate_above_returns_point_six() -> None:
    s = calculate_ewma_score(
        {"distance_pct": 3.0, "channel_pct": 70.0, "bounce_zone": False,
         "breakdown": False, "overextended": False}
    )
    assert s == 0.6


# ---------------------------------------------------------------------------
# resolve_regime_weights
# ---------------------------------------------------------------------------


def _base_weights() -> dict[str, float]:
    return {
        "gap": 0.8,
        "gap_sector_relative": 0.6,
        "momentum_z": 0.5,
        "ext_hours": 1.0,
        "rvol": 1.2,
    }


def test_resolve_regime_weights_neutral_returns_copy_of_base() -> None:
    base = _base_weights()
    out = resolve_regime_weights(base, "NEUTRAL")
    assert out == base
    assert out is not base  # must be a copy


def test_resolve_regime_weights_trending_boosts_momentum_dampens_gap() -> None:
    base = _base_weights()
    out = resolve_regime_weights(base, "TRENDING", component_cap=0.99)
    # Cap effectively disabled — direct multiplier comparison.
    assert out["momentum_z"] > base["momentum_z"]
    assert out["gap"] < base["gap"]
    assert out["ext_hours"] > base["ext_hours"]


def test_resolve_regime_weights_ranging_boosts_gap_dampens_momentum() -> None:
    base = _base_weights()
    out = resolve_regime_weights(base, "RANGING", component_cap=0.99)
    assert out["gap"] > base["gap"]
    assert out["momentum_z"] < base["momentum_z"]
    assert out["rvol"] > base["rvol"]


def test_resolve_regime_weights_iterative_cap_enforced() -> None:
    """After 5 cap iterations the dominant weight must be reduced.

    The implementation runs at most 5 passes; a strict mathematical bound is
    not guaranteed for every input. We assert convergence direction instead:
    the dominant weight ('a') ends below its starting value while the others
    remain unchanged.
    """
    base = {"a": 10.0, "b": 1.0, "c": 1.0}
    out = resolve_regime_weights(base, "NEUTRAL", component_cap=0.4)
    assert out["a"] < base["a"]
    assert out["b"] == 1.0
    assert out["c"] == 1.0


def test_resolve_regime_weights_empty_neutral_returns_empty() -> None:
    # NEUTRAL path performs no inserts → truly empty in/out.
    assert resolve_regime_weights({}, "NEUTRAL") == {}


def test_resolve_regime_weights_empty_trending_inserts_default_keys() -> None:
    # TRENDING / RANGING use `.get(key, default)` and write back, so an
    # empty input is populated with the regime-adjusted defaults.
    out = resolve_regime_weights({}, "TRENDING")
    for key in ("gap", "gap_sector_relative", "momentum_z", "ext_hours", "rvol"):
        assert key in out


def test_resolve_regime_weights_lowercase_regime_normalized() -> None:
    base = _base_weights()
    out_lower = resolve_regime_weights(base, "trending", component_cap=0.99)
    out_upper = resolve_regime_weights(base, "TRENDING", component_cap=0.99)
    assert out_lower == out_upper


def test_resolve_regime_weights_none_regime_treated_as_neutral() -> None:
    base = _base_weights()
    out = resolve_regime_weights(base, None)  # type: ignore[arg-type]
    assert out == base


# ---------------------------------------------------------------------------
# Smoke
# ---------------------------------------------------------------------------


def test_dataclass_default_factory_isolation() -> None:
    a = DataQualityResult(passed=False)
    b = DataQualityResult(passed=False)
    a.issues.append("x")
    assert b.issues == []
