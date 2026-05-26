"""Contract pin: ``promotion-gate-weekly-dashboard`` workflow (PQ A8 / #2354).

Pins the cron schedule, off-hours-only live-window marker, runner timeout,
and the script entrypoint so silent drift of the weekly governance
dashboard is caught at validate-time.
"""

from __future__ import annotations

from pathlib import Path

import yaml

_REPO_ROOT = Path(__file__).resolve().parents[1]
_WF_PATH = _REPO_ROOT / ".github" / "workflows" / "promotion-gate-weekly-dashboard.yml"


def _load() -> dict:
    return yaml.safe_load(_WF_PATH.read_text(encoding="utf-8"))


def test_workflow_file_exists() -> None:
    assert _WF_PATH.is_file(), f"missing workflow: {_WF_PATH}"


def test_live_window_marker_off_hours_only() -> None:
    head = _WF_PATH.read_text(encoding="utf-8").splitlines()[0]
    assert "live-window: off-hours-only" in head, (
        "first-line live-window marker required by F-V6-F2.1"
    )


def test_schedule_is_sunday_06_utc() -> None:
    data = _load()
    # PyYAML parses bare ``on`` as boolean True — accept both keys.
    on_block = data.get("on") or data.get(True)
    crons = [entry["cron"] for entry in on_block["schedule"]]
    assert crons == ["0 6 * * 0"], crons


def test_dashboard_job_invokes_build_script() -> None:
    data = _load()
    job = data["jobs"]["dashboard"]
    assert job["timeout-minutes"] == 10
    steps_run = " ".join(step.get("run", "") for step in job["steps"])
    assert "scripts.build_promotion_gate_dashboard" in steps_run
    assert "--source-dir governance/promotion_decisions" in steps_run
    assert "--lookback-weeks" in steps_run


def test_upload_artifact_name_is_dashboard() -> None:
    data = _load()
    upload_steps = [
        step for step in data["jobs"]["dashboard"]["steps"]
        if "actions/upload-artifact" in (step.get("uses") or "")
    ]
    assert len(upload_steps) == 1
    cfg = upload_steps[0]["with"]
    assert cfg["name"] == "promotion-gate-weekly-dashboard"
    assert cfg["if-no-files-found"] == "error"
    assert cfg["retention-days"] == 90
