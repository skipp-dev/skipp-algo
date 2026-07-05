"""Regression tests: strong_impulse_detector guards corrupt / out-of-order input.

Same class as the round-6 SMC-box finding, swept into the impulse detector
(backtest-reachable, raw un-coerced OHLC):

* ``IgnitionCandleDetector.detect`` accepted an inverted ``high < low`` candle
  (negative range/body, silently floored to strength 0) and let non-finite OHLC
  poison the rolling recent-high/low history for every later bar.
* ``StrongImpulseDetector.update_phase`` drove ``confirmation_bars`` negative on
  an out-of-order bar (reconnect / backfill / duplicate feed) — silent state
  corruption of the phase machine.

The original draft tests asserted the *buggy* behaviour and were themselves
broken (a single ``detect`` call returns None for <2 history bars, so they
failed at setup). These assert the *fixed* behaviour with correct priming.
"""

from __future__ import annotations

from services.live_overlay_daemon.strong_impulse_detector import (
    IgnitionCandleDetector,
    StrongImpulseDetector,
)


def _prime(detector: IgnitionCandleDetector) -> None:
    """Seed one benign candle so detect() has the >=2 history it needs."""
    detector.detect(bar_index=0, open=100.0, high=101.0, low=99.0, close=100.5, atr=1.0)


def test_ignition_rejects_inverted_high_low_candle() -> None:
    """An inverted candle that WOULD meet the criteria is rejected outright."""
    detector = IgnitionCandleDetector()
    # Tiny recent range so the inverted candle would otherwise "extend beyond".
    detector.detect(bar_index=0, open=1.0, high=1.0, low=1.0, close=1.0, atr=1.0)
    candle = detector.detect(
        bar_index=1, open=105.0, high=100.0, low=110.0, close=101.0, atr=1.0
    )
    assert candle is None


def test_ignition_rejects_nonfinite_ohlc_without_poisoning_history() -> None:
    detector = IgnitionCandleDetector()
    _prime(detector)
    assert len(detector.price_history) == 1

    for high, low, close in [
        (float("inf"), 100.0, 109.0),
        (110.0, float("-inf"), 109.0),
        (110.0, 100.0, float("nan")),
    ]:
        assert (
            detector.detect(
                bar_index=1, open=100.0, high=high, low=low, close=close, atr=1.0
            )
            is None
        )
        # Corrupt candle never lands in the rolling history.
        assert len(detector.price_history) == 1


def test_ignition_still_detects_valid_candle() -> None:
    """Guard must not regress the happy path."""
    detector = IgnitionCandleDetector()
    _prime(detector)
    candle = detector.detect(
        bar_index=1, open=100.0, high=110.0, low=100.0, close=109.0, atr=1.0
    )
    assert candle is not None
    assert candle.range == 10.0
    assert candle.body_size > 0


def test_update_phase_out_of_order_bar_index_does_not_corrupt_confirmation() -> None:
    detector = StrongImpulseDetector(propulsion_threshold=0.0)
    detector.ignition_detector.detect(
        bar_index=9, open=100.0, high=101.0, low=99.0, close=100.5, atr=1.0
    )
    signal = detector.detect_impulse(
        bar_index=10, open=100.0, high=110.0, low=99.0, close=109.0,
        atr=1.0, recent_momentum=0.9, volume_ratio=2.0,
    )
    assert signal is not None
    assert signal.confirmation_bars == 0

    # Out-of-order bar (bar 5 after bar 10) must be skipped, not corrupt state.
    updated = detector.update_phase(bar_index=5, high=108.0, low=100.0, close=105.0)
    assert updated == []
    assert signal.confirmation_bars == 0


def test_update_phase_in_order_still_advances() -> None:
    detector = StrongImpulseDetector(propulsion_threshold=0.0)
    detector.ignition_detector.detect(
        bar_index=9, open=100.0, high=101.0, low=99.0, close=100.5, atr=1.0
    )
    signal = detector.detect_impulse(
        bar_index=10, open=100.0, high=110.0, low=99.0, close=109.0,
        atr=1.0, recent_momentum=0.9, volume_ratio=2.0,
    )
    assert signal is not None

    updated = detector.update_phase(bar_index=11, high=108.0, low=100.0, close=105.0)
    assert len(updated) == 1
    assert updated[0].confirmation_bars == 1


def test_update_phase_duplicate_bar_index_is_skipped() -> None:
    """A duplicate feed bar at the ignition bar_index confirms nothing and must
    be skipped, not returned as an 'update' with confirmation_bars=0.
    """
    detector = StrongImpulseDetector(propulsion_threshold=0.0)
    detector.ignition_detector.detect(
        bar_index=9, open=100.0, high=101.0, low=99.0, close=100.5, atr=1.0
    )
    signal = detector.detect_impulse(
        bar_index=10, open=100.0, high=110.0, low=99.0, close=109.0,
        atr=1.0, recent_momentum=0.9, volume_ratio=2.0,
    )
    assert signal is not None
    assert signal.confirmation_bars == 0

    # Duplicate of the ignition bar (bar 10 again) must be skipped.
    updated = detector.update_phase(bar_index=10, high=108.0, low=100.0, close=105.0)
    assert updated == []
    assert signal.confirmation_bars == 0
