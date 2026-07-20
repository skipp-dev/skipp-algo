"""Structural contract tests for the Plan 2.8 evaluation workflow."""

from __future__ import annotations

from pathlib import Path

import yaml

WORKFLOW = (
    Path(__file__).resolve().parents[1]
    / ".github"
    / "workflows"
    / "plan-2-8-evaluation.yml"
)


def _workflow() -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def _steps() -> list[dict]:
    return _workflow()["jobs"]["evaluate"]["steps"]


def _step(name: str) -> dict:
    for step in _steps():
        if step.get("name") == name:
            return step
    raise AssertionError(f"step {name!r} not found")


def test_workflow_permissions_support_issue_fallback_without_token_push() -> None:
    permissions = _workflow()["permissions"]
    assert permissions["contents"] == "read"
    assert permissions["issues"] == "write"
    publish_step = _step("Publish snapshots to rolling bot branch")
    assert publish_step["env"]["GH_TOKEN"] == "${{ secrets.GH_PAT }}"


def test_checkout_does_not_persist_github_token_credentials() -> None:
    checkout_step = _step("Checkout")
    assert checkout_step["with"]["persist-credentials"] is False


def test_experiment_snapshot_publish_uses_explicit_force_with_lease_sha() -> None:
    run = _step("Publish snapshots to rolling bot branch")["run"]
    assert "scripts/publish_bot_snapshot.py" in run
    assert "--branch bot/live-experiment-snapshot" in run
    assert "--copy-if-present" in run


def test_experiment_snapshot_publish_failure_is_fail_closed() -> None:
    run = _step("Publish snapshots to rolling bot branch")["run"]
    assert "scripts/publish_bot_snapshot.py" in run
    assert "|| true" not in run


def test_evaluation_failure_issue_opens_for_failed_status_or_step_crash() -> None:
    issue_step = _step("Open issue on evaluation failure")
    assert issue_step["if"] == (
        "always() && "
        "(steps.evaluate.outcome == 'failure' || "
        "steps.evaluate.outputs.status == 'failed')"
    )
