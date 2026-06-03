"""Tests for the ADR-0019 clean-room momentum-ribbon v2 candidate features."""

from __future__ import annotations

import math

import pytest

from governance.family_momentum_ribbon_v2 import (
    DEFAULT_RIBBON_LENGTHS,
    DEFAULT_SMOOTH_PERIOD,
    MOMENTUM_RIBBON_SOURCE,
    _cutler_rsi_at,
    ribbon_stack_score_at,
    ribbon_stack_state_at,
    ribbon_values_at,
    usi_at,
)


def _bars(closes: list[float]) -> list[dict[str, float]]:
    return [{"close": c} for c in closes]


def _sine_bars(amp: float, period: int, n: int) -> list[dict[str, float]]:
    return _bars([100.0 + amp * math.sin(2.0 * math.pi * i / period) for i in range(n)])


def _down_then_up_tail() -> list[dict[str, float]]:
    # 60 bars strictly down, then a 10-bar pure up thrust. The recent thrust
    # pins the short RSI lines high while the long lines still carry the older
    # decline -> a strongly positive ribbon spread (short above long).
    c = [300.0]
    for _ in range(60):
        c.append(c[-1] - 1.0)
    for _ in range(10):
        c.append(c[-1] + 2.0)
    return _bars(c)


def _up_then_down_tail() -> list[dict[str, float]]:
    c = [100.0]
    for _ in range(60):
        c.append(c[-1] + 1.0)
    for _ in range(10):
        c.append(c[-1] - 2.0)
    return _bars(c)


# --------------------------------------------------------------------------- #
# _cutler_rsi_at                                                              #
# --------------------------------------------------------------------------- #
def test_rsi_all_gains_is_100() -> None:
    closes = [float(i) for i in range(20)]  # strictly rising
    assert _cutler_rsi_at(closes, 19, 14) == pytest.approx(100.0)


def test_rsi_all_losses_is_0() -> None:
    closes = [float(20 - i) for i in range(20)]  # strictly falling
    assert _cutler_rsi_at(closes, 19, 14) == pytest.approx(0.0)


def test_rsi_flat_window_is_neutral_50() -> None:
    closes = [5.0] * 20
    assert _cutler_rsi_at(closes, 19, 14) == pytest.approx(50.0)


def test_rsi_symmetric_alternating_is_50() -> None:
    # Equal up and down moves -> avg_gain == avg_loss -> RSI 50.
    closes = [10.0, 11.0, 10.0, 11.0, 10.0, 11.0, 10.0, 11.0, 10.0]
    assert _cutler_rsi_at(closes, 8, 4) == pytest.approx(50.0)


def test_rsi_none_for_insufficient_history() -> None:
    assert _cutler_rsi_at([1.0, 2.0, 3.0], 2, 14) is None


def test_rsi_is_strictly_backward_looking() -> None:
    # Mutating bars AFTER the anchor must not change the value.
    closes = [float(i) for i in range(30)]
    base = _cutler_rsi_at(closes, 15, 14)
    closes[16] = -999.0
    assert _cutler_rsi_at(closes, 15, 14) == base


# --------------------------------------------------------------------------- #
# usi_at                                                                      #
# --------------------------------------------------------------------------- #
def test_usi_equals_rsi_when_smoothing_disabled() -> None:
    closes = [float(i) * 1.3 for i in range(40)]
    rsi = _cutler_rsi_at(closes, 30, 14)
    usi = usi_at(closes, 30, rsi_period=14, smooth_period=1)
    assert usi == pytest.approx(rsi)


def test_usi_none_for_insufficient_history() -> None:
    closes = [float(i) for i in range(15)]
    # needs rsi_period + smooth_period - 1 = 14 + 3 - 1 = 16 history.
    assert usi_at(closes, 14, rsi_period=14, smooth_period=3) is None


def test_usi_in_valid_rsi_range() -> None:
    closes = [float(i % 7) + i * 0.01 for i in range(60)]
    usi = usi_at(closes, 50, rsi_period=14, smooth_period=3)
    assert usi is not None
    assert 0.0 <= usi <= 100.0


def test_usi_rejects_non_positive_periods() -> None:
    closes = [float(i) for i in range(40)]
    assert usi_at(closes, 30, rsi_period=0, smooth_period=3) is None
    assert usi_at(closes, 30, rsi_period=14, smooth_period=0) is None


# --------------------------------------------------------------------------- #
# ribbon_values_at                                                            #
# --------------------------------------------------------------------------- #
def test_ribbon_values_length_matches_lengths() -> None:
    bars = _bars([float(i) * 0.5 + (i % 5) for i in range(80)])
    values = ribbon_values_at(bars, 70)
    assert values is not None
    assert len(values) == len(DEFAULT_RIBBON_LENGTHS)


def test_ribbon_values_none_for_short_history() -> None:
    bars = _bars([float(i) for i in range(10)])
    assert ribbon_values_at(bars, 9) is None


