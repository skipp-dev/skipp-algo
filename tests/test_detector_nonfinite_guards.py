"""Non-finite / corrupt-input guards for the SMC/ensemble detector cluster.

These detectors are reachable only via the offline ensemble backtester (the
live path coerces OHLC upstream), but the backtester feeds raw historical
OHLC without finite-coercion, so a corrupt bar (NaN/±inf, or an inverted
high<low producing a negative range) can reach them. A corrupt input must not
produce an actively-wrong signal or permanently poison rolling state.
"""

from __future__ import annotations

import math

import pytest

from services.live_overlay_daemon.strong_impulse_detector import (
    IgnitionCandle,
    ImpulsePhase,
    ImpulseSignal,
    InvalidationLevelCalculator,
    PropulsionStrengthScorer,
    StrongImpulseDetector,
)
from services.live_overlay_daemon.triple_confluence_navigator import MarketStructure
from services.live_overlay_daemon.volatility_filter import VolatilityFilter


class TestVolatilityFilterCalculateAtrGuards:
    """calculate_atr must not let a corrupt bar poison atr_history (a NaN
    propagates through Wilder smoothing forever; a negative range corrupts the
    ratio)."""

    def _warm(self) -> VolatilityFilter:
        f = VolatilityFilter(atr_period=3, sma_period=5)
        for _ in range(5):
            f.calculate_atr(high=101.0, low=99.0, close=100.0)
        return f

    def test_non_finite_high_does_not_poison_history(self):
        f = self._warm()
        f.calculate_atr(high=float("inf"), low=99.0, close=100.0)
        f.calculate_atr(high=float("nan"), low=99.0, close=100.0)
        assert all(math.isfinite(x) for x in f.atr_history)
        # A subsequent clean bar still yields a finite ratio.
        f.calculate_atr(high=101.0, low=99.0, close=100.0)
        assert math.isfinite(f.get_atr_ratio())

    def test_inverted_bar_does_not_append_negative_range(self):
        f = self._warm()
        f.calculate_atr(high=98.0, low=100.0, close=99.0)  # high < low
        assert all(x >= 0 for x in f.atr_history)

    def test_non_finite_close_not_carried_to_next_bar(self):
        f = self._warm()
        f.calculate_atr(high=101.0, low=99.0, close=float("inf"))
        # Next bar's TR must stay finite despite the prior non-finite close.
        f.calculate_atr(high=101.0, low=99.0, close=100.0)
        assert all(math.isfinite(x) for x in f.atr_history)


class TestPropulsionStrengthScorerGuards:
    """min(2.0, NaN) == 2.0 in Python: a non-finite momentum/volume input must
    not silently award the maximum factor score."""

    def _ignition(self) -> IgnitionCandle:
        return IgnitionCandle(
            bar_index=0, open=100.0, high=110.0, low=99.0, close=109.0,
            body_size=9.0, range=11.0, direction="bullish",
        )

    def test_nan_momentum_and_volume_coerce_to_neutral(self):
        scorer = PropulsionStrengthScorer()
        ig = self._ignition()
        corrupt = scorer.calculate(
            ignition=ig, atr=2.0, recent_momentum=float("nan"), volume_ratio=float("nan")
        )
        neutral = scorer.calculate(
            ignition=ig, atr=2.0, recent_momentum=0.0, volume_ratio=1.0
        )
        assert math.isfinite(corrupt.total_strength)
        # NaN must produce the neutral (no-boost) score, not +4.0 of max score.
        assert corrupt.total_strength == neutral.total_strength

    def test_inf_inputs_do_not_maximize_strength(self):
        scorer = PropulsionStrengthScorer()
        ig = self._ignition()
        p = scorer.calculate(
            ignition=ig, atr=2.0, recent_momentum=float("inf"), volume_ratio=float("inf")
        )
        assert math.isfinite(p.total_strength)


