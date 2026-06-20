"""Reconnect, circuit-breaker, and internal metric tests for feed.py.

These tests exercise the _run_feed_loop error-handling paths without opening
a real Databento connection by mocking db.Live so its iterator raises the
exceptions we want to verify.
"""
from __future__ import annotations

import logging
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

    import services.live_overlay_daemon.feed as feed

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
    """Run _run_feed_loop in a daemon thread until *until()* is true or timeout."""
    stop = threading.Event()
    thread = threading.Thread(
        target=feed._run_feed_loop, args=(stop,), daemon=True, name="test-feed"
    )
    thread.start()
    deadline = time.monotonic() + max_runtime
    while thread.is_alive() and time.monotonic() < deadline:
        if until():
            break
        stop.wait(0.05)
    stop.set()
    thread.join(timeout=2)


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
        assert snapshot["bento_errors"] >= 1
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
        assert snapshot["unexpected_errors"] >= 1
        assert snapshot["reconnect_attempts"] >= 1

    def test_bar_processed_while_connected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A SymbolMappingMsg + OHLCV record makes it through to the bar cache."""
        monkeypatch.setenv("DATABENTO_API_KEY", "dummy-key")
        monkeypatch.setenv("OVERLAY_MAX_FEED_FAILURES", "5")
        feed = _reload_feed_module()
        _patch_reconnect_delays(feed)

        sequence = [SymbolMappingMsg(), OHLCV_1m()]

        with patch.object(db, "Live", side_effect=lambda **_: _live_factory(sequence)):
            _run_feed_loop_until(
                feed,
                until=lambda: feed.last_bar_age_secs() is not None,
                max_runtime=2.0,
            )

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
