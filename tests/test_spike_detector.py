"""Tests for terminal_spike_detector — real-time price spike detection."""

from __future__ import annotations

import math
import time
from unittest.mock import patch

import pytest

from terminal_spike_detector import (
    SpikeDetector,
    SpikeEvent,
    format_spike_description,
    format_time_et,
)

# ═══════════════════════════════════════════════════════════════════════════
# SpikeDetector — core logic
# ═══════════════════════════════════════════════════════════════════════════


class TestSpikeDetectorInit:
    def test_defaults(self) -> None:
        d = SpikeDetector()
        assert d.spike_threshold_pct == 1.0
        assert d.lookback_s == 60.0
        assert d.event_count == 0
        assert d.poll_count == 0
        assert d.symbols_tracked == 0

    def test_custom_params(self) -> None:
        d = SpikeDetector(spike_threshold_pct=2.0, lookback_s=30.0, cooldown_s=60.0)
        assert d.spike_threshold_pct == 2.0
        assert d.lookback_s == 30.0
        assert d.cooldown_s == 60.0


class TestSpikeDetectorUpdate:
    def test_first_poll_returns_no_spikes(self) -> None:
        d = SpikeDetector()
        quotes = [{"symbol": "AAPL", "price": 150.0}]
        result = d.update(quotes)
        assert result == []
        assert d.poll_count == 1
        assert d.symbols_tracked == 1

    def test_spike_detected_after_lookback(self) -> None:
        d = SpikeDetector(spike_threshold_pct=1.0, lookback_s=5.0, cooldown_s=0.0)

        # First poll — record baseline
        now = time.time()
        with patch("terminal_spike_detector.time") as mock_time:
            mock_time.time.return_value = now
            d.update([{"symbol": "TSLA", "price": 100.0}])

        # Second poll — 6s later with 2% price increase
        with patch("terminal_spike_detector.time") as mock_time:
            mock_time.time.return_value = now + 6.0
            result = d.update([{"symbol": "TSLA", "price": 102.0}])

        assert len(result) == 1
        assert result[0].symbol == "TSLA"
        assert result[0].direction == "UP"
        assert result[0].spike_pct == pytest.approx(2.0, abs=0.1)
        assert result[0].price == 102.0

    def test_no_spike_below_threshold(self) -> None:
        d = SpikeDetector(spike_threshold_pct=2.0, lookback_s=5.0, cooldown_s=0.0)

        now = time.time()
        with patch("terminal_spike_detector.time") as mock_time:
            mock_time.time.return_value = now
            d.update([{"symbol": "AAPL", "price": 100.0}])

        with patch("terminal_spike_detector.time") as mock_time:
            mock_time.time.return_value = now + 6.0
            result = d.update([{"symbol": "AAPL", "price": 101.5}])  # +1.5% < 2%

        assert result == []

    def test_downward_spike(self) -> None:
        d = SpikeDetector(spike_threshold_pct=1.0, lookback_s=5.0, cooldown_s=0.0)

        now = time.time()
        with patch("terminal_spike_detector.time") as mock_time:
            mock_time.time.return_value = now
            d.update([{"symbol": "GME", "price": 50.0}])

        with patch("terminal_spike_detector.time") as mock_time:
            mock_time.time.return_value = now + 6.0
            result = d.update([{"symbol": "GME", "price": 48.0}])

        assert len(result) == 1
        assert result[0].direction == "DOWN"
        assert result[0].spike_pct == pytest.approx(-4.0, abs=0.1)

    def test_cooldown_prevents_duplicate(self) -> None:
        d = SpikeDetector(
            spike_threshold_pct=1.0, lookback_s=5.0, cooldown_s=120.0,
        )

        now = time.time()
        with patch("terminal_spike_detector.time") as mock_time:
            mock_time.time.return_value = now
            d.update([{"symbol": "NVDA", "price": 100.0}])

        # First spike
        with patch("terminal_spike_detector.time") as mock_time:
            mock_time.time.return_value = now + 6.0
            result1 = d.update([{"symbol": "NVDA", "price": 105.0}])
        assert len(result1) == 1

        # Second update within cooldown — no new spike
        with patch("terminal_spike_detector.time") as mock_time:
            mock_time.time.return_value = now + 12.0
            result2 = d.update([{"symbol": "NVDA", "price": 110.0}])
        assert result2 == []

    def test_multiple_symbols(self) -> None:
        d = SpikeDetector(spike_threshold_pct=1.0, lookback_s=5.0, cooldown_s=0.0)

        now = time.time()
        quotes = [
            {"symbol": "AAPL", "price": 100.0},
            {"symbol": "MSFT", "price": 200.0},
            {"symbol": "GOOG", "price": 300.0},
        ]
        with patch("terminal_spike_detector.time") as mock_time:
            mock_time.time.return_value = now
            d.update(quotes)

        # Only AAPL and GOOG spike
        quotes2 = [
            {"symbol": "AAPL", "price": 105.0},   # +5%
            {"symbol": "MSFT", "price": 200.5},   # +0.25% (no spike)
            {"symbol": "GOOG", "price": 290.0},   # -3.33%
        ]
        with patch("terminal_spike_detector.time") as mock_time:
            mock_time.time.return_value = now + 6.0
            result = d.update(quotes2)

        assert len(result) == 2
        symbols = {e.symbol for e in result}
        assert symbols == {"AAPL", "GOOG"}

    def test_skips_zero_price(self) -> None:
        d = SpikeDetector()
        result = d.update([{"symbol": "BAD", "price": 0}])
        assert result == []
        assert d.symbols_tracked == 0

    def test_skips_empty_symbol(self) -> None:
        d = SpikeDetector()
        result = d.update([{"symbol": "", "price": 100.0}])
        assert result == []

    def test_events_newest_first(self) -> None:
        d = SpikeDetector(spike_threshold_pct=1.0, lookback_s=5.0, cooldown_s=0.0)
        now = time.time()

        with patch("terminal_spike_detector.time") as mock_time:
            mock_time.time.return_value = now
            d.update([
                {"symbol": "A", "price": 100.0},
                {"symbol": "B", "price": 100.0},
            ])

        with patch("terminal_spike_detector.time") as mock_time:
            mock_time.time.return_value = now + 6.0
            d.update([
                {"symbol": "A", "price": 105.0},
                {"symbol": "B", "price": 110.0},
            ])

        events = d.events
        assert len(events) == 2
        # Both detected at same time, B processed after A so is newer in deque
        assert events[0].symbol == "B"
        assert events[1].symbol == "A"