class TestMarketStructureNonFiniteGuard:
    """A non-finite high/low must not emit a spurious break-of-structure vote
    or poison the persisted pivots."""

    def test_inf_high_is_structurally_neutral(self):
        ms = MarketStructure()
        sig = ms.update(high=float("inf"), low=99.0, pivot_high_prev=105.0, pivot_low_prev=95.0)
        assert sig == "neutral"
        assert ms.break_of_structure is False
        assert math.isfinite(ms.pivot_high)

    def test_nan_low_is_structurally_neutral(self):
        ms = MarketStructure()
        sig = ms.update(high=101.0, low=float("nan"), pivot_high_prev=105.0, pivot_low_prev=95.0)
        assert sig == "neutral"
        assert math.isfinite(ms.pivot_low)

    def test_finite_break_still_detected(self):
        ms = MarketStructure()
        sig = ms.update(high=106.0, low=99.0, pivot_high_prev=105.0, pivot_low_prev=95.0)
        assert sig == "bullish"
        assert ms.break_of_structure is True


class TestInvalidationLevelCalculatorGuards:
    """A corrupt ATR must not flip the invalidation to the wrong side of price
    or make it non-finite. This path IS reachable: ignition detection is
    atr-independent and propulsion can clear the threshold from its other
    factors, and the backtester defaults atr to (high-low)*1.5 — negative for
    an inverted high<low bar."""

    def _ignition(self) -> IgnitionCandle:
        return IgnitionCandle(
            bar_index=0, open=100.0, high=105.0, low=95.0, close=104.0,
            body_size=4.0, range=10.0, direction="bullish",
        )

    def test_negative_atr_keeps_long_invalidation_below_low(self):
        calc = InvalidationLevelCalculator()
        ig = self._ignition()
        inv = calc.calculate_invalidation(ig, "long", atr=-2.0)
        # A negative ATR previously produced low + |atr|*0.5 (above the low).
        assert inv <= ig.low
        assert math.isfinite(inv)

    def test_negative_atr_keeps_short_invalidation_above_high(self):
        calc = InvalidationLevelCalculator()
        ig = self._ignition()
        inv = calc.calculate_invalidation(ig, "short", atr=-2.0)
        assert inv >= ig.high
        assert math.isfinite(inv)

    def test_non_finite_atr_yields_finite_invalidation(self):
        calc = InvalidationLevelCalculator()
        ig = self._ignition()
        for bad in (float("nan"), float("inf"), float("-inf")):
            assert math.isfinite(calc.calculate_invalidation(ig, "long", atr=bad))
            assert math.isfinite(calc.calculate_invalidation(ig, "short", atr=bad))

    def test_positive_atr_still_applies_half_atr_buffer(self):
        calc = InvalidationLevelCalculator()
        ig = self._ignition()
        assert calc.calculate_invalidation(ig, "long", atr=2.0) == ig.low - 1.0
        assert calc.calculate_invalidation(ig, "short", atr=2.0) == ig.high + 1.0


class TestStrongImpulseDetectorBoundaryGuards:
    """update_phase must never store a negative confirmation count, and
    detect_impulse must not emit a signal on non-finite / non-positive ATR
    (the ATR-displacement factor would silently zero while other factors clear
    the threshold, on top of a zero-buffer stop)."""

    def _armed_signal(self) -> ImpulseSignal:
        return ImpulseSignal(
            bar_index=10, phase=ImpulsePhase.IGNITION, direction="long",
            ignition_bar=10, propulsion_strength=7.0, entry_price=100.0,
            invalidation_level=99.0, target_1=101.0, target_2=102.0,
            target_3=103.0, confirmation_bars=0,
        )

    def test_out_of_order_bar_is_skipped_not_advanced(self):
        det = StrongImpulseDetector()
        signal = self._armed_signal()
        det.active_impulses[10] = signal
        # A backward (out-of-order) bar confirms nothing: it must be skipped, not
        # returned with a `max(0, …)`-clamped confirmation_bars.
        out = det.update_phase(bar_index=5, high=101.0, low=99.0, close=100.0)
        assert out == []
        # The signal's own state is left untouched.
        assert signal.phase == ImpulsePhase.IGNITION
        assert signal.confirmation_bars == 0

    @pytest.mark.parametrize(
        "bad_atr", [-5.0, 0.0, float("nan"), float("inf"), float("-inf")]
    )
    def test_non_finite_or_nonpositive_atr_emits_no_signal(self, bad_atr):
        det = StrongImpulseDetector(propulsion_threshold=6.0)
        # A strong bar whose non-ATR factors alone clear the threshold.
        sig = det.detect_impulse(
            bar_index=3, open=100.0, high=110.0, low=99.0, close=109.5,
            atr=bad_atr, recent_momentum=1.0, volume_ratio=3.0,
        )
        assert sig is None
