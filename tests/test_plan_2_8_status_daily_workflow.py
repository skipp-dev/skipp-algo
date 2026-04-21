"""Pin-tests for the plan-2.8 status daily workflow."""

from __future__ import annotations

from pathlib import Path

import yaml

WORKFLOW = (
    Path(__file__).resolve().parents[1]
    / ".github" / "workflows" / "plan-2-8-status-daily.yml"
)


def _wf() -> dict:
    data = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    return {"on": data.get("on", data.get(True)), **{
        k: v for k, v in data.items() if k not in ("on", True)
    }}


def test_workflow_exists() -> None:
    assert WORKFLOW.exists()


def test_trigger_is_schedule_plus_dispatch() -> None:
    on = _wf()["on"]
    assert isinstance(on, dict)
    assert "schedule" in on
    assert "workflow_dispatch" in on


def test_schedule_is_06_15_utc() -> None:
    on = _wf()["on"]
    crons = [s["cron"] for s in on["schedule"]]
    assert crons == ["15 6 * * *"]


def test_status_step_runs_script_and_streams_summary() -> None:
    steps = _wf()["jobs"]["status"]["steps"]
    report = next(s for s in steps if s.get("id") == "report")
    run = report["run"]
    assert "scripts/plan_2_8_status.py" in run
    assert "--format md" in run
    assert "$GITHUB_STEP_SUMMARY" in run
    assert "artifacts/plan_2_8_status/report.md" in run


def test_report_artifact_uploaded_always() -> None:
    steps = _wf()["jobs"]["status"]["steps"]
    upload = next(
        s for s in steps
        if str(s.get("uses", "")).startswith("actions/upload-artifact@")
    )
    assert upload.get("if") == "always()"
    assert upload["with"]["name"] == "plan-2-8-status-report"
    assert "report.md" in upload["with"]["path"]