class TestSpikeDetectorClear:
    def test_clear_resets_state(self) -> None:
        d = SpikeDetector(spike_threshold_pct=1.0, lookback_s=5.0, cooldown_s=0.0)
        now = time.time()

        with patch("terminal_spike_detector.time") as mock_time:
            mock_time.time.return_value = now
            d.update([{"symbol": "X", "price": 100.0}])

        with patch("terminal_spike_detector.time") as mock_time:
            mock_time.time.return_value = now + 6.0
            d.update([{"symbol": "X", "price": 110.0}])

        assert d.event_count == 1
        d.clear()
        assert d.event_count == 0
        assert d.poll_count == 0
        assert d.symbols_tracked == 0


class TestSpikeDetectorPruneOldEvents:
    def test_old_events_pruned(self) -> None:
        d = SpikeDetector(
            spike_threshold_pct=1.0,
            lookback_s=5.0,
            cooldown_s=0.0,
            max_event_age_s=60.0,
        )
        now = time.time()

        with patch("terminal_spike_detector.time") as mock_time:
            mock_time.time.return_value = now
            d.update([{"symbol": "OLD", "price": 100.0}])

        with patch("terminal_spike_detector.time") as mock_time:
            mock_time.time.return_value = now + 6.0
            d.update([{"symbol": "OLD", "price": 110.0}])

        assert d.event_count == 1

        # 70 seconds later — event should be pruned
        with patch("terminal_spike_detector.time") as mock_time:
            mock_time.time.return_value = now + 76.0
            d.update([{"symbol": "NEW", "price": 100.0}])

        assert d.event_count == 0  # OLD event pruned, NEW has no spike yet

    def test_large_lookback_window_still_detects_spike(self) -> None:
        # Regression for RISK C: a fixed count-based buffer can silently
        # disable detection when lookback_s exceeds its time span.
        d = SpikeDetector(spike_threshold_pct=1.0, lookback_s=300.0, cooldown_s=0.0)
        now = time.time()

        for i in range(302):
            price = 110.0 if i == 301 else 100.0
            with patch("terminal_spike_detector.time") as mock_time:
                mock_time.time.return_value = now + float(i)
                result = d.update([{"symbol": "LONG", "price": price}])

        assert len(result) == 1
        assert result[0].symbol == "LONG"
        assert result[0].direction == "UP"
        assert result[0].spike_pct == pytest.approx(10.0, abs=0.1)


