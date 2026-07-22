"""Reconnect, circuit-breaker, and internal metric tests for feed.py.

These tests exercise the _run_feed_loop error-handling paths without opening
a real Databento connection by mocking db.Live so its iterator raises the
exceptions we want to verify.
"""
from __future__ import annotations

import logging
import queue
import threading
import time
from collections.abc import Callable
from types import ModuleType
from typing import Any
from unittest.mock import MagicMock, patch

import databento as db
import pytest


def _reload_feed_module() -> ModuleType:
    """Import a fresh copy of feed.py so each test sees clean module globals."""
    import importlib

    import services.live_overlay_daemon.cache as cache
    import services.live_overlay_daemon.feed as feed

    # feed._run_feed_loop mutates cache module state; reset it so tests remain
    # order-independent when the feed module is reloaded.
    cache.init_bar_cache(rolling_bars=60, max_symbols=2000)
    cache.set_overlay({})
    with cache._vix_lock:
        cache._vix_level = None

    importlib.reload(feed)
    return feed


def _patch_reconnect_delays(feed: ModuleType) -> None:
    """Shrink reconnect delays so tests run in milliseconds, not minutes."""
    feed._RECONNECT_DELAY_SECS = 0.05
    feed._RECONNECT_BACKOFF_SECS = 0.05


def _run_feed_loop_until(
    feed: ModuleType,
    *,
    until: Callable[[], bool],
    max_runtime: float = 3.0,
) -> None:
    """Run _run_feed_loop + _run_ingest_loop until *until()* is true or timeout.

    Since PR #2879 the feed thread only enqueues bars; an ingest thread is
    required to drain the queue and push bars into the cache. Create the queue
    here so tests that call this helper directly do not silently drop bars.
    """
    stop = threading.Event()
    if feed._runtime.get("ingest_queue") is None:
        feed._runtime["ingest_queue"] = queue.Queue(maxsize=feed.config.ingest_queue_max())
        feed._runtime["ingest_queue_max"] = feed.config.ingest_queue_max()

    ingest_thread = threading.Thread(
        target=feed._run_ingest_loop, args=(stop,), daemon=True, name="test-ingest"
    )
    ingest_thread.start()
    feed_thread = threading.Thread(
        target=feed._run_feed_loop, args=(stop,), daemon=True, name="test-feed"
    )
    feed_thread.start()

    deadline = time.monotonic() + max_runtime
    while feed_thread.is_alive() and ingest_thread.is_alive() and time.monotonic() < deadline:
        if until():
            break
        stop.wait(0.05)

    stop.set()
    feed_thread.join(timeout=2)
    ingest_thread.join(timeout=2)
    assert not feed_thread.is_alive(), "feed loop thread did not stop within timeout"
    assert not ingest_thread.is_alive(), "ingest loop thread did not stop within timeout"


class FakeLive:
    """Minimal stand-in for db.Live that yields records or raises on iteration."""

    def __init__(self, sequence: list[Any]) -> None:
        self.sequence = list(sequence)
        self.stop = MagicMock()
        self.subscribe = MagicMock()

    def __iter__(self):
        for item in self.sequence:
            if isinstance(item, Exception):
                raise item
            yield item


def _live_factory(sequence: list[Any]):
    """Return a fresh FakeLive for every db.Live() call (reconnect simulation)."""
    return FakeLive(sequence)


class SymbolMappingMsg:
    """Fake Databento symbol-mapping record."""
    instrument_id = 1
    stype_out_symbol = "AAPL"
    raw_symbol = "AAPL"


class OHLCV_1m:
    """Fake Databento OHLCV record (type name must contain OHLCV)."""
    instrument_id = 1
    open = 1_000_000_000
    high = 1_100_000_000
    low = 900_000_000
    close = 1_050_000_000
    volume = 100
    ts_event = 1


