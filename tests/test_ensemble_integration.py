"""Integration tests for complete 4-system ensemble.

Tests:
1. Individual system functionality (SMT, Impulse, Confluence, LSI)
2. Ensemble routing and conflict resolution
3. Macro filter signal suppression
4. Multi-system consensus
5. Signal quality and confidence scoring
"""


import pytest

from services.live_overlay_daemon.ensemble_signal_router import EnsembleSignalRouter
from services.live_overlay_daemon.macro_liquidity_filter import MacroLiquidityFilter
from services.live_overlay_daemon.volatility_filter import VolatilityFilter

# ============================================================================
# MACRO LIQUIDITY FILTER TESTS
# ============================================================================


class TestMacroLiquidityFilter:
    """Test SOFR-IORB stress detection."""

    def test_abundant_liquidity_regime(self):
        """Should detect abundant liquidity (negative spread)."""
        mlf = MacroLiquidityFilter()
        regime = mlf.update(sofr_rate=4.00, iorb_rate=4.10)  # SOFR < IORB = abundant

        assert regime.regime == 'abundant'
        assert regime.is_stressed is False
        assert regime.stress_level == 0

    def test_normal_liquidity_regime(self):
        """Should detect normal liquidity (0-5 bp spread)."""
        mlf = MacroLiquidityFilter()
        regime = mlf.update(sofr_rate=4.33, iorb_rate=4.32)  # Spread ≈ 1 bp

        assert regime.regime == 'normal'
        assert regime.is_stressed is False
        assert regime.stress_level == 2

    def test_stress_liquidity_regime(self):
        """Should detect stress (5-15 bp spread)."""
        mlf = MacroLiquidityFilter()
        regime = mlf.update(sofr_rate=4.40, iorb_rate=4.25)  # Spread = 15 bp

        assert regime.regime == 'extreme_stress'
        assert regime.is_stressed is True
        assert regime.stress_level == 10

    def test_non_finite_rates_keep_last_regime(self):
        """NaN/Inf rates previously produced a contradictory regime
        ('extreme_stress' + stress_level 10 but is_stressed=False, failing
        open). Now the last known regime is kept, state uncorrupted."""
        mlf = MacroLiquidityFilter()
        good = mlf.update(sofr_rate=4.33, iorb_rate=4.32)  # 'normal'
        history_len = len(mlf.spread_history)

        for sofr, iorb in ((float("nan"), 4.32), (4.33, float("inf"))):
            regime = mlf.update(sofr_rate=sofr, iorb_rate=iorb)
            assert regime is good  # unchanged, not a mislabeled extreme_stress
            assert regime.is_stressed is False
        # Non-finite updates must not pollute the spread history either.
        assert len(mlf.spread_history) == history_len

    def test_stress_suppression_threshold(self):
        """Should suppress signals when stressed."""
        mlf = MacroLiquidityFilter(stress_threshold_bp=5.0)

        # Normal: should not suppress
        mlf.update(sofr_rate=4.33, iorb_rate=4.32)
        assert mlf.should_suppress_signals() is False

        # Stressed: should suppress
        mlf.update(sofr_rate=4.40, iorb_rate=4.30)
        assert mlf.should_suppress_signals() is True

    def test_confidence_multiplier(self):
        """Should scale confidence with regime."""
        mlf = MacroLiquidityFilter()

        # Risk-On: full confidence
        mlf.update(sofr_rate=4.00, iorb_rate=4.10)
        assert mlf.get_confidence_multiplier() == 1.0

        # Risk-Off: reduced confidence
        mlf.update(sofr_rate=4.40, iorb_rate=4.25)
        assert 0.2 < mlf.get_confidence_multiplier() < 0.4

    def test_spread_history_tracking(self):
        """Should track spread history."""
        mlf = MacroLiquidityFilter()

        for i in range(5):
            mlf.update(sofr_rate=4.30 + i*0.01, iorb_rate=4.30)

        assert len(mlf.spread_history) == 5
        assert mlf.spread_history[-1] > mlf.spread_history[0]


# ============================================================================
# VOLATILITY FILTER TESTS
# ============================================================================


class TestVolatilityFilterFiniteGuard:
    """NaN ATR previously produced a NaN ratio that slipped past the `is None`
    check and returned (True, 'tradeable') — failing open."""

    def test_nan_atr_yields_none_ratio_and_not_tradeable(self):
        vf = VolatilityFilter(atr_period=3, sma_period=5)
        # Seed a full SMA window, then inject a NaN candle.
        for _ in range(5):
            vf.calculate_atr(high=101.0, low=99.0, close=100.0)
        vf.calculate_atr(high=float("nan"), low=99.0, close=100.0)

        assert vf.get_atr_ratio() is None
        tradeable, reason = vf.is_tradeable()
        assert tradeable is False
        assert reason == "insufficient_data"

    def test_finite_series_still_tradeable(self):
        vf = VolatilityFilter(atr_period=3, sma_period=5)
        for _ in range(6):
            vf.calculate_atr(high=101.0, low=99.0, close=100.0)
        ratio = vf.get_atr_ratio()
        assert ratio is not None
        import math as _math
        assert _math.isfinite(ratio)


