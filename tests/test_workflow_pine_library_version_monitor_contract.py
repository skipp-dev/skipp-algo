"""Contract pin: ``pine-library-version-monitor`` workflow (#3599/#3603 follow-up).

Pins the daily schedule, the mutating-on-cron posture, the TradingView facade
probe entrypoint, the self-covering build (a facade outage still publishes),
and the rolling bot-branch publish — so silent drift of the Pine-library
version-monitoring producer is caught at validate-time. This file also
satisfies ``test_workflow_orphan_inventory`` by referencing the workflow stem
``pine-library-version-monitor``.
"""

from __future__ import annotations

from pathlib import Path

import yaml

_REPO_ROOT = Path(__file__).resolve().parents[1]
_WF_PATH = _REPO_ROOT / ".github" / "workflows" / "pine-library-version-monitor.yml"


def _load() -> dict:
    return yaml.safe_load(_WF_PATH.read_text(encoding="utf-8"))


def _steps() -> list[dict]:
    return _load()["jobs"]["snapshot"]["steps"]


def test_workflow_file_exists() -> None:
    assert _WF_PATH.is_file(), f"missing workflow: {_WF_PATH}"


def test_live_window_marker_mutating_on_cron() -> None:
    head = _WF_PATH.read_text(encoding="utf-8").splitlines()[1]
    assert "live-window: mutating-on-cron" in head, (
        "second-line live-window marker required — mutating-on-cron because "
        "the workflow publishes the snapshot branch"
    )


def test_schedule_is_daily() -> None:
    data = _load()
    on_block = data.get("on") or data.get(True)
    crons = [entry["cron"] for entry in on_block["schedule"]]
    assert crons == ["30 5 * * *"], crons
    assert "workflow_dispatch" in on_block


def test_permissions_declare_write() -> None:
    assert _load()["permissions"] == {"contents": "write"}


def test_concurrency_does_not_cancel() -> None:
    assert _load()["concurrency"]["cancel-in-progress"] is False


def test_job_has_timeout_and_unbuffered() -> None:
    data = _load()
    assert 0 < int(data["jobs"]["snapshot"]["timeout-minutes"]) <= 360
    assert data["env"]["PYTHONUNBUFFERED"] == "1"


def test_runs_the_facade_snapshot_builder() -> None:
    body = " ".join(step.get("run", "") for step in _steps())
    assert "scripts/build_pine_library_version_snapshot.ts" in body


def test_build_is_self_covering_on_facade_outage() -> None:
    """A facade/auth outage returns rc!=0 but STILL writes the snapshot
    (facade_ok=0). The build step must not let that fail the job — only a
    missing output file is fatal — so the monitoring signal survives a probe
    outage."""
    build = next(s for s in _steps() if s.get("id") == "build")
    run = build["run"]
    assert "|| rc=$?" in run
    assert 'if [ ! -s artifacts/monitoring/pine_library_versions.json ]' in run


def test_storage_state_absent_is_fail_soft() -> None:
    """A missing TV_STORAGE_STATE must warn and continue (the snapshot still
    publishes with facade_ok=0), never abort the run."""
    step = next(s for s in _steps() if s.get("id") == "storage_state")
    assert 'written=false' in step["run"]


def test_publishes_to_rolling_bot_branch() -> None:
    body = " ".join(step.get("run", "") for step in _steps())
    assert "bot/live-pine-library-versions" in body, (
        "the snapshot must publish to the rolling bot branch the daemon reads "
        "via PINE_LIBRARY_VERSIONS_SNAPSHOT_URL"
    )
    # Publish must be fail-soft on a missing PAT (best-effort, never red).
    assert "GH_PAT not configured" in body
