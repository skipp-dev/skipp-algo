from __future__ import annotations

import services.live_overlay_daemon.github_workflow_bridge as bridge


def test_phase_code_maps_status_and_conclusion() -> None:
    assert bridge._phase_code("queued", None) == 1
    assert bridge._phase_code("in_progress", None) == 2
    assert bridge._phase_code("completed", "success") == 3
    assert bridge._phase_code("completed", "failure") == 4
    assert bridge._phase_code("completed", "cancelled") == 5
    assert bridge._phase_code("completed", "skipped") == 6
    assert bridge._phase_code("completed", "neutral") == 7
    assert bridge._phase_code("completed", "timed_out") == 8
    assert bridge._phase_code("completed", "action_required") == 9
    assert bridge._phase_code("completed", "startup_failure") == 10
    assert bridge._phase_code("completed", "stale") == 11
    assert bridge._phase_code("completed", "unknown") == 0
    assert bridge._phase_code("waiting", None) == 0


def test_iso_age_seconds_uses_utc_epoch(monkeypatch) -> None:
    # 2024-06-21T12:00:00Z -> fixed expected age.
    monkeypatch.setattr(bridge.time, "time", lambda: 1_718_971_200.0)
    age = bridge._iso_age_seconds("2024-06-21T12:00:00Z")
    assert age == 0.0


def test_iso_age_seconds_returns_none_for_invalid_input() -> None:
    assert bridge._iso_age_seconds(None) is None
    assert bridge._iso_age_seconds("") is None
    assert bridge._iso_age_seconds("not-a-date") is None


def test_duration_seconds_uses_utc_epoch() -> None:
    duration = bridge._duration_seconds(
        "2024-06-21T12:00:00Z",
        "2024-06-21T12:02:30Z",
    )
    assert duration == 150.0


def test_duration_seconds_returns_none_for_missing_input() -> None:
    assert bridge._duration_seconds(None, "2024-06-21T12:02:30Z") is None
    assert bridge._duration_seconds("2024-06-21T12:00:00Z", None) is None
    assert bridge._duration_seconds("not-a-date", "2024-06-21T12:02:30Z") is None
