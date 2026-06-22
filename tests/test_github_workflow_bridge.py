"""Unit tests for the GitHub workflow bridge."""

from __future__ import annotations

import threading
import time
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import patch

import pytest

from services.live_overlay_daemon import github_workflow_bridge


@pytest.fixture(autouse=True)
def _reset_bridge_cache() -> None:
    github_workflow_bridge._cached_snapshot = None
    github_workflow_bridge._cached_at_monotonic = 0.0
    yield
    github_workflow_bridge._cached_snapshot = None
    github_workflow_bridge._cached_at_monotonic = 0.0


def test_phase_code_mapping() -> None:
    assert github_workflow_bridge._phase_code("queued", None) == 1
    assert github_workflow_bridge._phase_code("in_progress", None) == 2
    assert github_workflow_bridge._phase_code("completed", "success") == 3
    assert github_workflow_bridge._phase_code("completed", "failure") == 4
    assert github_workflow_bridge._phase_code("completed", "cancelled") == 5
    assert github_workflow_bridge._phase_code("completed", "skipped") == 6
    assert github_workflow_bridge._phase_code("completed", "neutral") == 7
    assert github_workflow_bridge._phase_code("completed", "timed_out") == 8
    assert github_workflow_bridge._phase_code("completed", "action_required") == 9
    assert github_workflow_bridge._phase_code("completed", "startup_failure") == 10
    assert github_workflow_bridge._phase_code("completed", "stale") == 11
    assert github_workflow_bridge._phase_code("completed", "unknown") == 0
    assert github_workflow_bridge._phase_code("weird", None) == 0


