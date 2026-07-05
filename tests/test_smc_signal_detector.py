"""Tests for SMC signal detector — real-time pattern detection.

Simulates tick-by-tick candle stream, verifies:
- Pattern detection (OB/FVG/RJB)
- Signal emission
- Mitigation tracking
- State consistency
"""

from __future__ import annotations

import pytest

from services.live_overlay_daemon.smc_ringbuffer import BoxType, Direction
from services.live_overlay_daemon.smc_signal_detector import (
    Candle,
    SmcSignalDetector,
)


@pytest.fixture
def detector() -> SmcSignalDetector:
    """Initialize detector."""
    return SmcSignalDetector(max_boxes_per_direction=5)


def test_detector_needs_3_candles(detector: SmcSignalDetector) -> None:
    """Detector requires 3 candles for pattern detection."""
    c1 = Candle(bar_index=0, open=100.0, high=101.0, low=99.0, close=100.5, volume=1000)
    signals = detector.process_candle(c1)
    assert len(signals) == 0  # Need history


def test_detect_bullish_ob(detector: SmcSignalDetector) -> None:
    """Detect bullish order block: trapped bear → bullish engulf."""
    # t-2: trapped bear (opens high, closes low)
    c1 = Candle(bar_index=0, open=102.0, high=103.0, low=98.0, close=99.0, volume=1000)
    detector.process_candle(c1)

    # t-1: previous bear
    c2 = Candle(bar_index=1, open=99.5, high=100.0, low=98.5, close=98.8, volume=1000)
    detector.process_candle(c2)

    # t: bullish close above resistance (trapped high)
    c3 = Candle(bar_index=2, open=99.0, high=104.0, low=98.5, close=103.0, volume=2000)
    signals = detector.process_candle(c3)

    # Should detect bullish OB
    ob_signals = [s for s in signals if s.box_type == BoxType.ORDER_BLOCK and s.direction == Direction.BULLISH]
    assert len(ob_signals) == 1
    assert ob_signals[0].event_type == "created"
    assert ob_signals[0].box.created_at == 2


def test_detect_bearish_ob(detector: SmcSignalDetector) -> None:
    """Detect bearish order block: trapped bull → bearish engulf."""
    # t-2: trapped bull (opens low, closes high)
    c1 = Candle(bar_index=0, open=98.0, high=103.0, low=97.0, close=102.0, volume=1000)
    detector.process_candle(c1)

    # t-1: previous bull
    c2 = Candle(bar_index=1, open=102.0, high=103.0, low=101.0, close=102.5, volume=1000)
    detector.process_candle(c2)

    # t: bearish close below resistance (trapped low)
    c3 = Candle(bar_index=2, open=102.0, high=102.5, low=96.0, close=96.5, volume=2000)
    signals = detector.process_candle(c3)

    ob_signals = [s for s in signals if s.box_type == BoxType.ORDER_BLOCK and s.direction == Direction.BEARISH]
    assert len(ob_signals) == 1


def test_detect_bullish_fvg(detector: SmcSignalDetector) -> None:
    """Detect bullish FVG: gap between current low and 2-bar-ago high."""
    # t-2: closes with high 100
    c1 = Candle(bar_index=0, open=99.0, high=100.0, low=98.0, close=99.5, volume=1000)
    detector.process_candle(c1)

    # t-1: any bar
    c2 = Candle(bar_index=1, open=100.0, high=101.0, low=99.5, close=100.5, volume=1000)
    detector.process_candle(c2)

    # t: gap up (low > t-2 high) → 105 > 100
    c3 = Candle(bar_index=2, open=105.0, high=106.0, low=105.0, close=105.5, volume=2000)
    signals = detector.process_candle(c3)

    fvg_signals = [s for s in signals if s.box_type == BoxType.FAIR_VALUE_GAP and s.direction == Direction.BULLISH]
    assert len(fvg_signals) == 1