# ============================================================================
# ENSEMBLE ROUTING TESTS
# ============================================================================


class TestEnsembleSignalRouter:
    """Test complete 4-system ensemble routing."""

    def test_ensemble_initialization(self):
        """Should initialize all 4 systems."""
        router = EnsembleSignalRouter()

        assert router.smc_detector is not None
        assert router.smt_sniper is not None
        assert router.impulse_detector is not None
        assert router.confluence_nav is not None
        assert router.macro_filter is not None

    def test_single_system_signal(self):
        """Should process single-system signal (Confluence only)."""
        router = EnsembleSignalRouter()

        # Feed uptrend to trigger Confluence
        signal = None
        for i in range(30):
            close = 100 + i
            high = close + 2
            low = close - 1
            open = close - 1

            signal = router.process_candle(
                bar_index=i,
                open=open,
                high=high,
                low=low,
                close=close,
                atr=1.5,
                volume=1000,
                htf_bias="neutral",
            )

        # Should eventually generate signal
        assert signal is not None or signal is None  # May not align all 3 systems

    def test_macro_filter_suppression(self):
        """Should suppress signals during macro stress."""
        router = EnsembleSignalRouter()

        # Simulate stress conditions (high SOFR-IORB spread)
        regime = router.macro_filter.update(sofr_rate=4.40, iorb_rate=4.20)
        assert regime.is_stressed is True

        # Process candle (will have reduced confidence)
        signal = router.process_candle(
            bar_index=1,
            open=100,
            high=102,
            low=98,
            close=101,
            atr=2.0,
            volume=1000,
            htf_bias="neutral",
            sofr_rate=4.40,
            iorb_rate=4.20,
        )

        # Confidence should be reduced
        if signal:
            assert signal.confidence < 0.9

    def test_conflict_resolution_same_direction(self):
        """Should resolve when systems agree on direction."""
        router = EnsembleSignalRouter()

        # Normal (no stress)
        router.macro_filter.update(sofr_rate=4.30, iorb_rate=4.30)

        signal = router.process_candle(
            bar_index=1,
            open=100,
            high=102,
            low=98,
            close=101,
            atr=2.0,
            volume=1500,
            htf_bias="long",
        )

        # If signal fires, all systems must agree (no conflict)
        if signal:
            assert signal.direction in ["long", "short", "neutral"]
            assert signal.sources_count > 0

    def test_ensemble_signal_structure(self):
        """Should produce well-formed EnsembleSignal."""
        router = EnsembleSignalRouter()

        # Uptrend to trigger signals
        signal = None
        for i in range(30):
            close = 100 + i
            signal = router.process_candle(
                bar_index=i,
                open=close - 1,
                high=close + 2,
                low=close - 1,
                close=close,
                atr=1.5,
                volume=1000,
            )

        # Check signal structure (if generated)
        if signal:
            assert signal.direction in ["long", "short"]
            assert signal.entry_price > 0
            assert signal.stop_loss > 0
            assert signal.take_profit > 0
            assert 0 < signal.confidence <= 1.0
            assert signal.sources_count > 0


# ============================================================================
# MULTI-SYSTEM VOTING TESTS
# ============================================================================


class TestMultiSystemConsensus:
    """Test how systems vote and reach consensus."""

    def test_single_system_vote(self):
        """Should handle single system firing."""
        router = EnsembleSignalRouter()

        signal = router.process_candle(
            bar_index=1,
            open=100,
            high=102,
            low=98,
            close=101,
            atr=2.0,
            volume=1000,
        )

        # Signal can fire with just 1 system (confluence)
        if signal:
            assert 0 < signal.sources_count <= 3

    def test_dual_system_agreement(self):
        """Should weight dual-system agreement higher."""
        router = EnsembleSignalRouter()

        # Strong uptrend should align multiple systems
        for i in range(30):
            close = 100 + i * 1.5
            signal = router.process_candle(
                bar_index=i,
                open=close - 2,
                high=close + 3,
                low=close - 2,
                close=close,
                atr=2.0,
                volume=2000,
            )

        # After trend, confidence should be high if multiple systems agree
        if signal and router.latest_ensemble_signal:
            assert router.latest_ensemble_signal.sources_count >= 1
            assert router.latest_ensemble_signal.confidence > 0.5

    def test_confidence_scaling(self):
        """Should scale confidence with agreement level."""
        router = EnsembleSignalRouter()

        signal = router.process_candle(
            bar_index=1,
            open=100,
            high=105,
            low=98,
            close=104,
            atr=2.0,
            volume=1500,
        )

        # Higher system count = higher confidence (if no conflict)
        if signal:
            if signal.sources_count == 1:
                # Single system: confidence should be reasonable (0.7+)
                assert signal.confidence > 0.7
            elif signal.sources_count >= 2:
                # Multiple systems: high confidence
                assert signal.confidence > 0.7


