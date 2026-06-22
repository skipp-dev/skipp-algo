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


def test_fetch_snapshot_includes_branch_query_when_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    import services.live_overlay_daemon.github_workflow_bridge as bridge

    monkeypatch.setattr(bridge.config, "github_workflow_repo", lambda: ("skippALGO", "skipp-algo"))
    monkeypatch.setattr(bridge.config, "github_workflow_timeout_secs", lambda: 5)
    monkeypatch.setattr(bridge.config, "github_workflow_per_page", lambda: 30)
    monkeypatch.setattr(bridge.config, "github_workflow_ids", lambda: [])
    monkeypatch.setattr(bridge.config, "github_workflow_branch", lambda: "main")

    captured: dict[str, object] = {}

    def _fake_request_json(url: str, token: str, timeout: int) -> dict[str, object]:
        captured["url"] = url
        captured["token"] = token
        captured["timeout"] = timeout
        return {"workflow_runs": []}

    monkeypatch.setattr(bridge, "_github_request_json", _fake_request_json)

    snap = bridge._fetch_snapshot("token")

    assert snap["ok"] == 1
    assert "branch=main" in str(captured.get("url", ""))
    assert captured["token"] == "token"
    assert captured["timeout"] == 5


def test_fetch_snapshot_omits_branch_query_when_not_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    import services.live_overlay_daemon.github_workflow_bridge as bridge

    monkeypatch.setattr(bridge.config, "github_workflow_repo", lambda: ("skippALGO", "skipp-algo"))
    monkeypatch.setattr(bridge.config, "github_workflow_timeout_secs", lambda: 5)
    monkeypatch.setattr(bridge.config, "github_workflow_per_page", lambda: 30)
    monkeypatch.setattr(bridge.config, "github_workflow_ids", lambda: [])
    monkeypatch.setattr(bridge.config, "github_workflow_branch", lambda: None)

    captured: dict[str, object] = {}

    def _fake_request_json(url: str, token: str, timeout: int) -> dict[str, object]:
        captured["url"] = url
        return {"workflow_runs": []}

    monkeypatch.setattr(bridge, "_github_request_json", _fake_request_json)

    snap = bridge._fetch_snapshot("token")

    assert snap["ok"] == 1
    assert "branch=" not in str(captured.get("url", ""))