def test_iso_age_seconds() -> None:
    one_hour_ago = (datetime.now(UTC) - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    age = github_workflow_bridge._iso_age_seconds(one_hour_ago)
    assert age is not None and 3500 < age < 3700
    assert github_workflow_bridge._iso_age_seconds(None) is None
    assert github_workflow_bridge._iso_age_seconds("") is None
    assert github_workflow_bridge._iso_age_seconds("not-a-date") is None


def test_duration_seconds() -> None:
    assert github_workflow_bridge._duration_seconds(
        "2026-06-21T12:00:00Z", "2026-06-21T12:00:30Z"
    ) == pytest.approx(30.0, abs=1.0)
    assert github_workflow_bridge._duration_seconds(None, "2026-06-21T12:00:30Z") is None


def _fake_response(body: bytes) -> object:
    class _Response:
        def read(self) -> bytes:
            return body

        def __enter__(self) -> object:
            return self

        def __exit__(self, *args: object) -> None:
            return None

    return _Response()


def test_github_request_json_uses_auth_headers() -> None:
    body = b'{"total_count": 0, "workflow_runs": []}'

    with patch.object(
        github_workflow_bridge.urllib.request,
        "urlopen",
        return_value=_fake_response(body),
    ) as mock_urlopen:
        result = github_workflow_bridge._github_request_json(
            "https://api.github.com/repos/owner/repo/actions/runs",
            "token123",
            5,
        )

    assert result == {"total_count": 0, "workflow_runs": []}
    request = mock_urlopen.call_args[0][0]
    assert request.headers["Authorization"] == "Bearer token123"
    assert request.get_header("X-github-api-version") == "2022-11-28"


def test_fetch_snapshot_applies_branch_filter() -> None:
    payload: dict[str, Any] = {
        "total_count": 1,
        "workflow_runs": [
            {
                "id": 101,
                "name": "CI",
                "workflow_id": 1,
                "status": "completed",
                "conclusion": "success",
                "created_at": "2026-06-21T12:00:00Z",
                "run_started_at": "2026-06-21T12:00:00Z",
                "updated_at": "2026-06-21T12:00:30Z",
                "head_branch": "main",
            }
        ],
    }

    with patch.object(
        github_workflow_bridge.config,
        "github_workflow_repo",
        return_value=("owner", "repo"),
    ), patch.object(
        github_workflow_bridge.config,
        "github_workflow_timeout_secs",
        return_value=5,
    ), patch.object(
        github_workflow_bridge.config,
        "github_workflow_per_page",
        return_value=30,
    ), patch.object(
        github_workflow_bridge.config,
        "github_workflow_branch",
        return_value="main",
    ), patch.object(
        github_workflow_bridge.config,
        "github_workflow_ids",
        return_value=[],
    ), patch.object(
        github_workflow_bridge,
        "_github_request_json",
        return_value=payload,
    ) as mock_request:
        result = github_workflow_bridge._fetch_snapshot("token")

    assert result["ok"] == 1
    assert result["counts"]["seen"] == 1
    assert result["counts"]["success"] == 1
    called_url = mock_request.call_args[0][0]
    assert "branch=main" in called_url


def test_fetch_snapshot_empty_branch_filter_allows_all() -> None:
    with patch.object(
        github_workflow_bridge.config,
        "github_workflow_repo",
        return_value=("owner", "repo"),
    ), patch.object(
        github_workflow_bridge.config,
        "github_workflow_timeout_secs",
        return_value=5,
    ), patch.object(
        github_workflow_bridge.config,
        "github_workflow_per_page",
        return_value=30,
    ), patch.object(
        github_workflow_bridge.config,
        "github_workflow_branch",
        return_value=None,
    ), patch.object(
        github_workflow_bridge.config,
        "github_workflow_ids",
        return_value=[],
    ), patch.object(
        github_workflow_bridge,
        "_github_request_json",
        return_value={"total_count": 0, "workflow_runs": []},
    ) as mock_request:
        github_workflow_bridge._fetch_snapshot("token")

    called_url = mock_request.call_args[0][0]
    assert "branch=" not in called_url


def test_snapshot_returns_disabled_without_token() -> None:
    with patch.object(
        github_workflow_bridge.config,
        "github_workflow_token",
        return_value="",
    ):
        result = github_workflow_bridge.snapshot()
    assert result["enabled"] == 0
    assert result["ok"] == 0
    assert result["error"] == "missing_token"


def test_snapshot_coalesces_parallel_fetches() -> None:
    github_workflow_bridge._cached_snapshot = None
    github_workflow_bridge._cached_at_monotonic = 0.0

    calls: list[str] = []

    def _slow_fetch(token: str) -> dict[str, Any]:
        calls.append(token)
        time.sleep(0.05)
        return {
            "enabled": 1,
            "ok": 1,
            "fetched_at_unix": time.time(),
            "counts": {
                "seen": 1,
                "success": 1,
                "failed": 0,
                "in_progress": 0,
                "queued": 0,
            },
            "latest_run_age_seconds": None,
            "latest_run_duration_seconds": None,
            "workflows": [],
        }

    with patch.object(
        github_workflow_bridge.config,
        "github_workflow_token",
        return_value="token",
    ), patch.object(
        github_workflow_bridge.config,
        "github_workflow_poll_ttl_secs",
        return_value=300,
    ), patch.object(
        github_workflow_bridge,
        "_fetch_snapshot",
        side_effect=_slow_fetch,
    ):
        threads = [threading.Thread(target=github_workflow_bridge.snapshot) for _ in range(6)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

    assert len(calls) == 1


def test_snapshot_parallel_fetch_error_is_coalesced() -> None:
    calls: list[str] = []
    results: list[dict[str, Any]] = []

    def _slow_fail(token: str) -> dict[str, Any]:
        calls.append(token)
        time.sleep(0.05)
        raise TimeoutError("boom")

    def _worker() -> None:
        results.append(github_workflow_bridge.snapshot())

    with patch.object(
        github_workflow_bridge.config,
        "github_workflow_token",
        return_value="token",
    ), patch.object(
        github_workflow_bridge.config,
        "github_workflow_poll_ttl_secs",
        return_value=300,
    ), patch.object(
        github_workflow_bridge,
        "_fetch_snapshot",
        side_effect=_slow_fail,
    ):
        threads = [threading.Thread(target=_worker) for _ in range(6)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

    assert len(calls) == 1
    assert len(results) == 6
    assert all(r.get("enabled") == 1 for r in results)
    assert all(r.get("ok") == 0 for r in results)
    assert all(r.get("error") == "TimeoutError" for r in results)
