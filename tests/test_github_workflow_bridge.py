"""Unit tests for services.live_overlay_daemon.github_workflow_bridge helpers."""

from __future__ import annotations

import pytest


def test_iso_age_seconds_parses_utc_z_timestamp(monkeypatch: pytest.MonkeyPatch) -> None:
    import services.live_overlay_daemon.github_workflow_bridge as bridge

    # 2026-06-22T10:00:00Z
    fixed_now = 1_782_122_460.0
    monkeypatch.setattr(bridge.time, "time", lambda: fixed_now)

    age = bridge._iso_age_seconds("2026-06-22T10:00:00Z")

    assert age is not None
    assert age == pytest.approx(60.0)


def test_iso_age_seconds_returns_none_on_invalid_timestamp() -> None:
    import services.live_overlay_daemon.github_workflow_bridge as bridge

    assert bridge._iso_age_seconds("not-a-timestamp") is None


def test_duration_seconds_parses_utc_z_timestamps() -> None:
    import services.live_overlay_daemon.github_workflow_bridge as bridge

    duration = bridge._duration_seconds(
        "2026-06-22T10:00:00Z",
        "2026-06-22T10:02:30Z",
    )

    assert duration is not None
    assert duration == pytest.approx(150.0)


def test_duration_seconds_clamps_negative_values_to_zero() -> None:
    import services.live_overlay_daemon.github_workflow_bridge as bridge

    duration = bridge._duration_seconds(
        "2026-06-22T10:03:00Z",
        "2026-06-22T10:02:30Z",
    )

    assert duration == 0.0


def test_snapshot_returns_cached_value_within_ttl(monkeypatch: pytest.MonkeyPatch) -> None:
    import services.live_overlay_daemon.github_workflow_bridge as bridge

    monkeypatch.setattr(bridge.config, "github_workflow_token", lambda: "token")
    monkeypatch.setattr(bridge.config, "github_workflow_poll_ttl_secs", lambda: 60)
    monkeypatch.setattr(bridge.time, "monotonic", lambda: 100.0)

    bridge._cached_snapshot = {
        "enabled": 1,
        "ok": 1,
        "fetched_at_unix": 1.0,
        "counts": {"seen": 1, "success": 1, "failed": 0, "in_progress": 0, "queued": 0},
        "latest_run_age_seconds": 1.0,
        "latest_run_duration_seconds": 2.0,
        "workflows": [],
    }
    bridge._cached_at_monotonic = 99.0

    def _boom_fetch(_token: str) -> dict:
        raise AssertionError("_fetch_snapshot must not be called on cache hit")

    monkeypatch.setattr(bridge, "_fetch_snapshot", _boom_fetch)

    snap = bridge.snapshot()
    assert snap["ok"] == 1
    assert snap["counts"]["seen"] == 1


def test_snapshot_fetch_error_returns_fallback_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    import services.live_overlay_daemon.github_workflow_bridge as bridge

    monkeypatch.setattr(bridge.config, "github_workflow_token", lambda: "token")
    monkeypatch.setattr(bridge.config, "github_workflow_poll_ttl_secs", lambda: 0)
    monkeypatch.setattr(bridge.time, "time", lambda: 1234.0)
    monkeypatch.setattr(bridge.time, "monotonic", lambda: 200.0)

    bridge._cached_snapshot = None
    bridge._cached_at_monotonic = 0.0

    def _raise_fetch(_token: str) -> dict:
        raise RuntimeError("boom")

    monkeypatch.setattr(bridge, "_fetch_snapshot", _raise_fetch)

    snap = bridge.snapshot()
    assert snap["enabled"] == 1
    assert snap["ok"] == 0
    assert snap["error"] == "RuntimeError"
    assert snap["fetched_at_unix"] == 1234.0
