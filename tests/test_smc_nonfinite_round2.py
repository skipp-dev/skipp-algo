"""Round-2 non-finite / corrupt-input guards for the SMC detector cluster.

Follows the round-1 hardening (test_detector_nonfinite_guards.py): the pattern
predicates and the fractal detector guarded only NaN, so a ±inf tick slipped
through and fabricated structures; the propulsion score could crash or go
negative on a degenerate/corrupt bar; and process_candle handed out its
internal list. These detectors are reachable via the offline backtester, which
does not finite-coerce OHLC.
"""

from __future__ import annotations

import math

from services.live_overlay_daemon.smc_advanced_patterns import BrokenFractalDetector
from services.live_overlay_daemon.smc_ringbuffer import (
    is_fvg_down,
    is_fvg_up,
    is_ob_down,
    is_ob_up,
    is_rjb_down,
    is_rjb_up,
    is_up,
)
from services.live_overlay_daemon.smc_signal_detector import Candle, SmcSignalDetector
from services.live_overlay_daemon.strong_impulse_detector import (
    IgnitionCandle,
    PropulsionStrengthScorer,
)


class TestPredicatesRejectNonFinite:
    """is_* pattern predicates must reject ±inf (not just NaN); an inf OHLC
    field otherwise fabricates a bullish FVG / bearish OB / etc."""

    def test_is_fvg_rejects_infinite(self):
        assert is_fvg_up(float("inf"), 100.0) is False
        assert is_fvg_up(101.0, float("-inf")) is False
        assert is_fvg_down(float("-inf"), 100.0) is False
        # A genuine finite gap still detects.
        assert is_fvg_up(101.0, 100.0) is True

    def test_is_ob_rejects_infinite(self):
        assert is_ob_up(float("inf"), 99.0, 99.0, 100.0, 100.0, 101.0, 98.0) is False
        assert is_ob_down(float("-inf"), 101.0, 101.0, 100.0, 100.0, 101.0, 99.0) is False

    def test_is_rjb_rejects_infinite(self):
        assert is_rjb_down(float("inf"), 100.0, 101.0) is False
        assert is_rjb_up(float("-inf"), 100.0, 99.0) is False

    def test_is_up_rejects_infinite(self):
        assert is_up(float("inf"), 100.0) is False


class TestBrokenFractalRejectsNonFinite:
    def test_nan_bar_does_not_confirm_break(self):
        det = BrokenFractalDetector()
        for h in (100.0, 101.0, float("nan")):
            det.detect(bar_index=0, high=h, low=99.0, close=100.0)
        result = det.detect(bar_index=5, high=200.0, low=99.0, close=199.0)
        assert result is None
        # The NaN bar must not have entered the fractal history.
        assert all(math.isfinite(f["high"]) for f in det.fractal_history)

    def test_inf_bar_returns_none(self):
        det = BrokenFractalDetector()
        assert det.detect(bar_index=0, high=float("inf"), low=99.0, close=100.0) is None


class TestProcessCandleReturnsFreshList:
    def _feed(self, det, n):
        last = None
        for i in range(n):
            last = det.process_candle(
                Candle(bar_index=i, open=100.0, high=101.0, low=99.0, close=100.0, volume=1000)
            )
        return last

    def test_successive_calls_return_distinct_lists(self):
        det = SmcSignalDetector()
        self._feed(det, 3)
        a = det.process_candle(Candle(bar_index=3, open=100.0, high=101.0, low=99.0, close=100.0, volume=1000))
        b = det.process_candle(Candle(bar_index=4, open=100.0, high=101.0, low=99.0, close=100.0, volume=1000))
        assert a is not b  # not the same internal list
        # Mutating/holding `a` must not be clobbered by the next call.
        a.append("sentinel")
        assert "sentinel" not in b

    def test_warmup_return_is_also_a_copy(self):
        det = SmcSignalDetector()
        first = det.process_candle(Candle(bar_index=0, open=100.0, high=101.0, low=99.0, close=100.0, volume=1000))
        assert first is not det.signals


class TestPropulsionRangeAndStrengthGuards:
    def _ig(self, **kw):
        base = dict(bar_index=0, open=100.0, high=101.0, low=99.0, close=100.5,
                    body_size=0.5, range=2.0, direction="bullish")
        base.update(kw)
        return IgnitionCandle(**base)

    def test_zero_range_does_not_crash(self):
        scorer = PropulsionStrengthScorer()
        ig = self._ig(high=100.0, low=100.0, close=100.0, body_size=0.0, range=0.0)
        p = scorer.calculate(ignition=ig, atr=2.0, recent_momentum=0.5, volume_ratio=1.0)
        assert math.isfinite(p.total_strength)

    def test_corrupt_close_keeps_strength_non_negative(self):
        scorer = PropulsionStrengthScorer()
        # close below low with a bearish body → several factors go negative.
        ig = self._ig(high=101.0, low=100.0, close=98.0, body_size=-2.0, range=1.0)
        p = scorer.calculate(ignition=ig, atr=2.0, recent_momentum=0.5, volume_ratio=1.0)
        assert p.total_strength >= 0.0

    def test_strong_impulse_still_scores_high(self):
        scorer = PropulsionStrengthScorer()
        ig = self._ig(high=110.0, low=100.0, close=109.5, body_size=9.5, range=10.0)
        p = scorer.calculate(ignition=ig, atr=2.0, recent_momentum=1.0, volume_ratio=3.0)
        assert p.total_strength > 6.0  # no regression from the clamp
