"""Pin-tests for the drift-alert issue creation wiring in the weekly digest."""

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


def test_permissions_include_issues_write() -> None:
    perms = _wf()["permissions"]
    assert perms["issues"] == "write"


def test_digest_step_also_renders_issue_body_and_alerts_file() -> None:
    steps = _wf()["jobs"]["weekly-digest"]["steps"]
    digest = next(s for s in steps if s.get("id") == "digest")
    run = digest["run"]
    assert "--format             issue" in run
    assert "--output             artifacts/plan_2_8_digest/issue_body.md" in run
    assert "--alerts-file        artifacts/plan_2_8_digest/alerts.json" in run
    # has_alerts propagated via GITHUB_OUTPUT.
    assert "has_alerts=" in run
    assert "$GITHUB_OUTPUT" in run


def test_issue_creation_step_present_and_conditional() -> None:
    steps = _wf()["jobs"]["weekly-digest"]["steps"]
    issue = next(s for s in steps if s.get("name") == "Open drift-alert issue")
    assert issue["if"] == "steps.digest.outputs.has_alerts == 'True'"
    run = issue["run"]
    assert "gh issue create" in run
    assert "--body-file artifacts/plan_2_8_digest/issue_body.md" in run
    assert "--label plan-2.8,drift-alert" in run


def test_issue_step_dedups_via_existing_open_issue() -> None:
    steps = _wf()["jobs"]["weekly-digest"]["steps"]
    issue = next(s for s in steps if s.get("name") == "Open drift-alert issue")
    run = issue["run"]
    assert "gh issue list" in run
    assert "--label plan-2.8" in run and "--label drift-alert" in run
    assert "--state open" in run
    assert "gh issue comment" in run


def test_issue_step_threads_run_url_into_body() -> None:
    steps = _wf()["jobs"]["weekly-digest"]["steps"]
    issue = next(s for s in steps if s.get("name") == "Open drift-alert issue")
    assert "RUN_URL" in issue["env"]
    assert "github.run_id" in issue["env"]["RUN_URL"]
    run = issue["run"]
    assert "--run-url" in run
    assert "${RUN_URL}" in run


def test_issue_step_uses_github_token() -> None:
    steps = _wf()["jobs"]["weekly-digest"]["steps"]
    issue = next(s for s in steps if s.get("name") == "Open drift-alert issue")
    assert issue["env"]["GH_TOKEN"] == "${{ secrets.GITHUB_TOKEN }}"


def test_issue_step_runs_after_upload() -> None:
    steps = _wf()["jobs"]["weekly-digest"]["steps"]
    names = [s.get("name", "") for s in steps]
    assert names.index("Upload weekly digest") < names.index("Open drift-alert issue")