# ═══════════════════════════════════════════════════════════════════════════
# SpikeEvent
# ═══════════════════════════════════════════════════════════════════════════


class TestSpikeEvent:
    def _make_event(self, direction: str = "UP", spike_pct: float = 2.0) -> SpikeEvent:
        return SpikeEvent(
            symbol="TEST",
            direction=direction,
            spike_pct=spike_pct,
            price=100.0,
            prev_price=98.0,
            change_pct=1.5,
            change=1.5,
            volume=1000000,
            name="Test Corp",
            asset_type="STOCK",
            ts=time.time(),
        )

    def test_icon_up(self) -> None:
        e = self._make_event("UP")
        assert e.icon == "🟢"

    def test_icon_down(self) -> None:
        e = self._make_event("DOWN")
        assert e.icon == "🔴"

    def test_age_s(self) -> None:
        e = SpikeEvent(
            symbol="T", direction="UP", spike_pct=1.0, price=10.0,
            prev_price=9.9, change_pct=0.5, change=0.05, volume=100,
            name="", asset_type="STOCK", ts=time.time() - 30,
        )
        assert e.age_s >= 29.0


# ═══════════════════════════════════════════════════════════════════════════
# Formatters
# ═══════════════════════════════════════════════════════════════════════════


class TestFormatSpikeDescription:
    def test_up_spike(self) -> None:
        e = SpikeEvent(
            symbol="AAPL", direction="UP", spike_pct=1.5, price=150.0,
            prev_price=147.78, change_pct=2.1234, change=3.12,
            volume=5000000, name="Apple Inc", asset_type="STOCK",
            ts=time.time(),
        )
        desc = format_spike_description(e)
        assert "Price Spike UP" in desc
        assert "+1.5%" in desc
        assert "< 1 minute" in desc
        assert "150" in desc

    def test_down_spike(self) -> None:
        e = SpikeEvent(
            symbol="GME", direction="DOWN", spike_pct=-3.2, price=20.0,
            prev_price=20.66, change_pct=-5.0, change=-1.05,
            volume=10000000, name="GameStop", asset_type="STOCK",
            ts=time.time(),
        )
        desc = format_spike_description(e)
        assert "Price Spike DOWN" in desc
        assert "-3.2%" in desc


class TestFormatTimeEt:
    def test_returns_string(self) -> None:
        result = format_time_et(time.time())
        assert isinstance(result, str)
        # Should contain AM or PM
        assert "AM" in result or "PM" in result


# ═══════════════════════════════════════════════════════════════════════════
# Non-finite input hardening (regression)
# ═══════════════════════════════════════════════════════════════════════════


