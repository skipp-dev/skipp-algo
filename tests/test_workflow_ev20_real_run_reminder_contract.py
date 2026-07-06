"""Contract pin: ``ev20-real-run-reminder`` workflow (operator decision 2026-07-06).

Pins the monthly cron, the notify-only posture (the reminder must NEVER
dispatch the governed ``edge-pipeline-real-run`` pipeline itself), the
recent-success skip rule, and the issues-disabled soft-degrade so silent
drift of the reminder is caught at validate-time. This file also satisfies
``test_workflow_orphan_inventory`` by referencing the workflow stem
``ev20-real-run-reminder``.
"""

from __future__ import annotations

from pathlib import Path

import yaml

_REPO_ROOT = Path(__file__).resolve().parents[1]
_WF_PATH = _REPO_ROOT / ".github" / "workflows" / "ev20-real-run-reminder.yml"


def _load() -> dict:
    return yaml.safe_load(_WF_PATH.read_text(encoding="utf-8"))


def _steps() -> list[dict]:
    return _load()["jobs"]["remind"]["steps"]


def test_workflow_file_exists() -> None:
    assert _WF_PATH.is_file(), f"missing workflow: {_WF_PATH}"


def test_live_window_marker_mutating_on_cron() -> None:
    head = _WF_PATH.read_text(encoding="utf-8").splitlines()[0]
    assert "live-window: mutating-on-cron" in head, (
        "first-line live-window marker required — mutating-on-cron because "
        "the reminder opens issues on a schedule"
    )


def test_schedule_is_monthly_first_0900_utc() -> None:
    data = _load()
    on_block = data.get("on") or data.get(True)
    crons = [entry["cron"] for entry in on_block["schedule"]]
    assert crons == ["0 9 1 * *"], crons
    assert "workflow_dispatch" in on_block


def test_permissions_issues_write_only_mutation() -> None:
    data = _load()
    assert data["permissions"] == {
        "contents": "read",
        "issues": "write",
        "actions": "read",
    }


def test_concurrency_does_not_cancel() -> None:
    conc = _load()["concurrency"]
    assert conc["cancel-in-progress"] is False


def test_job_has_timeout() -> None:
    job = _load()["jobs"]["remind"]
    assert 0 < int(job["timeout-minutes"]) <= 360


def test_reminder_never_dispatches_the_pipeline() -> None:
    """The reminder is notify-only: the governed pipeline is manual-only
    (Databento spend + human-reviewed decision PRs). The only place the
    dispatch command may appear is inside the issue BODY text (an echo into
    the body file), never as an executed command at the start of a line."""
    for step in _steps():
        for line in step.get("run", "").splitlines():
            stripped = line.strip()
            if stripped.startswith("gh workflow run"):
                raise AssertionError(
                    "reminder executes `gh workflow run` directly — it must "
                    f"only quote the command in the issue body: {stripped!r}"
                )
            if "gh workflow run" in stripped:
                assert stripped.startswith("echo"), (
                    "dispatch command may only appear inside echoed issue-"
                    f"body text: {stripped!r}"
                )


def test_probe_counts_only_successful_runs() -> None:
    probe = next(s for s in _steps() if s.get("id") == "probe")
    body = probe["run"]
    assert "edge-pipeline-real-run.yml" in body
    assert "--status success" in body, (
        "the skip rule must count only SUCCESSFUL runs as coverage — a "
        "failed attempt is not a fresh archived verdict"
    )
    assert probe["env"]["SKIP_IF_SUCCESS_WITHIN_DAYS"] == "25"


def test_issue_step_guards_disabled_issues() -> None:
    issue_step = next(
        s for s in _steps() if "issue" in s.get("name", "").lower()
    )
    body = issue_step["run"]
    assert "hasIssuesEnabled" in body, (
        "missing the issues-disabled soft-degrade (#3203 pattern) — with "
        "Issues off the step would crash and look like a broken reminder"
    )
    assert "::warning" in body
    # Gated on the probe verdict: no issue churn when the month is covered.
    assert issue_step.get("if") == "steps.probe.outputs.due == 'true'"


def test_issue_uses_known_label() -> None:
    issue_step = next(
        s for s in _steps() if "issue" in s.get("name", "").lower()
    )
    assert "--label automated" in issue_step["run"]
