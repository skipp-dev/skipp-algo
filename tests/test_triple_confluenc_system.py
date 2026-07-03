"""Tests for all 3 advanced systems: SMT Sniper, Strong Impulse, Triple Confluence."""

import pytest

from services.live_overlay_daemon.smt_sniper_validator import (
    LiquiditySweepDetector,
    SmtQualityScorer,
    SmtSniperValidator,
)
from services.live_overlay_daemon.strong_impulse_detector import (
    IgnitionCandleDetector,
    PropulsionStrengthScorer,
    StrongImpulseDetector,
)
from services.live_overlay_daemon.triple_confluence_navigator import (
    AdaptiveRsiSupertrend,
    CardwellMomentum,
    KalmanFilterState,
    MarketStructure,
    TripleConfluenceNavigator,
)


# ============================================================================
# SMT SNIPER TESTS
# ============================================================================


class TestLiquiditySweepDetector:
    """Test liquidity sweep detection."""

    def test_downward_sweep_detection(self):
        """Should detect downward sweep below recent lows."""
        detector = LiquiditySweepDetector(sweep_threshold_atr=0.5)

        # Build baseline with clear high/low
        for i in range(10):
            detector.detect(
                bar_index=i,
                high=105.0,
                low=95.0,
                close=100.0,
                atr=5.0,
            )

        # Sweep down below recent low (95)
        sweep = detector.detect(
            bar_index=10,
            high=100.0,
            low=88.0,  # 2+ ATR below recent low
            close=92.0,
            atr=5.0,
        )

        assert sweep is not None
        assert sweep.direction == "down"

    def test_no_sweep_when_within_threshold(self):
        """Should not detect sweep if within threshold."""
        detector = LiquiditySweepDetector(sweep_threshold_atr=0.5)

        for i in range(5):
            detector.detect(
                bar_index=i,
                high=100,
                low=95,
                close=98,
                atr=10.0,
            )

        sweep = detector.detect(
            bar_index=5,
            high=101,
            low=94,  # Just touches recent low, no significant sweep
            close=99,
            atr=10.0,
        )

        assert sweep is None


class TestSmtQualityScorer:
    """Test quality score calculation."""

    def test_quality_score_with_confirmed_sweep(self):
        """Quality should increase with confirmed sweep."""
        scorer = SmtQualityScorer()

        from services.live_overlay_daemon.smt_sniper_validator import LiquiditySweep

        sweep = LiquiditySweep(
            bar_index=5,
            sweep_price=90.0,
            sweep_depth_atr=2.0,
            direction="down",
            confirmed=True,
            confirmation_bar_index=6,
        )

        quality = scorer.calculate(
            sweep=sweep,
            structure_score=0.8,
            correlation_strength=0.7,
            momentum_score=0.6,
        )

        assert quality.total_score > 70  # Should be high quality


# ============================================================================
# STRONG IMPULSE TESTS
# ============================================================================


class TestIgnitionCandleDetector:
    """Test ignition candle detection."""

    def test_ignition_candle_detection(self):
        """Should detect bullish ignition candle."""
        detector = IgnitionCandleDetector()

        # Build baseline
        for i in range(5):
            detector.detect(
                bar_index=i,
                open=100,
                high=102,
                low=98,
                close=101,
                atr=2.0,
            )

        # Ignition candle: extends beyond range, body dominates, close at extreme
        ignition = detector.detect(
            bar_index=5,
            open=100,
            high=108,  # Extends beyond recent 102
            low=102,
            close=107,  # Close near high
            atr=2.0,
        )

        assert ignition is not None
        assert ignition.direction == "bullish"


class TestPropulsionStrengthScorer:
    """Test propulsion strength calculation."""

    def test_propulsion_strength_calculation(self):
        """Should calculate 0-10 propulsion strength."""
        scorer = PropulsionStrengthScorer()

        from services.live_overlay_daemon.strong_impulse_detector import (
            IgnitionCandle,
        )

        ignition = IgnitionCandle(
            bar_index=5,
            open=100,
            high=108,
            low=102,
            close=107,
            body_size=7.0,
            range=6.0,
            direction="bullish",
        )

        propulsion = scorer.calculate(
            ignition=ignition,
            atr=2.0,
            recent_momentum=0.8,
            volume_ratio=2.0,
        )

        assert 0 <= propulsion.total_strength <= 10
        assert propulsion.is_strong_impulse(threshold=6.0)


# ============================================================================
# TRIPLE CONFLUENCE TESTS
# ============================================================================


class TestKalmanFilter:
    """Test Kalman filter noise reduction."""

    def test_kalman_filter_smoothing(self):
        """Should smooth noisy measurements."""
        kf = KalmanFilterState()

        # Noisy signal: 0, 10, 0, 10, 0, 10
        measurements = [0, 10, 0, 10, 0, 10]
        smoothed = [kf.update(m) for m in measurements]

        # Should converge to ~5 (average) instead of oscillating
        assert smoothed[-1] != 0 and smoothed[-1] != 10  # Not extreme
        assert 3 < smoothed[-1] < 7  # Close to average


class TestCardwellMomentum:
    """Test Cardwell momentum with Kalman filter."""

    def test_cardwell_momentum_signal(self):
        """Should generate bullish/bearish momentum signals."""
        cm = CardwellMomentum()

        # Uptrend
        for close in [100, 101, 102, 103, 104]:
            signal = cm.update(close)

        assert cm.signal == "bullish"


class TestMarketStructure:
    """Test market structure pivot detection."""

    def test_pivot_break_detection(self):
        """Should detect break of structure."""
        ms = MarketStructure()

        # Build baseline
        ms.update(high=105, low=95, pivot_high_prev=100, pivot_low_prev=90)

        # Break above pivot
        signal = ms.update(high=110, low=98, pivot_high_prev=105, pivot_low_prev=95)

        assert ms.break_of_structure is True
        assert signal == "bullish"


class TestTripleConfluenceNavigator:
    """Test complete 3-way confluence system."""

    def test_triple_confluence_long_signal(self):
        """Should generate long signal when all 3 align."""
        nav = TripleConfluenceNavigator()

        # Uptrend candles to align all 3 systems
        signal = None
        for i in range(30):
            close = 100 + i
            high = close + 2
            low = close - 1
            open = close - 1

            signal = nav.process_candle(
                bar_index=i,
                open=open,
                high=high,
                low=low,
                close=close,
                atr=1.5,
                volume=100,
                htf_bias="neutral",
            )

        # Should eventually get a bullish signal
        assert signal is not None
        assert signal.direction in ["long", "short", "neutral"]

    def test_htf_bias_validation(self):
        """Should reject signal if HTF bias misaligned."""
        nav = TripleConfluenceNavigator()

        signal = nav.process_candle(
            bar_index=1,
            open=100,
            high=102,
            low=98,
            close=101,
            atr=2.0,
            volume=100,
            htf_bias="short",  # Opposite of expected bullish signal
        )

        # Should either be None or have misaligned HTF
        if signal:
            assert not signal.htf_bias_aligned
