"""Structural pin for ``.github/workflows/live-overlay-dashboard-publish.yml``.

This test intentionally references the exact hyphenated basename
``live-overlay-dashboard-publish`` so orphan-workflow inventory remains
closed once the temporary allowlist entry is removed.

The pins below scope themselves properly to the verify and publish steps and
even assert their execution order -- but they stop at the step boundary. Inside
the publish step, one token decides whether anything reaches Grafana at all:

    if [[ "${dry_run}" == "true" ]]; then   ->   if [[ "${dry_run}" == "false" ]]

Measured 2026-08-04: that inversion leaves every assertion here green while
every push to ``main`` stops before publishing, and a manual ``dry_run=true``
publishes for real instead. This file is on the required lane
(``tests/_fast_inventory.py``), so such a PR merges green. See the sibling
``test_live_overlay_alert_rules_publish_workflow.py`` -- the same shape, the
same blind spot, one shared harness.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from tests._workflow_step_shell import BASH, declares_bash_default, run_step

REPO_ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = "live-overlay-dashboard-publish.yml"
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / WORKFLOW
PUBLISH_STEP = "Publish dashboards (or dry-run)"
PUBLISH_SCRIPT = "scripts/publish_overlay_dashboard.py"
DASHBOARD_COUNT = 3  # dashboard.json, dashboard-signals-experiments.json, dashboard-pre-a0.json


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
        "services/live_overlay_daemon/infra/grafana/dashboard-pre-a0.json",
        "scripts/build_pre_a0_dashboard.py",
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
    assert checkout.get("uses") == "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1"

    verify_index = next(
        (
            index
            for index, step in enumerate(steps)
            if isinstance(step, dict)
            and step.get("name") == "Verify live overlay dashboard is up to date"
        ),
        None,
    )
    assert verify_index is not None, "dashboard publish must verify generated dashboard drift"
    verify_step = steps[verify_index]
    assert isinstance(verify_step, dict)
    verify_run = verify_step.get("run") or ""
    assert "python scripts/update_overlay_dashboard.py" in verify_run
    assert "services/live_overlay_daemon/infra/grafana/dashboard.json" in verify_run
    assert "services/live_overlay_daemon/infra/grafana/dashboard-signals-experiments.json" in verify_run
    assert "python scripts/build_pre_a0_dashboard.py --check" in verify_run
    assert verify_run.count("--check") == 3
    assert "env" not in verify_step, "dashboard drift check must not require publish secrets"

    publish_index = next(
        (
            index
            for index, step in enumerate(steps)
            if isinstance(step, dict) and step.get("name") == "Publish dashboards (or dry-run)"
        ),
        None,
    )
    assert publish_index is not None, "publish step missing"
    assert verify_index < publish_index, "dashboard drift check must run before publish"
    publish_step = steps[publish_index]
    assert isinstance(publish_step, dict), "publish step missing"

    run = publish_step.get("run") or ""
    assert "python scripts/publish_overlay_dashboard.py" in run
    assert "dashboard-signals-experiments.json" in run
    assert "dashboard-pre-a0.json|bfshrlee72tc0d" in run
    assert 'IFS="|" read -r DASHBOARD_PATH FOLDER_UID' in run
    assert '--folder "${FOLDER_UID}"' in run
    assert "GRAFANA_API_TOKEN" in run
    assert "--dry-run" in run


# --- what the step decides, measured rather than read ------------------------


@pytest.fixture
def publish(tmp_path):
    """Run the real publish step against a stubbed ``python``; report its calls."""

    def _run(
        event_name: str,
        *,
        dry_run: str = "",
        token: str = "grafana-token",
        host: str = "",
        python_exit: int = 0,
    ):
        return run_step(
            WORKFLOW,
            PUBLISH_STEP,
            tmp_path,
            env={
                "EVENT_NAME": event_name,
                "INPUT_DRY_RUN": dry_run,
                "INPUT_HOST": host,
                "GRAFANA_API_TOKEN": token,
            },
            stubs={"python": python_exit},
        )

    return _run


def _network_publishes(result) -> tuple[str, ...]:
    """Invocations that actually mutate Grafana -- i.e. without ``--dry-run``."""
    return tuple(c for c in result.called_with(PUBLISH_SCRIPT) if "--dry-run" not in c)


def test_publish_executes_for_real_on_a_push(publish) -> None:
    """A push to main must reach Grafana, for every dashboard."""
    result = publish("push")
    assert result.returncode == 0, result.stderr
    assert len(_network_publishes(result)) == DASHBOARD_COUNT, (
        f"a push must publish all {DASHBOARD_COUNT} dashboards; it ran: {result.calls}"
    )


def test_every_dashboard_is_validated_before_any_is_published(publish) -> None:
    """The half-updated-Grafana guard the step's own comment describes.

    Not "a preflight exists" but "ALL preflights precede the FIRST publish" --
    the property that keeps a failure on dashboard 2 from stranding dashboard 1
    already live.
    """
    calls = publish("push").called_with(PUBLISH_SCRIPT)
    previews = [i for i, c in enumerate(calls) if "--dry-run" in c]
    publishes = [i for i, c in enumerate(calls) if "--dry-run" not in c]
    assert len(previews) == DASHBOARD_COUNT, f"every dashboard needs a preflight: {calls}"
    assert max(previews) < min(publishes), (
        f"all preflights must finish before the first publish; order was: {calls}"
    )


def test_each_dashboard_goes_to_its_own_folder(publish) -> None:
    """``dashboard-pre-a0.json`` lives in a different Grafana folder than the rest.

    The structural pin asserts the ``path|uid`` pairs appear in the source; this
    asserts the split survives ``IFS="|" read`` and reaches the command line.
    """
    published = _network_publishes(publish("push"))
    pre_a0 = [c for c in published if "dashboard-pre-a0.json" in c]
    others = [c for c in published if "dashboard-pre-a0.json" not in c]
    # Count both sides before looping: an empty `others` would let the loop
    # below pass without comparing a single folder uid.
    assert others, "no non-pre-a0 dashboard was published; the loop below would be vacuous"
    assert len(others) == DASHBOARD_COUNT - 1, published
    assert len(pre_a0) == 1, published
    assert "--folder bfshrlee72tc0d" in pre_a0[0], pre_a0[0]
    for other in others:
        assert "--folder cfpozahbhfzswc" in other, other


def test_a_manual_dry_run_never_reaches_grafana(publish) -> None:
    """``dry_run=true`` (the manual default) must validate and stop."""
    result = publish("workflow_dispatch", dry_run="true")
    assert result.returncode == 0, result.stderr
    assert not _network_publishes(result), f"a dry run must not publish; ran: {result.calls}"
    assert len(result.called_with(PUBLISH_SCRIPT, "--dry-run")) == DASHBOARD_COUNT


def test_a_manual_publish_reaches_grafana(publish) -> None:
    """``dry_run=false`` is the deliberate manual publish."""
    assert len(_network_publishes(publish("workflow_dispatch", dry_run="false"))) == DASHBOARD_COUNT


def test_an_unparseable_dry_run_input_fails_before_anything_runs(publish) -> None:
    result = publish("workflow_dispatch", dry_run="maybe")
    assert result.returncode != 0, "an invalid dry_run input must fail the step"
    assert not result.calls, f"nothing may run before the input is validated: {result.calls}"


def test_a_real_publish_without_the_token_fails_loud(publish) -> None:
    result = publish("push", token="")
    assert result.returncode != 0, "a tokenless real publish must fail, not skip"
    assert not _network_publishes(result), "it must fail BEFORE calling Grafana"


def test_a_failing_preflight_stops_the_publish(publish) -> None:
    """A payload that will not build must never be published.

    As in the alert-rules sibling, the abort comes from the ``shell: bash``
    default (Actions runs the block under ``-eo pipefail``), not from the
    block's own ``set -euo pipefail`` line. What this catches is a ``|| true``
    appended to the preflight, which every structural pin above would miss.
    """
    result = publish("push", python_exit=1)
    assert result.returncode != 0, "a failed preflight must fail the step"
    assert not _network_publishes(result), f"nothing may be published; ran: {result.calls}"


def test_the_harness_runs_the_shell_this_workflow_declares(workflow_doc: dict) -> None:
    """Pin both sides -- see the sibling test for why one side is not enough."""
    assert declares_bash_default(WORKFLOW), "workflow must keep `defaults: run: shell: bash`"
    assert ((workflow_doc.get("defaults") or {}).get("run") or {}).get("shell") == "bash"
    assert BASH == ("bash", "--noprofile", "--norc", "-e", "-o", "pipefail")
