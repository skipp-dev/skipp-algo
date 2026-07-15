"""Unit tests for services.live_overlay_daemon.github_workflow_bridge helpers."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def reset_workflow_bridge_cache() -> None:
    import services.live_overlay_daemon.github_workflow_bridge as bridge

    bridge._cached_snapshot = None
    bridge._cached_at_monotonic = 0.0
    yield
    bridge._cached_snapshot = None
    bridge._cached_at_monotonic = 0.0


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


def test_fetch_snapshot_separates_status_from_conclusion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import services.live_overlay_daemon.github_workflow_bridge as bridge

    runs_payload = {
        "workflow_runs": [
            {
                "workflow_id": 1,
                "name": "CI",
                "event": "pull_request",
                "status": "queued",
                "conclusion": None,
                "created_at": "2026-06-22T10:00:00Z",
                "run_started_at": None,
                "updated_at": None,
            }
        ]
    }

    monkeypatch.setattr(bridge.config, "github_workflow_repo", lambda: ("o", "r"))
    monkeypatch.setattr(bridge.config, "github_workflow_per_page", lambda: 30)
    monkeypatch.setattr(bridge.config, "github_workflow_timeout_secs", lambda: 5)
    monkeypatch.setattr(bridge.time, "time", lambda: 1_782_122_460.0)
    monkeypatch.setattr(bridge, "_github_request_json", lambda *args, **kwargs: runs_payload)

    snap = bridge._fetch_snapshot("token")
    assert snap["workflows"]
    row = snap["workflows"][0]
    assert row["status"] == "queued"
    assert row["conclusion"] == "unknown"


def _fetch_with_runs(monkeypatch: pytest.MonkeyPatch, runs: list[dict]) -> dict:
    import services.live_overlay_daemon.github_workflow_bridge as bridge

    monkeypatch.setattr(bridge.config, "github_workflow_repo", lambda: ("o", "r"))
    monkeypatch.setattr(bridge.config, "github_workflow_per_page", lambda: 30)
    monkeypatch.setattr(bridge.config, "github_workflow_timeout_secs", lambda: 5)
    monkeypatch.setattr(bridge.time, "time", lambda: 1_782_122_460.0)
    monkeypatch.setattr(
        bridge, "_github_request_json", lambda *a, **k: {"workflow_runs": runs}
    )
    return bridge._fetch_snapshot("token")


def test_latest_success_comes_from_newest_completed_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An in-flight newest run has no verdict yet: latest_success must reflect
    the newest COMPLETED run. Counting in-flight as "not green" made every
    long-running workflow flap the no-green-24h alarm for its whole runtime
    (observed with smc-library-refresh, 2026-07-07)."""
    runs = [
        {"workflow_id": 7, "name": "lib", "event": "schedule", "status": "in_progress",
         "conclusion": None, "created_at": "2026-06-22T10:30:00Z"},
        {"workflow_id": 7, "name": "lib", "event": "schedule", "status": "completed",
         "conclusion": "success", "created_at": "2026-06-22T09:00:00Z"},
    ]
    row = _fetch_with_runs(monkeypatch, runs)["workflows"][0]
    assert row["status"] == "in_progress"  # newest run still drives lifecycle
    assert row["latest_success"] == 1      # verdict from the completed run
    assert "latest_success_final" not in row  # internal marker never leaks


def test_latest_success_zero_when_newest_completed_run_failed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Newest completed = failure; an even older success must NOT win.
    runs = [
        {"workflow_id": 7, "name": "lib", "event": "push", "status": "in_progress",
         "conclusion": None, "created_at": "2026-06-22T10:30:00Z"},
        {"workflow_id": 7, "name": "lib", "event": "push", "status": "completed",
         "conclusion": "failure", "created_at": "2026-06-22T09:00:00Z"},
        {"workflow_id": 7, "name": "lib", "event": "push", "status": "completed",
         "conclusion": "success", "created_at": "2026-06-22T08:00:00Z"},
    ]
    row = _fetch_with_runs(monkeypatch, runs)["workflows"][0]
    assert row["latest_success"] == 0