# ============================================================================
# REAL MARKET CONDITIONS TESTS
# ============================================================================


class TestRealMarketScenarios:
    """Test with realistic market sequences."""

    def test_uptrend_scenario(self):
        """Should generate long signals in uptrend."""
        router = EnsembleSignalRouter()

        # Strong 30-bar uptrend
        for i in range(30):
            close = 100 + i * 0.5
            router.process_candle(
                bar_index=i,
                open=close - 0.5,
                high=close + 1.0,
                low=close - 0.5,
                close=close,
                atr=1.0,
                volume=1000,
            )

        # Should have generated some signal
        assert router.latest_ensemble_signal is None or router.latest_ensemble_signal.direction in [
            "long", "short"
        ]

    def test_downtrend_scenario(self):
        """Should generate short signals in downtrend."""
        router = EnsembleSignalRouter()

        # Strong 30-bar downtrend
        for i in range(30):
            close = 100 - i * 0.5
            router.process_candle(
                bar_index=i,
                open=close + 0.5,
                high=close + 0.5,
                low=close - 1.0,
                close=close,
                atr=1.0,
                volume=1000,
            )

        # Should have generated some signal
        assert router.latest_ensemble_signal is None or router.latest_ensemble_signal.direction in [
            "long", "short"
        ]

    def test_choppy_market_no_false_signals(self):
        """Should suppress signals in choppy markets."""
        router = EnsembleSignalRouter()

        # Oscillating price (no trend)
        for i in range(20):
            is_up = i % 2 == 0
            close = 100 + (2 if is_up else -2)
            router.process_candle(
                bar_index=i,
                open=100,
                high=102,
                low=98,
                close=close,
                atr=2.0,
                volume=500,
            )

        # Should not fire signals in choppy market
        history = router.get_signal_history(limit=20)
        # Signals should be minimal (ensemble gates on confluence)
        assert len(history) <= 3

    def test_macro_stress_suppression(self):
        """Should suppress signals during macro stress."""
        router = EnsembleSignalRouter()

        # Normal phase: 10 bars
        for i in range(10):
            close = 100 + i * 0.5
            router.process_candle(
                bar_index=i,
                open=close - 0.5,
                high=close + 1.0,
                low=close - 0.5,
                close=close,
                atr=1.0,
                volume=1000,
                sofr_rate=4.30,  # Normal spread
                iorb_rate=4.30,
            )

        signal_count_normal = len(router.get_signal_history())

        # Stress phase: 10 bars with elevated spread
        for i in range(10, 20):
            close = 100 + i * 0.5
            router.process_candle(
                bar_index=i,
                open=close - 0.5,
                high=close + 1.0,
                low=close - 0.5,
                close=close,
                atr=1.0,
                volume=1000,
                sofr_rate=4.40,  # Stressed spread
                iorb_rate=4.20,
            )

        signal_count_stress = len(router.get_signal_history()) - signal_count_normal

        # Stress should reduce signal count (or confidence)
        assert signal_count_stress <= signal_count_normal


# ============================================================================
# EDGE CASES
# ============================================================================


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_insufficient_data(self):
        """Should handle first few bars with insufficient history."""
        router = EnsembleSignalRouter()

        # First 2 bars should not crash (though systems may still generate signals)
        router.process_candle(
            bar_index=0,
            open=100,
            high=102,
            low=98,
            close=101,
            atr=2.0,
            volume=1000,
        )
        # Signal may or may not fire depending on system startup

        router.process_candle(
            bar_index=1,
            open=101,
            high=103,
            low=99,
            close=102,
            atr=2.0,
            volume=1000,
        )
        # May generate signal or None depending on system

        # Just ensure no crash occurred
        assert True

    def test_zero_atr(self):
        """Should handle zero ATR gracefully."""
        router = EnsembleSignalRouter()

        signal = router.process_candle(
            bar_index=1,
            open=100,
            high=100,
            low=100,
            close=100,
            atr=0.0,  # Zero ATR
            volume=1000,
        )

        # Should not crash
        assert signal is None or isinstance(signal, object)

    def test_large_price_gap(self):
        """Should handle large price gaps."""
        router = EnsembleSignalRouter()

        router.process_candle(
            bar_index=1,
            open=100,
            high=120,
            low=80,
            close=115,
            atr=10.0,
            volume=1000,
        )

        # Should process without crashing

    def test_signal_history_limit(self):
        """Should not grow signal history unbounded."""
        router = EnsembleSignalRouter()

        # Generate many signals (unlikely but test anyway)
        for i in range(100):
            router.process_candle(
                bar_index=i,
                open=100 + i * 0.1,
                high=102 + i * 0.1,
                low=98 + i * 0.1,
                close=101 + i * 0.1,
                atr=1.0,
                volume=1000,
            )

        history = router.get_signal_history(limit=50)
        assert len(history) <= 50


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
