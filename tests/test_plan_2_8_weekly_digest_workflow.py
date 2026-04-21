"""Pin-tests for the plan-2.8 weekly trend digest workflow."""

from __future__ import annotations

from pathlib import Path

import yaml

WORKFLOW = (
    Path(__file__).resolve().parents[1]
    / ".github" / "workflows" / "plan-2-8-weekly-digest.yml"
)


def _wf() -> dict:
    data = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    return {"on": data.get("on", data.get(True)), **{
        k: v for k, v in data.items() if k not in ("on", True)
    }}


def test_workflow_exists() -> None:
    assert WORKFLOW.exists()


def test_trigger_is_monday_schedule_plus_dispatch() -> None:
    on = _wf()["on"]
    assert "schedule" in on and "workflow_dispatch" in on
    crons = [s["cron"] for s in on["schedule"]]
    assert crons == ["0 12 * * 1"]


def test_dispatch_inputs_have_documented_defaults() -> None:
    inputs = _wf()["on"]["workflow_dispatch"]["inputs"]
    assert inputs["lookback_days"]["default"] == "7"
    assert inputs["alert_threshold_pp"]["default"] == "0.05"
    assert inputs["min_events"]["default"] == "30"


def test_digest_step_invokes_trend_digest_with_all_knobs() -> None:
    steps = _wf()["jobs"]["weekly-digest"]["steps"]
    digest = next(s for s in steps if s.get("id") == "digest")
    run = digest["run"]
    assert "scripts/plan_2_8_trend_digest.py" in run
    for flag in ("--history", "--lookback-days", "--alert-threshold-pp",
                 "--min-events", "--output"):
        assert flag in run, f"trend digest missing flag: {flag}"
    assert "$GITHUB_STEP_SUMMARY" in run
    # Fail-soft: missing history is logged but does not fail the run.
    assert "set +e" in run
    assert "No plan_2_8_history.jsonl found" in run


def test_digest_artifact_uploaded_always() -> None:
    steps = _wf()["jobs"]["weekly-digest"]["steps"]
    upload = next(
        s for s in steps
        if str(s.get("uses", "")).startswith("actions/upload-artifact@")
    )
    assert upload.get("if") == "always()"
    assert upload["with"]["name"] == "plan-2-8-weekly-digest"
    assert "weekly_digest.md" in upload["with"]["path"]
    assert int(upload["with"]["retention-days"]) >= 90


def test_download_step_targets_rolling_bench_workflow() -> None:
    steps = _wf()["jobs"]["weekly-digest"]["steps"]
    dl = next(s for s in steps if s.get("id") == "download")
    assert dl["with"]["workflow"] == "smc-measurement-benchmark-rolling.yml"
    assert dl["with"]["name_is_regexp"] is True