def test_ribbon_values_none_on_missing_close() -> None:
    closes = [float(i) for i in range(80)]
    bars: list[dict[str, float | None]] = [{"close": c} for c in closes]
    bars[60] = {"close": None}  # inside the window for anchor 70
    assert ribbon_values_at(bars, 70) is None


def test_ribbon_values_none_for_empty_or_bad_lengths() -> None:
    bars = _bars([float(i) for i in range(80)])
    assert ribbon_values_at(bars, 70, lengths=()) is None
    assert ribbon_values_at(bars, 70, lengths=(5, 0, 7)) is None


def test_ribbon_values_strictly_backward_looking() -> None:
    closes = [float(i) * 0.4 + (i % 3) for i in range(90)]
    bars = _bars(closes)
    base = ribbon_values_at(bars, 70)
    mutated = _bars(closes[:71] + [-1000.0] * (len(closes) - 71))
    assert ribbon_values_at(mutated, 70) == base


# --------------------------------------------------------------------------- #
# ribbon_stack_state_at                                                       #
# --------------------------------------------------------------------------- #
def test_stack_state_plus_one_on_recent_momentum_surge() -> None:
    # Anchor placed where the most recent up-swing makes the faster lines sit
    # strictly above the slower ones (clean bull stack).
    bars = _sine_bars(amp=0.5, period=16, n=160)
    assert ribbon_stack_state_at(bars, 50) == 1


def test_stack_state_minus_one_on_recent_momentum_fade() -> None:
    bars = _sine_bars(amp=0.5, period=20, n=160)
    assert ribbon_stack_state_at(bars, 109) == -1


def test_stack_state_zero_for_saturated_linear_ramp() -> None:
    # An honest property: a perfectly linear ramp has zero losses, so every RSI
    # length saturates to 100, the ribbon is flat, and the state is mixed (0).
    bars = _bars([100.0 + i * 1.5 for i in range(80)])
    assert ribbon_stack_state_at(bars, 70) == 0


def test_stack_state_none_for_short_history() -> None:
    bars = _bars([float(i) for i in range(10)])
    assert ribbon_stack_state_at(bars, 9) is None


def test_stack_state_in_allowed_set() -> None:
    bars = _bars([float(i % 11) * 2.0 for i in range(90)])
    state = ribbon_stack_state_at(bars, 80)
    assert state in (-1, 0, 1)


# --------------------------------------------------------------------------- #
# ribbon_stack_score_at                                                       #
# --------------------------------------------------------------------------- #
def test_stack_score_positive_on_recent_up_thrust() -> None:
    bars = _down_then_up_tail()
    score = ribbon_stack_score_at(bars, len(bars) - 1)
    assert score is not None
    assert score > 0.0


def test_stack_score_negative_on_recent_down_thrust() -> None:
    bars = _up_then_down_tail()
    score = ribbon_stack_score_at(bars, len(bars) - 1)
    assert score is not None
    assert score < 0.0


def test_stack_score_sign_agrees_with_state_when_stacked() -> None:
    # +1 state must carry a positive spread; -1 state a negative one.
    bull = _sine_bars(amp=0.5, period=16, n=160)
    assert ribbon_stack_state_at(bull, 50) == 1
    bull_score = ribbon_stack_score_at(bull, 50)
    assert bull_score is not None and bull_score > 0.0

    bear = _sine_bars(amp=0.5, period=20, n=160)
    assert ribbon_stack_state_at(bear, 109) == -1
    bear_score = ribbon_stack_score_at(bear, 109)
    assert bear_score is not None and bear_score < 0.0


def test_stack_score_none_for_single_line() -> None:
    bars = _bars([float(i) for i in range(80)])
    assert ribbon_stack_score_at(bars, 70, lengths=(5,)) is None


def test_stack_score_none_for_short_history() -> None:
    bars = _bars([float(i) for i in range(10)])
    assert ribbon_stack_score_at(bars, 9) is None


def test_stack_score_does_not_telescope() -> None:
    # All-pairs mean must reflect interior order, not just the endpoints. Build
    # a ribbon whose first and last USI are near-equal but the interior is
    # ordered, and assert the score is non-trivial there.
    bars = _bars([50.0 + 10.0 * (i % 9) - i * 0.02 for i in range(120)])
    values = ribbon_values_at(bars, 100)
    score = ribbon_stack_score_at(bars, 100)
    assert values is not None and score is not None
    endpoints_only = (values[0] - values[-1]) / (len(values) - 1)
    # The two coincide only when the interior is perfectly linear; on this
    # irregular series they must differ.
    assert score != pytest.approx(endpoints_only)


# --------------------------------------------------------------------------- #
# provenance / defaults                                                       #
# --------------------------------------------------------------------------- #
def test_source_tag_is_versioned_v2() -> None:
    assert MOMENTUM_RIBBON_SOURCE.endswith("_v2")


def test_default_lengths_are_sorted_ascending() -> None:
    assert list(DEFAULT_RIBBON_LENGTHS) == sorted(DEFAULT_RIBBON_LENGTHS)
    assert DEFAULT_SMOOTH_PERIOD >= 1
