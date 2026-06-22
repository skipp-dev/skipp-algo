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
