"""Unit tests for the UptimeRobot bridge."""

from __future__ import annotations

import threading
import time
from typing import Any
from unittest.mock import patch

import pytest

from services.live_overlay_daemon import uptimerobot_bridge


@pytest.fixture(autouse=True)
def _reset_bridge_cache() -> None:
    uptimerobot_bridge._cached_snapshot = None
    uptimerobot_bridge._cached_at_monotonic = 0.0
    yield
    uptimerobot_bridge._cached_snapshot = None
    uptimerobot_bridge._cached_at_monotonic = 0.0


def test_status_bucket() -> None:
    assert uptimerobot_bridge._status_bucket(2) == "up"
    assert uptimerobot_bridge._status_bucket(8) == "down"
    assert uptimerobot_bridge._status_bucket(9) == "down"
    assert uptimerobot_bridge._status_bucket(0) == "paused"
    assert uptimerobot_bridge._status_bucket(1) == "unknown"
    assert uptimerobot_bridge._status_bucket(999) == "unknown"


def test_to_float() -> None:
    assert uptimerobot_bridge._to_float("12.5") == 12.5
    assert uptimerobot_bridge._to_float(7) == 7.0
    assert uptimerobot_bridge._to_float(None) is None
    assert uptimerobot_bridge._to_float("n/a") is None


def test_extract_response_time_ms_uses_latest_response_time() -> None:
    monitor: dict[str, Any] = {
        "response_times": [{"value": "123"}],
        "average_response_time": "456",
    }
    assert uptimerobot_bridge._extract_response_time_ms(monitor) == 123.0


def test_extract_response_time_ms_falls_back_to_average() -> None:
    monitor: dict[str, Any] = {"average_response_time": "456"}
    assert uptimerobot_bridge._extract_response_time_ms(monitor) == 456.0


def test_extract_response_time_ms_returns_none_when_missing() -> None:
    assert uptimerobot_bridge._extract_response_time_ms({}) is None


def test_snapshot_returns_disabled_without_api_key() -> None:
    with patch.object(uptimerobot_bridge.config, "uptimerobot_api_key", return_value=""):
        result = uptimerobot_bridge.snapshot()
    assert result["enabled"] == 0
    assert result["ok"] == 0
    assert result["error"] == "missing_api_key"


def _fake_response(body: bytes) -> object:
    class _Response:
        def read(self) -> bytes:
            return body

        def __enter__(self) -> object:
            return self

        def __exit__(self, *args: object) -> None:
            return None

    return _Response()


def test_fetch_snapshot_parses_monitors_and_counts() -> None:
    body = (
        b'{"stat": "ok", "monitors": [\n'
        b'  {"id": 1, "friendly_name": "A", "status": 2, "average_response_time": "50"},\n'
        b'  {"id": 2, "friendly_name": "B", "status": 9, "response_times": [{"value": "80"}]}\n'
        b']}'
    )

    with patch.object(
        uptimerobot_bridge.config,
        "uptimerobot_api_key",
        return_value="secret",
    ), patch.object(
        uptimerobot_bridge.config,
        "uptimerobot_timeout_secs",
        return_value=5,
    ), patch.object(
        uptimerobot_bridge.config,
        "uptimerobot_monitor_ids",
        return_value=[],
    ), patch.object(
        uptimerobot_bridge.urllib.request,
        "urlopen",
        return_value=_fake_response(body),
    ) as mock_urlopen:
        result = uptimerobot_bridge._fetch_snapshot("secret")

    assert result["enabled"] == 1
    assert result["ok"] == 1
    assert result["counts"]["total"] == 2
    assert result["counts"]["up"] == 1
    assert result["counts"]["down"] == 1
    assert result["avg_response_time_ms"] == 65.0
    mock_urlopen.assert_called_once()


def test_snapshot_caches_result() -> None:
    body = b'{"stat": "ok", "monitors": []}'

    with patch.object(
        uptimerobot_bridge.config,
        "uptimerobot_api_key",
        return_value="secret",
    ), patch.object(
        uptimerobot_bridge.config,
        "uptimerobot_timeout_secs",
        return_value=5,
    ), patch.object(
        uptimerobot_bridge.config,
        "uptimerobot_monitor_ids",
        return_value=[],
    ), patch.object(
        uptimerobot_bridge.config,
        "uptimerobot_poll_ttl_secs",
        return_value=300,
    ), patch.object(
        uptimerobot_bridge.urllib.request,
        "urlopen",
        return_value=_fake_response(body),
    ) as mock_urlopen:
        first = uptimerobot_bridge.snapshot()
        second = uptimerobot_bridge.snapshot()

    assert first["ok"] == 1
    assert second["ok"] == 1
    assert mock_urlopen.call_count == 1


def test_snapshot_handles_api_error_gracefully() -> None:
    uptimerobot_bridge._cached_snapshot = None
    uptimerobot_bridge._cached_at_monotonic = 0.0
    with patch.object(
        uptimerobot_bridge.config,
        "uptimerobot_api_key",
        return_value="secret",
    ), patch.object(
        uptimerobot_bridge.config,
        "uptimerobot_poll_ttl_secs",
        return_value=300,
    ), patch.object(
        uptimerobot_bridge.urllib.request,
        "urlopen",
        side_effect=TimeoutError("boom"),
    ):
        result = uptimerobot_bridge.snapshot()

    assert result["enabled"] == 1
    assert result["ok"] == 0
    assert result["error"] == "TimeoutError"


def test_snapshot_coalesces_parallel_fetches() -> None:
    uptimerobot_bridge._cached_snapshot = None
    uptimerobot_bridge._cached_at_monotonic = 0.0

    calls: list[str] = []

    def _slow_fetch(api_key: str) -> dict[str, Any]:
        calls.append(api_key)
        time.sleep(0.05)
        return {
            "enabled": 1,
            "ok": 1,
            "fetched_at_unix": time.time(),
            "counts": {"total": 0, "up": 0, "down": 0, "paused": 0, "unknown": 0},
            "avg_response_time_ms": None,
            "monitors": [],
        }

    with patch.object(
        uptimerobot_bridge.config,
        "uptimerobot_api_key",
        return_value="secret",
    ), patch.object(
        uptimerobot_bridge.config,
        "uptimerobot_poll_ttl_secs",
        return_value=300,
    ), patch.object(
        uptimerobot_bridge,
        "_fetch_snapshot",
        side_effect=_slow_fetch,
    ):
        threads = [threading.Thread(target=uptimerobot_bridge.snapshot) for _ in range(6)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

    assert len(calls) == 1