def test_latest_success_skips_cancelled_to_the_newest_verdict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A merge-train concurrency cancel is NOT a health verdict: the newest
    completed run being ``cancelled`` must not count as "not green". Skip it
    and take the newest run that actually reached success/failure (observed
    2026-07-07: rapid merges cancelled CI runs and flapped the alarm)."""
    runs = [
        {"workflow_id": 3, "name": "CI", "event": "push", "status": "completed",
         "conclusion": "cancelled", "created_at": "2026-06-22T10:30:00Z"},
        {"workflow_id": 3, "name": "CI", "event": "push", "status": "completed",
         "conclusion": "success", "created_at": "2026-06-22T10:00:00Z"},
    ]
    row = _fetch_with_runs(monkeypatch, runs)["workflows"][0]
    assert row["latest_success"] == 1


def test_latest_success_skips_skipped_and_stale_conclusions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # skipped / stale are non-verdict too — only a genuine failure below wins.
    runs = [
        {"workflow_id": 3, "name": "CI", "event": "push", "status": "completed",
         "conclusion": "skipped", "created_at": "2026-06-22T10:30:00Z"},
        {"workflow_id": 3, "name": "CI", "event": "push", "status": "completed",
         "conclusion": "stale", "created_at": "2026-06-22T10:15:00Z"},
        {"workflow_id": 3, "name": "CI", "event": "push", "status": "completed",
         "conclusion": "failure", "created_at": "2026-06-22T10:00:00Z"},
    ]
    row = _fetch_with_runs(monkeypatch, runs)["workflows"][0]
    assert row["latest_success"] == 0


def test_latest_success_stays_zero_when_only_cancelled_runs_seen(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # No verdict anywhere in the window -> conservative 0 (the 24h `for:`
    # absorbs it); a workflow that only ever cancels IS worth surfacing.
    runs = [
        {"workflow_id": 3, "name": "CI", "event": "push", "status": "completed",
         "conclusion": "cancelled", "created_at": "2026-06-22T10:30:00Z"},
        {"workflow_id": 3, "name": "CI", "event": "push", "status": "completed",
         "conclusion": "cancelled", "created_at": "2026-06-22T10:00:00Z"},
    ]
    row = _fetch_with_runs(monkeypatch, runs)["workflows"][0]
    assert row["latest_success"] == 0
    assert "latest_success_final" not in row


def test_timed_out_and_startup_failure_count_as_failure_verdicts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Genuine failure modes (not cancellations) must still read as not-green.
    for bad in ("timed_out", "startup_failure"):
        runs = [
            {"workflow_id": 3, "name": "CI", "event": "push", "status": "completed",
             "conclusion": bad, "created_at": "2026-06-22T10:30:00Z"},
            {"workflow_id": 3, "name": "CI", "event": "push", "status": "completed",
             "conclusion": "success", "created_at": "2026-06-22T10:00:00Z"},
        ]
        row = _fetch_with_runs(monkeypatch, runs)["workflows"][0]
        assert row["latest_success"] == 0, bad


def test_counts_failed_excludes_non_verdict_conclusions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # counts["failed"] -> the CI dashboard's "failed" line. It must mean genuine
    # failures (matching the latest_success verdict), not "every completed run
    # that isn't success": a merge-train cancel / skip / stale is not a failure,
    # it only bumps "seen". Previously all four below counted as failed.
    runs = [
        {"workflow_id": 3, "name": "CI", "event": "push", "status": "completed",
         "conclusion": "cancelled", "created_at": "2026-06-22T10:30:00Z"},
        {"workflow_id": 4, "name": "CI2", "event": "push", "status": "completed",
         "conclusion": "skipped", "created_at": "2026-06-22T10:20:00Z"},
        {"workflow_id": 5, "name": "CI3", "event": "push", "status": "completed",
         "conclusion": "stale", "created_at": "2026-06-22T10:10:00Z"},
        {"workflow_id": 6, "name": "CI4", "event": "push", "status": "completed",
         "conclusion": "failure", "created_at": "2026-06-22T10:00:00Z"},
    ]
    counts = _fetch_with_runs(monkeypatch, runs)["counts"]
    assert counts["seen"] == 4
    assert counts["success"] == 0
    assert counts["failed"] == 1  # only the genuine failure, not cancel/skip/stale


def _capture_fetch_url(monkeypatch: pytest.MonkeyPatch, branch: str) -> dict[str, str]:
    import services.live_overlay_daemon.github_workflow_bridge as bridge

    captured: dict[str, str] = {}

    def _capture(url: str, _token: str, _timeout: int) -> dict[str, object]:
        captured["url"] = url
        return {"workflow_runs": []}

    monkeypatch.setattr(bridge.config, "github_workflow_repo", lambda: ("o", "r"))
    monkeypatch.setattr(bridge.config, "github_workflow_per_page", lambda: 30)
    monkeypatch.setattr(bridge.config, "github_workflow_timeout_secs", lambda: 5)
    monkeypatch.setattr(bridge.config, "github_workflow_branch", lambda: branch)
    monkeypatch.setattr(bridge.time, "time", lambda: 1.0)
    monkeypatch.setattr(bridge, "_github_request_json", _capture)
    bridge._fetch_snapshot("token")
    return captured


def test_fetch_snapshot_scopes_to_main_branch_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    # main-scoped health: a green feature-branch run must not mask a red main run.
    captured = _capture_fetch_url(monkeypatch, "main")
    assert "branch=main" in captured["url"]


def test_fetch_snapshot_tracks_all_branches_when_branch_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Empty branch config restores the pre-2026-07 all-branches behaviour.
    captured = _capture_fetch_url(monkeypatch, "")
    assert "branch=" not in captured["url"]


def test_fetch_snapshot_records_last_success_timestamp(monkeypatch: pytest.MonkeyPatch) -> None:
    import services.live_overlay_daemon.github_workflow_bridge as bridge

    monkeypatch.setattr(bridge.config, "github_workflow_token", lambda: "token")
    monkeypatch.setattr(bridge.config, "github_workflow_repo", lambda: ("o", "r"))
    monkeypatch.setattr(bridge.config, "github_workflow_per_page", lambda: 30)
    monkeypatch.setattr(bridge.config, "github_workflow_timeout_secs", lambda: 5)
    monkeypatch.setattr(bridge.time, "time", lambda: 1_700_000_000.0)
    monkeypatch.setattr(
        bridge,
        "_fetch_snapshot",
        lambda _token: {
            "enabled": 1,
            "ok": 1,
            "fetched_at_unix": 1_700_000_000.0,
            "counts": {"seen": 0, "success": 0, "failed": 0, "in_progress": 0, "queued": 0},
            "latest_run_age_seconds": None,
            "latest_run_duration_seconds": None,
            "workflows": [],
        },
    )

    snap = bridge.snapshot()
    assert snap["last_success_fetched_at_unix"] == 1_700_000_000.0


def test_failed_snapshot_preserves_last_success_timestamp(monkeypatch: pytest.MonkeyPatch) -> None:
    import services.live_overlay_daemon.github_workflow_bridge as bridge

    bridge._cached_snapshot = {
        "enabled": 1,
        "configured": 1,
        "ok": 1,
        "fetched_at_unix": 1_700_000_000.0,
        "last_success_fetched_at_unix": 1_700_000_000.0,
        "counts": {"seen": 5, "success": 4, "failed": 1, "in_progress": 0, "queued": 0},
        "latest_run_age_seconds": 60.0,
        "latest_run_duration_seconds": 120.0,
        "workflows": [],
    }
    bridge._cached_at_monotonic = 0.0

    monkeypatch.setattr(bridge.config, "github_workflow_token", lambda: "token")
    monkeypatch.setattr(bridge.config, "github_workflow_poll_ttl_secs", lambda: 300)
    monkeypatch.setattr(bridge.time, "time", lambda: 1_700_000_300.0)
    monkeypatch.setattr(bridge.time, "monotonic", lambda: 300.0)
    monkeypatch.setattr(
        bridge,
        "_fetch_snapshot",
        lambda _token: (_ for _ in ()).throw(TimeoutError("boom")),
    )

    snap = bridge.snapshot()
    assert snap["ok"] == 1
    assert snap["last_success_fetched_at_unix"] == 1_700_000_000.0
    assert snap["fetched_at_unix"] == 1_700_000_000.0


def test_fetch_error_preserves_last_successful_snapshot(monkeypatch: pytest.MonkeyPatch) -> None:
    """A transient GitHub API failure must not evict the last successful snapshot.

    Without this guard a single failed poll immediately flips the dashboard to
    ok=0/counts=0 even though the previous successful snapshot is still useful.
    """
    import services.live_overlay_daemon.github_workflow_bridge as bridge

    monkeypatch.setattr(bridge.config, "github_workflow_token", lambda: "token")
    monkeypatch.setattr(bridge.config, "github_workflow_poll_ttl_secs", lambda: 0)
    monkeypatch.setattr(bridge.time, "time", lambda: 1_700_000_000.0)
    monkeypatch.setattr(bridge.time, "monotonic", lambda: 200.0)

    def _good_fetch(_token: str) -> dict:
        return {
            "enabled": 1,
            "configured": 1,
            "ok": 1,
            "fetched_at_unix": 1_700_000_000.0,
            "last_success_fetched_at_unix": 1_700_000_000.0,
            "counts": {"seen": 5, "success": 4, "failed": 1, "in_progress": 0, "queued": 0},
            "latest_run_age_seconds": 60.0,
            "latest_run_duration_seconds": 120.0,
            "workflows": [{"id": "1", "name": "CI", "event": "schedule", "phase_code": 3, "latest_success": 1}],
        }

    monkeypatch.setattr(bridge, "_fetch_snapshot", _good_fetch)
    first = bridge.snapshot()
    assert first["ok"] == 1
    assert first["counts"]["seen"] == 5

    def _bad_fetch(_token: str) -> dict:
        raise RuntimeError("github down")

    monkeypatch.setattr(bridge, "_fetch_snapshot", _bad_fetch)
    bridge._cached_at_monotonic = 0.0
    second = bridge.snapshot()
    assert second["ok"] == 1
    assert second["counts"]["seen"] == 5
    assert second["last_success_fetched_at_unix"] == 1_700_000_000.0
