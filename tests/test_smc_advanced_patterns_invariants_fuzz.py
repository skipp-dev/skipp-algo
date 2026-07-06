"""Property-based invariants for SMC advanced pattern detectors.

These tests fuzz HVBDetector, PPDDClassifier, LiquidityClusterDetector and
BrokenFractalDetector with random / adversarial inputs. The goal is to find
silent crashes, NaN propagation, or undefined ordering that would break the
live daemon/backtester.
"""

from __future__ import annotations

import math

import hypothesis.strategies as st
import pytest
from hypothesis import given, settings

from services.live_overlay_daemon import smc_advanced_patterns as ap

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _all_finite(*values: float) -> bool:
    return all(math.isfinite(v) for v in values)


# ---------------------------------------------------------------------------
# HVBDetector invariants
# ---------------------------------------------------------------------------


@settings(max_examples=1000)
@given(
    bar_index=st.integers(),
    volume=st.one_of(st.integers(), st.floats(allow_nan=True, allow_infinity=True)),
    close=st.floats(allow_nan=True, allow_infinity=True),
    open_=st.floats(allow_nan=True, allow_infinity=True),
    high=st.floats(allow_nan=True, allow_infinity=True),
    low=st.floats(allow_nan=True, allow_infinity=True),
)
def test_hvb_detector_never_crashes(bar_index, volume, close, open_, high, low) -> None:
    detector = ap.HVBDetector(lookback=5, hvb_threshold=1.5)
    detector.detect(bar_index, volume, close, open_, high, low)


@settings(max_examples=500)
@given(
    bar_index=st.integers(),
    volume=st.integers(min_value=-1_000_000, max_value=1_000_000),
    close=st.floats(allow_nan=False, allow_infinity=False),
    open_=st.floats(allow_nan=False, allow_infinity=False),
    high=st.floats(allow_nan=False, allow_infinity=False),
    low=st.floats(allow_nan=False, allow_infinity=False),
)
def test_hvb_detector_output_fields_are_finite_when_input_is_finite(
    bar_index, volume, close, open_, high, low
) -> None:
    detector = ap.HVBDetector(lookback=5, hvb_threshold=1.5)
    for _ in range(10):
        result = detector.detect(bar_index, volume, close, open_, high, low)
    assert math.isfinite(result.volume)
    assert result.volume >= 0
    assert math.isfinite(result.avg_volume)
    assert math.isfinite(result.volume_ratio)


@settings(max_examples=200)
@given(lookback=st.integers(min_value=-100, max_value=0))
def test_hvb_detector_rejects_non_positive_lookback(lookback: int) -> None:
    with pytest.raises(ValueError):
        ap.HVBDetector(lookback=lookback)


# ---------------------------------------------------------------------------
# PPDDClassifier invariants
# ---------------------------------------------------------------------------


@settings(max_examples=1000)
@given(
    ob_top=st.floats(allow_nan=True, allow_infinity=True),
    ob_bottom=st.floats(allow_nan=True, allow_infinity=True),
    direction=st.sampled_from(["bullish", "bearish", "unknown"]),
    current_price=st.floats(allow_nan=True, allow_infinity=True),
    atr=st.floats(allow_nan=True, allow_infinity=True),
    hvb_present=st.booleans(),
)
def test_ppdd_classifier_never_crashes(
    ob_top, ob_bottom, direction, current_price, atr, hvb_present
) -> None:
    classifier = ap.PPDDClassifier(atr_multiple=2.0)
    try:
        classifier.classify(ob_top, ob_bottom, direction, current_price, atr, hvb_present)
    except ValueError:
        pass  # Non-finite inputs raise by design.


@settings(max_examples=500)
@given(
    ob_top=st.floats(min_value=1.0, max_value=1000.0, allow_nan=False, allow_infinity=False),
    ob_bottom=st.floats(min_value=1.0, max_value=1000.0, allow_nan=False, allow_infinity=False),
    direction=st.sampled_from(["bullish", "bearish"]),
    current_price=st.floats(min_value=1.0, max_value=1000.0, allow_nan=False, allow_infinity=False),
    atr=st.floats(min_value=0.01, max_value=100.0, allow_nan=False, allow_infinity=False),
)
def test_ppdd_classifier_finite_inputs_produce_finite_block(
    ob_top, ob_bottom, direction, current_price, atr
) -> None:
    classifier = ap.PPDDClassifier(atr_multiple=2.0)
    block = classifier.classify(ob_top, ob_bottom, direction, current_price, atr)
    assert math.isfinite(block.strength)
    assert 0.0 <= block.strength <= 1.0
    assert block.is_premium != block.is_discount


# ---------------------------------------------------------------------------
# LiquidityClusterDetector invariants
# ---------------------------------------------------------------------------


@settings(max_examples=1000)
@given(
    swing_highs=st.lists(
        st.floats(allow_nan=True, allow_infinity=True),
        min_size=0,
        max_size=30,
    ),
    swing_lows=st.lists(
        st.floats(allow_nan=True, allow_infinity=True),
        min_size=0,
        max_size=30,
    ),
    current_price=st.floats(allow_nan=True, allow_infinity=True),
    atr=st.floats(allow_nan=True, allow_infinity=True),
)
def test_liquidity_cluster_detector_never_crashes(
    swing_highs, swing_lows, current_price, atr
) -> None:
    detector = ap.LiquidityClusterDetector(cluster_distance_atr=0.5, min_confluences=2)
    detector.detect_clusters(swing_highs, swing_lows, current_price, atr)


