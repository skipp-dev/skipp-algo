"""Non-finite hardening for the detector-stack entry points #3161 left open.

#3161 guarded the SMC-adjacent detectors' history/cluster paths, but three
public entry points still ingested non-finite OHLC/ATR into persisted state or
level construction, and VolatilityFilter's gate could still fall through to
"tradeable" on a non-finite ratio. These tests pin the remaining guards.
"""
from __future__ import annotations

import math

import pytest

from services.live_overlay_daemon.smc_advanced_patterns import PPDDClassifier
from services.live_overlay_daemon.smt_sniper_validator import (
    LiquiditySweepDetector,
    SmtSniperValidator,
)
from services.live_overlay_daemon.triple_confluence_navigator import (
    TripleConfluenceNavigator,
)
from services.live_overlay_daemon.volatility_filter import VolatilityFilter

NAN = float("nan")
INF = float("inf")


class TestTripleConfluenceNonFinite:
    def test_process_candle_skips_nonfinite(self) -> None:
        nav = TripleConfluenceNavigator()
        assert nav.process_candle(0, 100.0, 101.0, 99.0, NAN, 1.0, 1000) is None
        assert nav.process_candle(0, 100.0, 101.0, 99.0, 100.0, INF, 1000) is None
        assert nav.structure.pivot_high == 0.0
        assert nav.structure.pivot_low == 0.0
        assert nav.price_history == []

    def test_finite_candle_is_processed(self) -> None:
        nav = TripleConfluenceNavigator()
        nav.process_candle(0, 100.0, 101.0, 99.0, 100.0, 1.0, 1000)
        assert len(nav.price_history) == 1


class TestSmtSniperNonFinite:
    def test_sweep_detector_skips_nonfinite(self) -> None:
        det = LiquiditySweepDetector()
        assert det.detect(0, INF, 99.0, 100.0, 1.0) is None
        assert det.detect(1, 101.0, 99.0, 100.0, NAN) is None
        assert det.recent_extremes["highs"] == []
        assert det.recent_extremes["lows"] == []

    def test_validate_entry_skips_nonfinite(self) -> None:
        val = SmtSniperValidator()
        assert val.validate_entry(0, NAN, 99.0, 100.0, 1.0, 0.5, {}, 0.5) is None


class TestPpddClassifierNonFinite:
    def test_classify_rejects_nonfinite(self) -> None:
        clf = PPDDClassifier()
        with pytest.raises(ValueError):
            clf.classify(NAN, 99.0, "bullish", 100.0, 1.0)
        with pytest.raises(ValueError):
            clf.classify(101.0, 99.0, "bullish", 100.0, INF)

    def test_classify_accepts_finite(self) -> None:
        block = PPDDClassifier().classify(101.0, 99.0, "bullish", 100.0, 1.0)
        assert math.isfinite(block.box_top) and math.isfinite(block.box_bottom)


class TestVolatilityFilterFailClosed:
    def test_is_tradeable_fails_closed_on_nonfinite_ratio(self) -> None:
        class _NanRatioFilter(VolatilityFilter):
            def get_atr_ratio(self):  # type: ignore[override]
                return NAN

        tradeable, reason = _NanRatioFilter().is_tradeable()
        assert tradeable is False
        assert reason == "non_finite_atr"

    def test_get_atr_ratio_none_on_nonfinite_history(self) -> None:
        vf = VolatilityFilter(atr_period=2, sma_period=3)
        vf.atr_history = [1.0, 1.0, INF]
        assert vf.get_atr_ratio() is None

    def test_normal_volatility_still_tradeable(self) -> None:
        vf = VolatilityFilter(atr_period=2, sma_period=3, ratio_min=0.0, ratio_max=10.0)
        for i in range(6):
            vf.calculate_atr(high=101.0 + i, low=99.0 + i, close=100.0 + i)
        tradeable, _reason = vf.is_tradeable()
        assert tradeable is True