class TestNonFiniteInputs:
    """Regression tests: NaN/inf in provider payloads must never crash the
    poll loop nor enter the buffer / emitted events.

    Background
    ----------
    FMP occasionally returns ``"nan"``/``null``/oversized numerics for thinly
    traded tickers. Two bugs existed before the ``math.isfinite`` guard in
    ``_safe_float``:

    * BUG A — a spike-triggering quote with ``volume`` NaN/inf crashed
      ``update()`` via ``int(float("nan"))`` (``ValueError``) /
      ``int(float("inf"))`` (``OverflowError``), aborting the whole poll.
    * BUG B — ``price = NaN`` slipped past the ``price <= 0`` guard (NaN
      comparisons are always False), poisoned the price buffer, and produced
      a phantom ``DOWN`` spike with ``spike_pct == nan``.
    """

    @pytest.mark.parametrize("bad_volume", [float("nan"), float("inf"), "nan", "inf"])
    def test_non_finite_volume_does_not_crash(self, bad_volume) -> None:
        # BUG A regression.
        d = SpikeDetector(spike_threshold_pct=1.0, lookback_s=5.0, cooldown_s=0.0)
        now = time.time()
        with patch("terminal_spike_detector.time") as mock_time:
            mock_time.time.return_value = now
            d.update([{"symbol": "TSLA", "price": 100.0, "volume": 1}])

        with patch("terminal_spike_detector.time") as mock_time:
            mock_time.time.return_value = now + 6.0
            result = d.update([{"symbol": "TSLA", "price": 105.0, "volume": bad_volume}])

        assert len(result) == 1
        assert result[0].volume == 0  # coerced to default, not crashed

    @pytest.mark.parametrize("bad_price", [float("nan"), float("inf"), float("-inf")])
    def test_non_finite_price_is_skipped(self, bad_price) -> None:
        # BUG B regression — behaves like price <= 0 (skipped, not tracked).
        d = SpikeDetector(spike_threshold_pct=1.0, lookback_s=5.0, cooldown_s=0.0)
        result = d.update([{"symbol": "NANP", "price": bad_price}])
        assert result == []
        assert d.symbols_tracked == 0

    def test_nan_price_does_not_poison_buffer(self) -> None:
        # BUG B regression — a NaN observation must not produce a later
        # phantom spike with NaN fields once a real price arrives.
        d = SpikeDetector(spike_threshold_pct=1.0, lookback_s=5.0, cooldown_s=0.0)
        now = time.time()
        with patch("terminal_spike_detector.time") as mock_time:
            mock_time.time.return_value = now
            d.update([{"symbol": "POI", "price": float("nan")}])

        with patch("terminal_spike_detector.time") as mock_time:
            mock_time.time.return_value = now + 6.0
            result = d.update([{"symbol": "POI", "price": 100.0}])

        assert result == []  # first real price = new baseline, no spike

    @pytest.mark.parametrize("bad_changes", [float("nan"), float("inf")])
    def test_non_finite_change_fields_coerced(self, bad_changes) -> None:
        # A spike with NaN/inf changesPercentage/change must emit finite fields.
        d = SpikeDetector(spike_threshold_pct=1.0, lookback_s=5.0, cooldown_s=0.0)
        now = time.time()
        with patch("terminal_spike_detector.time") as mock_time:
            mock_time.time.return_value = now
            d.update([{"symbol": "AMC", "price": 10.0}])

        with patch("terminal_spike_detector.time") as mock_time:
            mock_time.time.return_value = now + 6.0
            result = d.update([{
                "symbol": "AMC", "price": 11.0,
                "changesPercentage": bad_changes, "change": bad_changes,
            }])

        assert len(result) == 1
        assert math.isfinite(result[0].change_pct)
        assert math.isfinite(result[0].change)

    def test_safe_float_rejects_non_finite(self) -> None:
        from terminal_spike_detector import _safe_float

        assert _safe_float(float("nan")) == 0.0
        assert _safe_float(float("inf")) == 0.0
        assert _safe_float(float("-inf")) == 0.0
        assert _safe_float("nan", 42.0) == 42.0
        assert _safe_float(123.5) == 123.5  # finite values unaffected