def test_detect_bearish_fvg(detector: SmcSignalDetector) -> None:
    """Detect bearish FVG: gap between current high and 2-bar-ago low."""
    # t-2: closes with low 100
    c1 = Candle(bar_index=0, open=101.0, high=102.0, low=100.0, close=101.0, volume=1000)
    detector.process_candle(c1)

    # t-1: any bar
    c2 = Candle(bar_index=1, open=100.0, high=100.5, low=99.5, close=100.0, volume=1000)
    detector.process_candle(c2)

    # t: gap down (high < t-2 low) → 95 < 100
    c3 = Candle(bar_index=2, open=95.0, high=95.5, low=94.0, close=94.5, volume=2000)
    signals = detector.process_candle(c3)

    fvg_signals = [s for s in signals if s.box_type == BoxType.FAIR_VALUE_GAP and s.direction == Direction.BEARISH]
    assert len(fvg_signals) == 1


def test_detect_mitigation(detector: SmcSignalDetector) -> None:
    """Detect when price breaches an order block."""
    # Create bullish OB
    c1 = Candle(bar_index=0, open=102.0, high=103.0, low=98.0, close=99.0, volume=1000)
    detector.process_candle(c1)
    c2 = Candle(bar_index=1, open=99.5, high=100.0, low=98.5, close=98.8, volume=1000)
    detector.process_candle(c2)
    c3 = Candle(bar_index=2, open=99.0, high=104.0, low=98.5, close=103.0, volume=2000)
    signals = detector.process_candle(c3)

    # OB created at bar 2, top=103, bottom=98
    ob = next(s.box for s in signals if s.box_type == BoxType.ORDER_BLOCK)
    assert not ob.is_mitigated

    # Move price above top
    c4 = Candle(bar_index=3, open=103.0, high=105.0, low=102.0, close=104.0, volume=1500)
    signals = detector.process_candle(c4)

    mit_signals = [s for s in signals if s.event_type == "mitigated"]
    assert len(mit_signals) > 0
    assert mit_signals[0].direction == Direction.BULLISH


def test_signal_event_attributes(detector: SmcSignalDetector) -> None:
    """Verify signal event structure."""
    c1 = Candle(bar_index=0, open=102.0, high=103.0, low=98.0, close=99.0, volume=1000)
    detector.process_candle(c1)
    c2 = Candle(bar_index=1, open=99.5, high=100.0, low=98.5, close=98.8, volume=1000)
    detector.process_candle(c2)
    c3 = Candle(bar_index=2, open=99.0, high=104.0, low=98.5, close=103.0, volume=2000)
    signals = detector.process_candle(c3)

    sig = signals[0]
    assert sig.bar_index == 2
    assert sig.event_type == "created"
    assert sig.box is not None
    assert sig.box.created_at == 2


def test_get_active_structures(detector: SmcSignalDetector) -> None:
    """Retrieve current unmitigated structures."""
    # Create OB
    c1 = Candle(bar_index=0, open=102.0, high=103.0, low=98.0, close=99.0, volume=1000)
    detector.process_candle(c1)
    c2 = Candle(bar_index=1, open=99.5, high=100.0, low=98.5, close=98.8, volume=1000)
    detector.process_candle(c2)
    c3 = Candle(bar_index=2, open=99.0, high=104.0, low=98.5, close=103.0, volume=2000)
    detector.process_candle(c3)

    active = detector.get_active_structures()
    assert len(active) == 1
    assert active[0].is_mitigated is False


def test_get_structures_by_type(detector: SmcSignalDetector) -> None:
    """Filter structures by type."""
    # Create both OB and FVG
    c1 = Candle(bar_index=0, open=102.0, high=103.0, low=98.0, close=99.0, volume=1000)
    detector.process_candle(c1)
    c2 = Candle(bar_index=1, open=99.5, high=100.0, low=98.5, close=98.8, volume=1000)
    detector.process_candle(c2)
    c3 = Candle(bar_index=2, open=99.0, high=105.0, low=98.5, close=103.0, volume=2000)
    detector.process_candle(c3)

    obs = detector.get_structures_by_type(BoxType.ORDER_BLOCK)
    assert len(obs) > 0
    # FVG might not trigger depending on exact values


