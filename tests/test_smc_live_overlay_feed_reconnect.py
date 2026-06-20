"""Tests for feed.py reconnect, circuit-breaker, and metrics behaviour."""
from __future__ import annotations

import logging
import threading
from typing import Any

import databento as db
import pytest

import services.live_overlay_daemon.feed as feed_mod


class _FailingLive:
    """Drop-in replacement for db.Live that always raises during subscribe."""

    def __init__(self, key: str) -> None:
        self.key = key
        self.subscribe_calls: list[dict[str, Any]] = []
        self._stopped = False

    def subscribe(self, **kwargs: Any) -> None:
        self.subscribe_calls.append(kwargs)
        raise db.BentoError("simulated connection failure")

    def __iter__(self):
        raise db.BentoError("simulated iteration failure")

    def stop(self) -> None:
        self._stopped = True


class TestFeedReconnectLoop:
    """_run_feed_loop reconnect logic and circuit-breaker."""

    def test_bento_error_triggers_reconnect_and_circuit_breaker(
        self,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """On repeated BentoError the loop reconnects, then trips the breaker."""
        stop = threading.Event()
        monkeypatch.setattr(feed_mod.config, "databento_api_key", lambda: "dummy")
        monkeypatch.setattr(feed_mod.config, "max_feed_failures", lambda: 3)
        monkeypatch.setattr(feed_mod.config, "rolling_bars", lambda: 10)
        monkeypatch.setattr(feed_mod.config, "max_symbols", lambda: 100)
        monkeypatch.setattr(feed_mod, "_RECONNECT_DELAY_SECS", 0)
        monkeypatch.setattr(feed_mod, "_RECONNECT_BACKOFF_SECS", 0)
        monkeypatch.setattr(feed_mod.db, "Live", _FailingLive)

        # Reset shared metrics/ready state.
        monkeypatch.setattr(feed_mod, "_metrics", {
            "reconnect_attempts": 0,
            "bento_errors": 0,
            "unexpected_errors": 0,
            "circuit_breakers": 0,
            "partial_restarts": 0,
        })
        feed_mod._feed_ready.set()

        with caplog.at_level(logging.WARNING):
            feed_mod._run_feed_loop(stop)

        assert not feed_mod._feed_ready.is_set()
        snapshot = feed_mod.metrics_snapshot()
        assert snapshot["bento_errors"] == 3
        assert snapshot["reconnect_attempts"] == 2  # after failures 1 and 2
        assert snapshot["circuit_breakers"] == 1
        assert "circuit-breaker triggered" in caplog.text

    def test_feed_ready_cleared_during_reconnect(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """_feed_ready must be cleared while the feed is disconnected."""
        stop = threading.Event()
        monkeypatch.setattr(feed_mod.config, "databento_api_key", lambda: "dummy")
        monkeypatch.setattr(feed_mod.config, "max_feed_failures", lambda: 3)
        monkeypatch.setattr(feed_mod.config, "rolling_bars", lambda: 10)
        monkeypatch.setattr(feed_mod.config, "max_symbols", lambda: 100)
        monkeypatch.setattr(feed_mod, "_RECONNECT_DELAY_SECS", 0)
        monkeypatch.setattr(feed_mod, "_RECONNECT_BACKOFF_SECS", 0)
        monkeypatch.setattr(feed_mod.db, "Live", _FailingLive)
        feed_mod._feed_ready.set()

        feed_mod._run_feed_loop(stop)

        assert not feed_mod._feed_ready.is_set()


class TestFeedMetricsSnapshot:
    """feed.metrics_snapshot exposes real counters across reconnects."""

    def test_metrics_update_during_reconnect_loop(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Counters for bento_errors and reconnect_attempts reflect loop state."""
        stop = threading.Event()
        monkeypatch.setattr(feed_mod.config, "databento_api_key", lambda: "dummy")
        monkeypatch.setattr(feed_mod.config, "max_feed_failures", lambda: 2)
        monkeypatch.setattr(feed_mod.config, "rolling_bars", lambda: 10)
        monkeypatch.setattr(feed_mod.config, "max_symbols", lambda: 100)
        monkeypatch.setattr(feed_mod, "_RECONNECT_DELAY_SECS", 0)
        monkeypatch.setattr(feed_mod, "_RECONNECT_BACKOFF_SECS", 0)
        monkeypatch.setattr(feed_mod.db, "Live", _FailingLive)
        monkeypatch.setattr(feed_mod, "_metrics", {
            "reconnect_attempts": 0,
            "bento_errors": 0,
            "unexpected_errors": 0,
            "circuit_breakers": 0,
            "partial_restarts": 0,
        })

        feed_mod._run_feed_loop(stop)

        snapshot = feed_mod.metrics_snapshot()
        assert snapshot["bento_errors"] == 2
        assert snapshot["circuit_breakers"] == 1
