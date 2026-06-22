"""Unit tests for services.live_overlay_daemon.uptimerobot_bridge helpers."""

from __future__ import annotations

import pytest


def test_snapshot_uses_last_good_cache_on_fetch_error(monkeypatch: pytest.MonkeyPatch) -> None:
    import services.live_overlay_daemon.uptimerobot_bridge as bridge

    monkeypatch.setattr(bridge.config, "uptimerobot_api_key", lambda: "token")
    monkeypatch.setattr(bridge.config, "uptimerobot_poll_ttl_secs", lambda: 30)
    monkeypatch.setattr(bridge.time, "monotonic", lambda: 200.0)

    good = {
        "enabled": 1,
        "ok": 1,
        "fetched_at_unix": 1_700_000_200.0,
        "counts": {"total": 1, "up": 1, "down": 0, "paused": 0, "unknown": 0},
        "avg_response_time_ms": 95.0,
        "monitors": [{"id": "1", "up": 1, "status_code": 2, "response_time_ms": 95.0}],
    }

    monkeypatch.setattr(bridge, "_cached_snapshot", dict(good))
    monkeypatch.setattr(bridge, "_cached_at_monotonic", 0.0)

    def _boom(_api_key: str) -> dict[str, object]:
        raise RuntimeError("boom")

    monkeypatch.setattr(bridge, "_fetch_snapshot", _boom)

    snap = bridge.snapshot()

    assert snap["ok"] == 1
    assert snap["fetched_at_unix"] == good["fetched_at_unix"]
    assert snap["error"] == "RuntimeError"
    assert snap["cache_fallback"] == 1
    assert bridge._cached_at_monotonic == 200.0