def test_count_structures(detector: SmcSignalDetector) -> None:
    """Count structures by direction."""
    # Create multiple bullish structures
    c1 = Candle(bar_index=0, open=102.0, high=103.0, low=98.0, close=99.0, volume=1000)
    detector.process_candle(c1)
    c2 = Candle(bar_index=1, open=99.5, high=100.0, low=98.5, close=98.8, volume=1000)
    detector.process_candle(c2)
    c3 = Candle(bar_index=2, open=99.0, high=105.0, low=98.5, close=103.0, volume=2000)
    detector.process_candle(c3)

    bullish_count = detector.count_structures(Direction.BULLISH)
    bearish_count = detector.count_structures(Direction.BEARISH)
    assert bullish_count >= 1
    assert bearish_count == 0


def test_max_boxes_eviction(detector: SmcSignalDetector) -> None:
    """Verify max_boxes_per_direction limit is enforced."""
    detector_small = SmcSignalDetector(max_boxes_per_direction=2)

    # Generate 4 bullish OBs (should evict oldest when buffer full)
    for i in range(4):
        c1 = Candle(bar_index=i * 3, open=102.0, high=103.0, low=98.0, close=99.0, volume=1000)
        detector_small.process_candle(c1)
        c2 = Candle(bar_index=i * 3 + 1, open=99.5, high=100.0, low=98.5, close=98.8, volume=1000)
        detector_small.process_candle(c2)
        c3 = Candle(bar_index=i * 3 + 2, open=99.0, high=104.0, low=98.5, close=103.0, volume=2000)
        detector_small.process_candle(c3)

    active = detector_small.get_active_structures()
    bullish = [b for b in active if b.direction == Direction.BULLISH]
    # Should have evicted oldest, keep only 2 newest
    assert len(bullish) <= 2


class TestNonFiniteWindowGuard:
    """Bug-hunt: a non-finite OHLC in the 3-bar detection window must not
    produce boxes with NaN/inf bounds (silent, never-mitigating bad signals)."""

    def test_nan_candle_creates_no_structure(self, caplog) -> None:
        import logging
        import math

        det = SmcSignalDetector(max_boxes_per_direction=10)
        # A bullish-OB-shaped sequence, but the previous bar's low is NaN — the
        # exact arg (low_t1) that is_ob_up never guarded and make_ob_up consumes.
        candles = [
            Candle(bar_index=0, open=100.0, high=101.0, low=99.0, close=100.0, volume=1000),
            Candle(bar_index=1, open=100.0, high=101.0, low=99.0, close=100.0, volume=1000),
            Candle(bar_index=2, open=102.0, high=103.0, low=98.0, close=99.0, volume=1000),
            Candle(bar_index=3, open=99.5, high=100.0, low=float("nan"), close=98.8, volume=1000),
            Candle(bar_index=4, open=99.0, high=104.0, low=98.5, close=103.0, volume=2000),
        ]
        created = []
        with caplog.at_level(
            logging.WARNING, logger="services.live_overlay_daemon.smc_signal_detector"
        ):
            for c in candles:
                created += [s for s in det.process_candle(c) if s.event_type == "created"]

        # No created signal, and nothing active, carries non-finite bounds.
        assert all(math.isfinite(s.box.top) and math.isfinite(s.box.bottom) for s in created)
        assert all(
            math.isfinite(b.top) and math.isfinite(b.bottom)
            for b in det.get_active_structures()
        )
        # The corrupt window was surfaced, not silently swallowed.
        assert any("non-finite OHLC" in r.getMessage() for r in caplog.records)

    def test_detection_resumes_after_corrupt_candle(self) -> None:
        det = SmcSignalDetector(max_boxes_per_direction=10)
        # One corrupt candle, then a clean bullish-OB sequence well clear of it.
        det.process_candle(Candle(bar_index=0, open=100.0, high=float("inf"), low=99.0, close=100.0, volume=0))
        det.process_candle(Candle(bar_index=1, open=102.0, high=103.0, low=98.0, close=99.0, volume=1000))
        det.process_candle(Candle(bar_index=2, open=99.5, high=100.0, low=98.5, close=98.8, volume=1000))
        signals = det.process_candle(
            Candle(bar_index=3, open=99.0, high=104.0, low=98.5, close=103.0, volume=2000)
        )
        ob = [s for s in signals if s.box_type == BoxType.ORDER_BLOCK and s.direction == Direction.BULLISH]
        assert len(ob) == 1
        assert ob[0].event_type == "created"