class TestFeedReconnectAndCircuitBreaker:
    """_run_feed_loop reconnects on BentoError and trips the circuit breaker."""

    def test_bento_error_increments_bento_errors_metric(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DATABENTO_API_KEY", "dummy-key")
        monkeypatch.setenv("OVERLAY_MAX_FEED_FAILURES", "5")
        feed = _reload_feed_module()
        _patch_reconnect_delays(feed)

        failure = db.BentoError("connection reset")
        sequence = [failure]

        with patch.object(db, "Live", side_effect=lambda **_: _live_factory(sequence)):
            _run_feed_loop_until(
                feed,
                until=lambda: feed.metrics_snapshot()["bento_errors"] >= 2,
                max_runtime=2.0,
            )

        snapshot = feed.metrics_snapshot()
        assert snapshot["bento_errors"] >= 2
        assert snapshot["reconnect_attempts"] >= 1

    def test_consecutive_failures_trip_circuit_breaker(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DATABENTO_API_KEY", "dummy-key")
        monkeypatch.setenv("OVERLAY_MAX_FEED_FAILURES", "3")
        feed = _reload_feed_module()
        _patch_reconnect_delays(feed)

        failure = db.BentoError("persistent failure")

        def make_client(**_):
            client = FakeLive([])
            client.subscribe.side_effect = failure
            return client

        with patch.object(db, "Live", side_effect=make_client):
            _run_feed_loop_until(
                feed,
                until=lambda: feed.metrics_snapshot()["circuit_breakers"] >= 1,
                max_runtime=2.0,
            )

        snapshot = feed.metrics_snapshot()
        assert snapshot["circuit_breakers"] == 1
        assert snapshot["bento_errors"] >= 3
        assert not feed._feed_ready.is_set()

    def test_unexpected_error_increments_unexpected_errors_metric(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DATABENTO_API_KEY", "dummy-key")
        monkeypatch.setenv("OVERLAY_MAX_FEED_FAILURES", "5")
        feed = _reload_feed_module()
        _patch_reconnect_delays(feed)

        failure = RuntimeError("boom")
        sequence = [failure]

        with patch.object(db, "Live", side_effect=lambda **_: _live_factory(sequence)):
            _run_feed_loop_until(
                feed,
                until=lambda: feed.metrics_snapshot()["unexpected_errors"] >= 2,
                max_runtime=2.0,
            )

        snapshot = feed.metrics_snapshot()
        assert snapshot["unexpected_errors"] >= 2
        assert snapshot["reconnect_attempts"] >= 1

    def test_bar_processed_while_connected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A SymbolMappingMsg + OHLCV record makes it through to the bar cache."""
        monkeypatch.setenv("DATABENTO_API_KEY", "dummy-key")
        monkeypatch.setenv("OVERLAY_MAX_FEED_FAILURES", "5")
        feed = _reload_feed_module()
        _patch_reconnect_delays(feed)

        # Queue-based architecture: feed loop enqueues, ingest loop applies to cache.
        feed._runtime["ingest_queue"] = queue.Queue(maxsize=32)
        feed._runtime["ingest_queue_max"] = 32

        sequence = [SymbolMappingMsg(), OHLCV_1m()]

        stop = threading.Event()
        feed_thread = threading.Thread(
            target=feed._run_feed_loop, args=(stop,), daemon=True, name="test-feed"
        )
        ingest_thread = threading.Thread(
            target=feed._run_ingest_loop, args=(stop,), daemon=True, name="test-ingest"
        )

        with patch.object(db, "Live", side_effect=lambda **_: _live_factory(sequence)):
            feed_thread.start()
            ingest_thread.start()
            deadline = time.monotonic() + 2.0
            while time.monotonic() < deadline and feed.last_bar_age_secs() is None:
                stop.wait(0.05)
            stop.set()
            feed_thread.join(timeout=2)
            ingest_thread.join(timeout=2)
            assert not feed_thread.is_alive(), "feed loop thread did not stop within timeout"
            assert not ingest_thread.is_alive(), "ingest loop thread did not stop within timeout"

        assert feed.last_bar_age_secs() is not None
        assert feed.metrics_snapshot()["bento_errors"] == 0


class TestFeedMissingApiKey:
    """Missing DATABENTO_API_KEY is a non-retryable fatal config error."""

    def test_missing_api_key_breaks_feed_loop(self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
        monkeypatch.delenv("DATABENTO_API_KEY", raising=False)
        feed = _reload_feed_module()
        monkeypatch.setattr(
            feed.config,
            "databento_api_key",
            lambda: (_ for _ in ()).throw(RuntimeError("missing DATABENTO_API_KEY")),
        )

        with caplog.at_level(logging.CRITICAL):
            _run_feed_loop_until(feed, until=lambda: False, max_runtime=1.0)

        assert "Non-retryable feed configuration error" in caplog.text
        assert not feed._feed_ready.is_set()


class TestFeedBackpressureDropCadence:
    """Drop warning cadence must be driven by drop count, not pushed-bar count."""

    def test_queue_drop_counter_increments_and_warns_on_first_and_100th_drop(self) -> None:
        feed = _reload_feed_module()

        with feed._backpressure_lock:
            feed._backpressure["ingest_queue_dropped_total"] = 0.0

        dropped_total = feed._record_queue_drop()
        assert dropped_total == 1.0
        assert feed._should_log_queue_drop_warning(dropped_total) is True

        for _ in range(98):
            dropped_total = feed._record_queue_drop()
            assert feed._should_log_queue_drop_warning(dropped_total) is False

        dropped_total = feed._record_queue_drop()
        assert dropped_total == 100.0
        assert feed._should_log_queue_drop_warning(dropped_total) is True


class TestFeedReadyOwnership:
    """F2.1: only the feed loop may arm readiness — a queued bar must not."""

    def test_ingest_loop_does_not_rearm_feed_ready_after_disconnect(self) -> None:
        """A bar queued before a disconnect must not make /health report ready.

        The feed loop clears _feed_ready on BentoError, but bars enqueued before
        the failure are still in the queue. If the ingest loop armed readiness
        while draining them it would also stamp _last_bar_at, so the staleness
        check in is_ready() could not catch it either.
        """
        feed = _reload_feed_module()

        feed._feed_ready.clear()
        ingest_queue: queue.Queue[Any] = queue.Queue(maxsize=8)
        ingest_queue.put(("AAPL", feed._record_to_bar(OHLCV_1m()), time.monotonic()))
        feed._runtime["ingest_queue"] = ingest_queue

        stop = threading.Event()
        ingest_thread = threading.Thread(
            target=feed._run_ingest_loop, args=(stop,), daemon=True, name="test-ingest"
        )
        ingest_thread.start()
        try:
            ingest_queue.join()
        finally:
            stop.set()
            ingest_thread.join(timeout=2)

        assert not ingest_thread.is_alive(), "ingest loop thread did not stop within timeout"
        # Proves the loop really drained the bar — without this the assertions
        # below would also pass on an ingest loop that did nothing at all.
        assert feed.last_bar_age_secs() is not None, "queued bar was never ingested"
        assert not feed._feed_ready.is_set(), (
            "ingest loop re-armed _feed_ready from a bar queued before the disconnect"
        )
        assert not feed.is_ready(), "/health must not report ready while the feed is down"


class OHLCVUnknownInstrument:
    """OHLCV record whose instrument_id never appears in the symmap (sym=None drop)."""

    instrument_id = 999
    open = 1_000_000_000
    high = 1_100_000_000
    low = 900_000_000
    close = 1_050_000_000
    volume = 100
    ts_event = 1


class OHLCVUnparseable:
    """OHLCV-typed record with a mapped symbol but none of the OHLC price
    attributes, so _record_to_bar returns None (bar=None drop)."""

    instrument_id = 1
    volume = 100


class TestFeedDropCounters:
    """Truth-audit F-2: sym=None / bar=None drops were logged at most three
    times per connection and then silently swallowed — no metric moved, so a
    partial symbology gap (e.g. new listings missing from SymbolMappingMsg)
    dropped those symbols' bars with zero operator visibility. These pins
    require both drop classes to (a) be seeded at 0 so the hermetic exporter
    render and rate()/increase() see them from boot, and (b) increment on the
    corresponding drop."""

    def test_drop_counters_are_seeded_at_zero(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DATABENTO_API_KEY", "dummy-key")
        feed = _reload_feed_module()
        snapshot = feed.metrics_snapshot()
        assert snapshot.get("sym_none_drops_total") == 0
        assert snapshot.get("bar_none_drops_total") == 0

    def test_sym_none_and_bar_none_drops_increment_counters(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("DATABENTO_API_KEY", "dummy-key")
        monkeypatch.setenv("OVERLAY_MAX_FEED_FAILURES", "5")
        feed = _reload_feed_module()
        _patch_reconnect_delays(feed)

        sequence = [
            SymbolMappingMsg(),
            OHLCVUnknownInstrument(),  # unmapped instrument -> sym=None drop
            OHLCVUnparseable(),        # mapped but priceless -> bar=None drop
            OHLCV_1m(),                # healthy record still flows
        ]

        with patch.object(db, "Live", side_effect=lambda **_: _live_factory(sequence)):
            _run_feed_loop_until(
                feed,
                until=lambda: (
                    feed.metrics_snapshot().get("sym_none_drops_total", 0) >= 1
                    and feed.metrics_snapshot().get("bar_none_drops_total", 0) >= 1
                ),
                max_runtime=2.0,
            )

        snapshot = feed.metrics_snapshot()
        assert snapshot.get("sym_none_drops_total", 0) >= 1, "unmapped-instrument drop not counted"
        assert snapshot.get("bar_none_drops_total", 0) >= 1, "unparseable-bar drop not counted"
        # The healthy record must still have been ingested — the counters must
        # observe drops, not cause them.
        assert feed.last_bar_age_secs() is not None, "healthy bar was never ingested"
