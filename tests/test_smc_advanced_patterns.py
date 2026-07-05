"""Tests for SMC Advanced Patterns (HVB, PPDD, Liquidity, Broken Fractal)."""


from services.live_overlay_daemon.smc_advanced_patterns import (
    BrokenFractalDetector,
    HVBDetector,
    LiquidityCluster,
    LiquidityClusterDetector,
    PPDDClassifier,
)


class TestHVBDetector:
    """Test High Volume Bar detection."""

    def test_hvb_detection_above_threshold(self):
        """HVB should be detected when volume > threshold."""
        detector = HVBDetector(lookback=5, hvb_threshold=1.5)

        # Build baseline: 5 candles with volume 100
        for _ in range(5):
            detector.detect(
                bar_index=0,
                volume=100,
                close=100,
                open=99,
                high=101,
                low=99,
            )

        # 6th candle with 2x volume
        hvb = detector.detect(
            bar_index=6,
            volume=200,
            close=101,
            open=100,
            high=102,
            low=100,
        )

        assert hvb.is_hvb is True
        assert hvb.volume_ratio > 1.5

    def test_hvb_detection_below_threshold(self):
        """HVB should not be detected when volume <= threshold."""
        detector = HVBDetector(lookback=5, hvb_threshold=1.5)

        # Build baseline
        for _ in range(5):
            detector.detect(
                bar_index=0,
                volume=100,
                close=100,
                open=99,
                high=101,
                low=99,
            )

        # 6th candle with 1.2x volume (below 1.5x threshold)
        hvb = detector.detect(
            bar_index=6,
            volume=120,
            close=101,
            open=100,
            high=102,
            low=100,
        )

        assert hvb.is_hvb is False
        assert hvb.volume_ratio < 1.5

    def test_volume_history_is_bounded_by_lookback(self):
        """deque(maxlen) refactor: rolling window must not grow past lookback."""
        detector = HVBDetector(lookback=3, hvb_threshold=1.5)
        for i in range(1000):
            detector.detect(bar_index=i, volume=100, close=100, open=99, high=101, low=99)
        assert len(detector.volume_history) == 3

    def test_rolling_average_matches_last_lookback_bars(self):
        """avg_volume must reflect only the trailing `lookback` volumes
        (incl. the current bar) — behaviour preserved from the list+pop(0) impl."""
        detector = HVBDetector(lookback=3, hvb_threshold=999)  # threshold high: measure avg only
        for volume in (10, 20, 30):
            detector.detect(bar_index=0, volume=volume, close=100, open=99, high=101, low=99)
        # Window is now [10, 20, 30]; next bar evicts 10 -> [20, 30, 60].
        hvb = detector.detect(bar_index=4, volume=60, close=100, open=99, high=101, low=99)
        assert hvb.avg_volume == (20 + 30 + 60) / 3
        assert list(detector.volume_history) == [20, 30, 60]

    def test_rejects_negative_volume_in_history(self):
        """A negative volume must not poison the rolling average and fabricate
        an HVB on the next normal bar (repro: [100, -100, 1] flipped is_hvb)."""
        detector = HVBDetector(lookback=3, hvb_threshold=1.5)
        results = [
            detector.detect(bar_index=i, volume=v, close=100.0, open=100.0, high=100.0, low=100.0)
            for i, v in enumerate([100, -100, 1])
        ]
        # -100 is clamped to 0 in the window, so avg stays sane and vol=1 is tiny.
        assert results[2].is_hvb is False
        assert list(detector.volume_history) == [100, 0, 1]

    def test_rejects_non_finite_volume(self):
        detector = HVBDetector(lookback=3, hvb_threshold=1.5)
        bar = detector.detect(bar_index=0, volume=float("inf"), close=100.0, open=100.0, high=100.0, low=100.0)
        assert bar.is_hvb is False
        assert list(detector.volume_history) == [0]


