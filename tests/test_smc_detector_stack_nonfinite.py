"""Non-finite (NaN / ±inf) hardening for the wider SMC detector stack.

Follow-up to the smc_ringbuffer/smc_signal_detector hardening: every detector
in the stack builds price levels/zones (invalidation, targets, stops, pivots,
supertrend, fractal boxes, liquidity clusters) or gates trades, and each did
so with no finite-validation. Corrupt feed data would poison persisted state
(``max``/``min``/history) or emit signals with NaN/inf levels. These tests pin
that each public entry point now rejects/skip non-finite inputs.
"""
from __future__ import annotations

import math

import pytest

from services.live_overlay_daemon.smc_advanced_patterns import (
    BrokenFractalDetector,
    LiquidityClusterDetector,
    PPDDClassifier,
)
from services.live_overlay_daemon.smt_sniper_validator import (
    LiquiditySweepDetector,
    SmtSniperValidator,
)
from services.live_overlay_daemon.strong_impulse_detector import (
    IgnitionCandleDetector,
    StrongImpulseDetector,
)
from services.live_overlay_daemon.triple_confluence_navigator import (
    TripleConfluenceNavigator,
)
from services.live_overlay_daemon.volatility_filter import VolatilityFilter

NAN = float("nan")
INF = float("inf")


class TestStrongImpulseNonFinite:
    def test_detect_impulse_skips_nonfinite_atr(self) -> None:
        det = StrongImpulseDetector()
        assert det.detect_impulse(0, 100.0, 101.0, 99.0, 100.5, NAN, 0.5, 1.2) is None
        # A skipped candle must not poison the ignition history.
        assert det.ignition_detector.price_history == []

    def test_ignition_detector_skips_nonfinite_ohlc(self) -> None:
        ig = IgnitionCandleDetector()
        assert ig.detect(0, NAN, 1.0, 0.0, 0.0, 1.0) is None
        assert ig.detect(1, 0.0, INF, 0.0, 0.0, 1.0) is None
        assert ig.price_history == []

    def test_finite_inputs_still_record_history(self) -> None:
        ig = IgnitionCandleDetector()
        ig.detect(0, 100.0, 101.0, 99.0, 100.5, 1.0)
        assert len(ig.price_history) == 1


class TestTripleConfluenceNonFinite:
    def test_process_candle_skips_nonfinite(self) -> None:
        nav = TripleConfluenceNavigator()
        assert nav.process_candle(0, 100.0, 101.0, 99.0, NAN, 1.0, 1000) is None
        # Persisted pivot/history state must stay clean.
        assert nav.structure.pivot_high == 0.0
        assert nav.structure.pivot_low == 0.0
        assert nav.price_history == []

    def test_nonfinite_atr_is_rejected(self) -> None:
        nav = TripleConfluenceNavigator()
        assert nav.process_candle(0, 100.0, 101.0, 99.0, 100.0, INF, 1000) is None


class TestSmtSniperNonFinite:
    def test_sweep_detector_skips_nonfinite(self) -> None:
        det = LiquiditySweepDetector()
        assert det.detect(0, INF, 99.0, 100.0, 1.0) is None
        assert det.detect(1, 101.0, 99.0, 100.0, NAN) is None
        assert det.recent_extremes["highs"] == []
        assert det.recent_extremes["lows"] == []

    def test_validate_entry_skips_nonfinite(self) -> None:
        val = SmtSniperValidator()
        result = val.validate_entry(0, NAN, 99.0, 100.0, 1.0, 0.5, {}, 0.5)
        assert result is None


class TestBrokenFractalNonFinite:
    def test_detect_skips_nonfinite(self) -> None:
        det = BrokenFractalDetector()
        assert det.detect(0, NAN, 99.0, 100.0) is None
        assert det.detect(1, 101.0, 99.0, INF) is None
        assert det.fractal_history == []

    def test_finite_inputs_still_record(self) -> None:
        det = BrokenFractalDetector()
        det.detect(0, 101.0, 99.0, 100.0)
        assert len(det.fractal_history) == 1


class TestLiquidityClusterNonFinite:
    def test_detect_clusters_returns_empty_on_nonfinite(self) -> None:
        det = LiquidityClusterDetector(min_confluences=1)
        assert det.detect_clusters([100.0, 101.0], [98.0, 99.0], 100.0, NAN) == []
        assert det.detect_clusters([100.0, 101.0], [98.0, 99.0], INF, 1.0) == []

    def test_cluster_prices_drops_nonfinite(self) -> None:
        det = LiquidityClusterDetector()
        # A NaN in the price list would make sorted() a garbage partial order.
        clusters = det._cluster_prices([100.0, NAN, 100.1, INF], distance=1.0)
        assert clusters  # still produced from the finite prices
        assert all(math.isfinite(center) for center, _count in clusters)


class TestPpddClassifierNonFinite:
    def test_classify_rejects_nonfinite(self) -> None:
        clf = PPDDClassifier()
        with pytest.raises(ValueError):
            clf.classify(NAN, 99.0, "bullish", 100.0, 1.0)
        with pytest.raises(ValueError):
            clf.classify(101.0, 99.0, "bullish", 100.0, INF)

    def test_classify_accepts_finite(self) -> None:
        clf = PPDDClassifier()
        block = clf.classify(101.0, 99.0, "bullish", 100.0, 1.0)
        assert math.isfinite(block.box_top) and math.isfinite(block.box_bottom)


class TestVolatilityFilterNonFinite:
    def _warm(self, vf: VolatilityFilter, n: int) -> None:
        for i in range(n):
            vf.calculate_atr(high=101.0 + i, low=99.0 + i, close=100.0 + i)

    def test_nan_candle_does_not_poison_history(self) -> None:
        vf = VolatilityFilter(atr_period=2, sma_period=3)
        self._warm(vf, 5)
        vf.calculate_atr(high=NAN, low=NAN, close=NAN)  # corrupt candle
        assert all(math.isfinite(v) for v in vf.atr_history)
        ratio = vf.get_atr_ratio()
        assert ratio is None or math.isfinite(ratio)

    def test_get_atr_ratio_none_on_nonfinite_history(self) -> None:
        vf = VolatilityFilter(atr_period=2, sma_period=3)
        vf.atr_history = [1.0, 1.0, INF]  # last ATR non-finite
        assert vf.get_atr_ratio() is None

    def test_is_tradeable_fails_closed_on_nonfinite_ratio(self) -> None:
        # The core fail-open bug: a NaN ratio made both threshold comparisons
        # False and fell through to "tradeable". It must now fail closed.
        class _NanRatioFilter(VolatilityFilter):
            def get_atr_ratio(self):  # type: ignore[override]
                return NAN

        tradeable, reason = _NanRatioFilter().is_tradeable()
        assert tradeable is False
        assert reason == "non_finite_atr"

    def test_normal_volatility_still_tradeable(self) -> None:
        vf = VolatilityFilter(atr_period=2, sma_period=3, ratio_min=0.0, ratio_max=10.0)
        self._warm(vf, 6)
        tradeable, _reason = vf.is_tradeable()
        assert tradeable is True
