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


def test_snapshot_uses_last_good_cache_on_fetch_error(monkeypatch: pytest.MonkeyPatch) -> None:
    import services.live_overlay_daemon.github_workflow_bridge as bridge

    monkeypatch.setattr(bridge.config, "github_workflow_token", lambda: "token")
    monkeypatch.setattr(bridge.config, "github_workflow_poll_ttl_secs", lambda: 30)
    monkeypatch.setattr(bridge.time, "monotonic", lambda: 100.0)

    good = {
        "enabled": 1,
        "ok": 1,
        "fetched_at_unix": 1_700_000_100.0,
        "counts": {
            "seen": 2,
            "success": 1,
            "failed": 1,
            "in_progress": 0,
            "queued": 0,
        },
        "latest_run_age_seconds": 12.0,
        "latest_run_duration_seconds": 30.0,
        "workflows": [],
    }

    monkeypatch.setattr(bridge, "_cached_snapshot", dict(good))
    monkeypatch.setattr(bridge, "_cached_at_monotonic", 0.0)

    def _boom(_token: str) -> dict[str, object]:
        raise RuntimeError("boom")

    monkeypatch.setattr(bridge, "_fetch_snapshot", _boom)

    snap = bridge.snapshot()

    assert snap["ok"] == 1
    assert snap["fetched_at_unix"] == good["fetched_at_unix"]
    assert snap["error"] == "RuntimeError"
    assert snap["cache_fallback"] == 1
    assert bridge._cached_at_monotonic == 100.0