class TestPPDDClassifier:
    """Test Premium/Discount OrderBlock classification."""

    def test_bullish_ob_premium(self):
        """Bullish OB above current price = Premium (resistance)."""
        classifier = PPDDClassifier(atr_multiple=2.0)

        ob = classifier.classify(
            ob_top=110,
            ob_bottom=105,
            direction="bullish",
            current_price=100,
            atr=5,
        )

        assert ob.is_premium is True
        assert ob.is_discount is False
        assert ob.bias() == "premium"

    def test_bullish_ob_discount(self):
        """Bullish OB below current price = Discount (support)."""
        classifier = PPDDClassifier(atr_multiple=2.0)

        ob = classifier.classify(
            ob_top=95,
            ob_bottom=90,
            direction="bullish",
            current_price=100,
            atr=5,
        )

        assert ob.is_premium is False
        assert ob.is_discount is True
        assert ob.bias() == "discount"

    def test_bearish_ob_premium(self):
        """Bearish OB above current price = Premium (resistance)."""
        classifier = PPDDClassifier(atr_multiple=2.0)

        ob = classifier.classify(
            ob_top=110,
            ob_bottom=105,
            direction="bearish",
            current_price=100,
            atr=5,
        )

        assert ob.is_premium is True
        assert ob.is_discount is False

    def test_hvb_confirmation_strength(self):
        """OB strength should increase with HVB confirmation."""
        classifier = PPDDClassifier(atr_multiple=2.0)

        ob_with_hvb = classifier.classify(
            ob_top=110,
            ob_bottom=105,
            direction="bullish",
            current_price=100,
            atr=5,
            hvb_present=True,
        )

        ob_no_hvb = classifier.classify(
            ob_top=110,
            ob_bottom=105,
            direction="bullish",
            current_price=100,
            atr=5,
            hvb_present=False,
        )

        assert ob_with_hvb.hvb_confirmation is True
        assert ob_no_hvb.hvb_confirmation is False


class TestLiquidityClusterDetector:
    """Test liquidity cluster detection."""

    def test_cluster_detection_from_highs(self):
        """Should detect cluster of swing highs."""
        detector = LiquidityClusterDetector(
            cluster_distance_atr=0.5, min_confluences=2
        )

        # Two highs close together
        swing_highs = [110.0, 110.5]
        swing_lows = [90.0, 89.5]

        clusters = detector.detect_clusters(
            swing_highs=swing_highs,
            swing_lows=swing_lows,
            current_price=100.0,
            atr=10.0,
        )

        assert len(clusters) >= 1
        assert clusters[0].cluster_count >= 2

    def test_cluster_risk_classification(self):
        """Risk should vary by distance from current price."""
        detector = LiquidityClusterDetector(
            cluster_distance_atr=0.5, min_confluences=2
        )

        swing_highs = [100.0, 100.2]  # Very close to current
        swing_lows = []

        clusters = detector.detect_clusters(
            swing_highs=swing_highs,
            swing_lows=swing_lows,
            current_price=100.1,
            atr=10.0,
        )

        if clusters:
            assert clusters[0].risk_level == "high"  # Very close = high risk


class TestBrokenFractalDetector:
    """Test Broken Fractal pattern detection."""

    def test_fractal_break_detection_up(self):
        """Should detect upward fractal break."""
        detector = BrokenFractalDetector()

        # Build fractal history
        detector.detect(bar_index=1, high=100, low=95, close=98)
        detector.detect(bar_index=2, high=102, low=94, close=101)
        detector.detect(bar_index=3, high=101, low=93, close=100)

        # Break above
        bf = detector.detect(bar_index=4, high=103, low=96, close=103)

        assert bf is not None
        assert bf.break_direction == "up"

    def test_fractal_break_confirmation(self):
        """Break should be confirmed on close above/below."""
        detector = BrokenFractalDetector()

        detector.detect(bar_index=1, high=100, low=95, close=98)
        detector.detect(bar_index=2, high=102, low=94, close=101)
        detector.detect(bar_index=3, high=101, low=93, close=100)

        # Break with close confirmation
        bf = detector.detect(bar_index=4, high=103, low=96, close=103)

        if bf:
            assert bf.confirmed is True


class TestLiquidityCluster:
    """Test LiquidityCluster dataclass."""

    def test_contains_price(self):
        """Should identify if price is in cluster zone."""
        cluster = LiquidityCluster(
            center_price=100.0,
            zone_top=101.0,
            zone_bottom=99.0,
            cluster_count=3,
            risk_level="medium",
            direction_bias="neutral",
        )

        assert cluster.contains_price(100.0) is True
        assert cluster.contains_price(99.5) is True
        assert cluster.contains_price(101.0) is True
        assert cluster.contains_price(102.0) is False
        assert cluster.contains_price(98.0) is False

    def test_zone_width(self):
        """Should calculate zone width correctly."""
        cluster = LiquidityCluster(
            center_price=100.0,
            zone_top=110.0,
            zone_bottom=90.0,
            cluster_count=2,
            risk_level="low",
            direction_bias="neutral",
        )

        assert cluster.zone_width == 20.0