@settings(max_examples=500)
@given(
    swing_highs=st.lists(
        st.floats(min_value=1.0, max_value=1000.0, allow_nan=False, allow_infinity=False),
        min_size=0,
        max_size=30,
    ),
    swing_lows=st.lists(
        st.floats(min_value=1.0, max_value=1000.0, allow_nan=False, allow_infinity=False),
        min_size=0,
        max_size=30,
    ),
    current_price=st.floats(min_value=1.0, max_value=1000.0, allow_nan=False, allow_infinity=False),
    atr=st.floats(min_value=0.01, max_value=100.0, allow_nan=False, allow_infinity=False),
)
def test_liquidity_cluster_zones_are_ordered(
    swing_highs, swing_lows, current_price, atr
) -> None:
    detector = ap.LiquidityClusterDetector(cluster_distance_atr=0.5, min_confluences=2)
    clusters = detector.detect_clusters(swing_highs, swing_lows, current_price, atr)
    for c in clusters:
        assert math.isfinite(c.zone_top)
        assert math.isfinite(c.zone_bottom)
        assert c.zone_top >= c.zone_bottom
        assert c.cluster_count >= detector.min_confluences


@settings(max_examples=500)
@given(
    prices=st.lists(
        st.floats(allow_nan=True, allow_infinity=True),
        min_size=1,
        max_size=30,
    )
)
def test_cluster_prices_handles_nan_without_crashing(prices: list[float]) -> None:
    detector = ap.LiquidityClusterDetector(cluster_distance_atr=0.5, min_confluences=2)
    detector._cluster_prices(prices, distance=1.0)


# ---------------------------------------------------------------------------
# BrokenFractalDetector invariants
# ---------------------------------------------------------------------------


@settings(max_examples=1000)
@given(
    bar_index=st.integers(),
    high=st.floats(allow_nan=True, allow_infinity=True),
    low=st.floats(allow_nan=True, allow_infinity=True),
    close=st.floats(allow_nan=True, allow_infinity=True),
)
def test_broken_fractal_detector_never_crashes(bar_index, high, low, close) -> None:
    detector = ap.BrokenFractalDetector()
    detector.detect(bar_index, high, low, close)


@settings(max_examples=500)
@given(
    bar_index=st.integers(),
    high=st.floats(min_value=1.0, max_value=1000.0, allow_nan=False, allow_infinity=False),
    low=st.floats(min_value=1.0, max_value=1000.0, allow_nan=False, allow_infinity=False),
    close=st.floats(min_value=1.0, max_value=1000.0, allow_nan=False, allow_infinity=False),
)
def test_broken_fractal_detector_history_is_bounded(bar_index, high, low, close) -> None:
    detector = ap.BrokenFractalDetector()
    for i in range(100):
        detector.detect(i, high, low, close)
    assert len(detector.fractal_history) <= detector.MAX_FRACTAL_HISTORY


# ---------------------------------------------------------------------------
# Cross-detector determinism
# ---------------------------------------------------------------------------


@settings(max_examples=200)
@given(
    inputs=st.lists(
        st.tuples(
            st.integers(min_value=0),
            st.floats(allow_nan=True, allow_infinity=True),
            st.floats(allow_nan=True, allow_infinity=True),
            st.floats(allow_nan=True, allow_infinity=True),
            st.floats(allow_nan=True, allow_infinity=True),
            st.integers(min_value=0),
        ),
        min_size=5,
        max_size=50,
    )
)
def test_smcsignal_detector_never_crashes_on_random_candles(inputs) -> None:
    from services.live_overlay_daemon.smc_signal_detector import Candle, SmcSignalDetector

    detector = SmcSignalDetector(max_boxes_per_direction=10)
    for bar_index, open_, high, low, close, volume in inputs:
        candle = Candle(
            bar_index=bar_index,
            open=open_,
            high=high,
            low=low,
            close=close,
            volume=volume,
        )
        detector.process_candle(candle)


@settings(max_examples=200)
@given(
    inputs=st.lists(
        st.tuples(
            st.integers(min_value=0),
            st.floats(min_value=1.0, max_value=1000.0, allow_nan=False, allow_infinity=False),
            st.floats(min_value=1.0, max_value=1000.0, allow_nan=False, allow_infinity=False),
            st.floats(min_value=1.0, max_value=1000.0, allow_nan=False, allow_infinity=False),
            st.floats(min_value=1.0, max_value=1000.0, allow_nan=False, allow_infinity=False),
            st.integers(min_value=0),
        ),
        min_size=5,
        max_size=50,
    )
)
def test_smcsignal_detector_boxes_are_ordered_and_finite(inputs) -> None:
    from services.live_overlay_daemon.smc_signal_detector import Candle, SmcSignalDetector

    detector = SmcSignalDetector(max_boxes_per_direction=10)
    for bar_index, open_, high, low, close, volume in inputs:
        candle = Candle(
            bar_index=bar_index,
            open=open_,
            high=high,
            low=low,
            close=close,
            volume=volume,
        )
        detector.process_candle(candle)

    for box in detector.get_active_structures():
        assert math.isfinite(box.top)
        assert math.isfinite(box.bottom)
        assert box.top >= box.bottom
