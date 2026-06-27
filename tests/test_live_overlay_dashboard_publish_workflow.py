"""Structural pin for ``.github/workflows/live-overlay-dashboard-publish.yml``.

This test intentionally references the exact hyphenated basename
``live-overlay-dashboard-publish`` so orphan-workflow inventory remains
closed once the temporary allowlist entry is removed.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "live-overlay-dashboard-publish.yml"


@pytest.fixture(scope="module")
def workflow_doc() -> dict:
    text = WORKFLOW_PATH.read_text(encoding="utf-8")
    data = yaml.safe_load(text)
    assert isinstance(data, dict), "workflow must parse as a mapping"
    return data


def test_trigger_contract_pinned(workflow_doc: dict) -> None:
    # PyYAML may parse bare `on:` as boolean True; tolerate both shapes.
    on_block = workflow_doc.get("on") if "on" in workflow_doc else workflow_doc.get(True)
    assert isinstance(on_block, dict), "workflow must declare `on:` mapping"

    push = on_block.get("push")
    assert isinstance(push, dict), "workflow must define push trigger"
    assert push.get("branches") == ["main"], "push trigger must remain pinned to main"
    assert push.get("paths") == [
        "services/live_overlay_daemon/infra/grafana/dashboard.json",
        "services/live_overlay_daemon/infra/grafana/dashboard-signals-experiments.json",
    ], "push path filter drifted for dashboard publish workflow"

    dispatch = on_block.get("workflow_dispatch")
    assert isinstance(dispatch, dict), "workflow must support workflow_dispatch"
    inputs = dispatch.get("inputs")
    assert isinstance(inputs, dict), "workflow_dispatch must define inputs"
    dry_run = inputs.get("dry_run")
    assert isinstance(dry_run, dict), "dry_run input missing"
    assert dry_run.get("type") == "boolean"
    assert dry_run.get("default") is True


def test_permissions_defaults_and_concurrency_pinned(workflow_doc: dict) -> None:
    permissions = workflow_doc.get("permissions")
    assert isinstance(permissions, dict)
    assert permissions.get("contents") == "read"

    defaults = workflow_doc.get("defaults")
    assert isinstance(defaults, dict)
    run_defaults = defaults.get("run")
    assert isinstance(run_defaults, dict)
    assert run_defaults.get("shell") == "bash"

    env = workflow_doc.get("env")
    assert isinstance(env, dict)
    assert env.get("PYTHONUNBUFFERED") == "1"
    assert env.get("PYTHONPATH") == "${{ github.workspace }}"

    concurrency = workflow_doc.get("concurrency")
    assert isinstance(concurrency, dict)
    group = concurrency.get("group")
    assert isinstance(group, str)
    assert "${{ github.workflow }}" in group and "${{ github.ref }}" in group
    assert concurrency.get("cancel-in-progress") is False


def test_publish_step_contract_pinned(workflow_doc: dict) -> None:
    jobs = workflow_doc.get("jobs")
    assert isinstance(jobs, dict)
    job = jobs.get("publish-dashboard")
    assert isinstance(job, dict), "publish-dashboard job missing"

    steps = job.get("steps")
    assert isinstance(steps, list) and steps

    checkout = next(
        (step for step in steps if isinstance(step, dict) and step.get("name") == "Checkout"),
        None,
    )
    assert isinstance(checkout, dict), "Checkout step missing"
    assert checkout.get("uses") == "actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd"

    publish_step = next(
        (
            step
            for step in steps
            if isinstance(step, dict) and step.get("name") == "Publish dashboards (or dry-run)"
        ),
        None,
    )
    assert isinstance(publish_step, dict), "publish step missing"

    run = publish_step.get("run") or ""
    assert "python scripts/publish_overlay_dashboard.py" in run
    assert "dashboard-signals-experiments.json" in run
    assert "GRAFANA_API_TOKEN" in run
    assert "--dry-run" in run
