"""Structural pin for ``.github/workflows/workflow-freshness-monitor.yml``.

Companion to ``tests/test_credential_health_workflow.py``. The freshness
monitor is the out-of-band observer that exists *because* of the 5-week
silent publish-skip post-mortem (PR #2415 / issue #2422). Any refactor
that drops the monitored workflow list, swallows the script rc, or
removes the auto-issue surface would re-introduce exactly the failure
mode this workflow is supposed to detect — so each load-bearing piece
gets an explicit pin here.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None  # type: ignore[assignment]


WORKFLOW = (
    Path(__file__).resolve().parents[1]
    / ".github"
    / "workflows"
    / "workflow-freshness-monitor.yml"
)


@pytest.fixture(scope="module")
def workflow_text() -> str:
    assert WORKFLOW.exists(), f"missing workflow: {WORKFLOW}"
    return WORKFLOW.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def workflow(workflow_text: str) -> dict:
    if yaml is None:
        pytest.skip("PyYAML not available")
    return yaml.safe_load(workflow_text)


# ---------------------------------------------------------------------------
# Triggers
# ---------------------------------------------------------------------------


def test_workflow_runs_daily_at_06_30_utc(workflow: dict) -> None:
    on = workflow.get(True) or workflow.get("on")  # PyYAML quirk: 'on' → True
    assert on is not None, "workflow has no triggers"
    schedule = on.get("schedule")
    assert schedule, "must have a schedule trigger"
    crons = [entry.get("cron") for entry in schedule]
    assert "30 6 * * *" in crons, (
        f"expected daily 06:30 UTC cron (30 min after credential-health-check "
        f"so its issue is filed first), got {crons!r}"
    )


def test_workflow_supports_manual_dispatch(workflow: dict) -> None:
    on = workflow.get(True) or workflow.get("on")
    assert "workflow_dispatch" in on, "must allow manual operator runs"


# ---------------------------------------------------------------------------
# Concurrency (F-V5-C2) + F-V6-F2.1 live-window marker.
# ---------------------------------------------------------------------------


def test_live_window_marker_present(workflow_text: str) -> None:
    """F-V6-F2.1: top-of-file marker MUST be present in the first 10 lines."""
    head = "\n".join(workflow_text.splitlines()[:10])
    assert "# live-window:" in head, (
        "workflow-freshness-monitor.yml MUST declare the F-V6-F2.1 live-window "
        "marker in the first 10 lines (was removed/relocated?)."
    )


def test_concurrency_does_not_cancel_in_progress(workflow: dict) -> None:
    """F-V5-C2 (2026-05-01): cron workflows MUST NOT cancel in-progress siblings."""
    concurrency = workflow.get("concurrency")
    assert isinstance(concurrency, dict), (
        "workflow-freshness-monitor.yml MUST declare a top-level concurrency block"
    )
    assert concurrency.get("group"), "concurrency.group must be set"
    cancel = concurrency.get("cancel-in-progress")
    assert cancel is False, (
        "cancel-in-progress MUST be False — losing a freshness probe mid-run "
        "would defeat the purpose of having an out-of-band observer."
    )


# ---------------------------------------------------------------------------
# Permissions (least-privilege)
# ---------------------------------------------------------------------------


def test_workflow_permissions_are_minimal(workflow: dict) -> None:
    perms = workflow.get("permissions") or {}
    assert perms.get("contents") == "read", "contents must be read-only"
    assert perms.get("issues") == "write", (
        "needs issues:write to file the cron-failure issue when a monitored "
        "workflow goes stale"
    )
    assert set(perms.keys()) <= {"contents", "issues"}, (
        f"unexpected extra permissions: {perms}"
    )


# ---------------------------------------------------------------------------
# Probe step contract
# ---------------------------------------------------------------------------


def test_probe_step_invokes_freshness_script(workflow_text: str) -> None:
    assert "python scripts/check_workflow_freshness.py" in workflow_text, (
        "workflow must call scripts/check_workflow_freshness.py"
    )
    assert "--output artifacts/ci/workflow_freshness.json" in workflow_text, (
        "workflow must write its report to the canonical artifact path so "
        "the audit dashboard finds it"
    )


# The set of critical-path crons this monitor watches. Drift here = the
# new workflow is silently NOT being observed for staleness. Each entry
# must stay paired with its budget in the probe step CLI.
_MONITORED_WORKFLOWS = (
    "smc-library-refresh.yml",
    "credential-health-check.yml",
    "c13-daily-cron.yml",
    "run-open-prep-daily.yml",
    "promotion-gate-daily.yml",
    "f2-promotion-gate-daily.yml",
    "fvg-quality-recal-shadow-daily.yml",
    "feature-importance-daily.yml",
)


@pytest.mark.parametrize("monitored", _MONITORED_WORKFLOWS)
def test_each_critical_cron_is_monitored(workflow_text: str, monitored: str) -> None:
    assert f"{monitored}=" in workflow_text, (
        f"{monitored} is on the critical-path cron list but the freshness "
        f"monitor stopped watching it — re-add `{monitored}=<budget_hours>` "
        f"to the probe step CLI."
    )


def test_monitored_inventory_is_complete(workflow_text: str) -> None:
    """Fail loud if a NEW `<name>.yml=<hours>` arg appears without a pin entry."""
    # Match tokens that look like `something.yml=<int>` in the probe step.
    pattern = re.compile(r"\b([a-z0-9_-]+\.yml)=\d+\b")
    found = set(pattern.findall(workflow_text))
    pinned = set(_MONITORED_WORKFLOWS)
    new = found - pinned
    assert not new, (
        f"freshness monitor watches new workflows {sorted(new)} that are not "
        f"in this test's `_MONITORED_WORKFLOWS` ledger — add them so the pin "
        f"and the workflow stay in lockstep."
    )


# ---------------------------------------------------------------------------
# Failure surfacing (must NOT silently swallow rc)
# ---------------------------------------------------------------------------


def test_probe_step_captures_and_surfaces_rc(workflow_text: str) -> None:
    """The whole point of this workflow is that it CANNOT silently skip."""
    assert "rc=$?" in workflow_text, "probe step must capture $? immediately"
    # Forbidden patterns: any swallow around the freshness script.
    forbidden = (
        re.compile(r"python\s+scripts/check_workflow_freshness\.py[^\n]*\|\|\s*true"),
        re.compile(r"python\s+scripts/check_workflow_freshness\.py[^\n]*;\s*true"),
    )
    for pat in forbidden:
        assert not pat.search(workflow_text), (
            f"freshness probe must not swallow failures: {pat.pattern}"
        )


def test_workflow_fails_job_on_nonzero_rc(workflow_text: str) -> None:
    # Final step re-surfaces rc. Must exit with the captured value, not 0.
    assert 'exit "${{ steps.probe.outputs.rc }}"' in workflow_text, (
        "final fail-step MUST exit with the captured probe rc so the job "
        "conclusion reflects the freshness verdict"
    )


# ---------------------------------------------------------------------------
# Annotations + issue surface
# ---------------------------------------------------------------------------


def test_workflow_surfaces_annotations(workflow_text: str) -> None:
    assert "::error title=workflow-freshness::" in workflow_text, (
        "stale/error states must produce ::error:: annotations so they show "
        "up in the run summary, not just in JSON"
    )
    assert "GITHUB_STEP_SUMMARY" in workflow_text, (
        "must write a human-readable summary to GITHUB_STEP_SUMMARY"
    )


def test_workflow_opens_cron_failure_issue_with_dedup(workflow_text: str) -> None:
    # Same dedup pattern as credential-health-check.yml.
    assert "gh issue list" in workflow_text, "must dedup via gh issue list"
    assert "gh issue comment" in workflow_text, (
        "must comment on the existing same-day issue instead of opening a duplicate"
    )
    assert "gh issue create" in workflow_text, "must create a new issue when none exists"
    assert "--label cron-failure" in workflow_text, "issue must carry cron-failure label"
    assert "--label automated" in workflow_text, "issue must carry automated label"


def test_workflow_uploads_report_artifact(workflow_text: str) -> None:
    assert "actions/upload-artifact@" in workflow_text, (
        "report artifact must be uploaded for audit retention"
    )
    assert "workflow-freshness-report" in workflow_text, (
        "artifact must be named `workflow-freshness-report` (consumers depend on this)"
    )


def test_workflow_uses_gh_pat_with_token_fallback(workflow_text: str) -> None:
    # Same auth pattern as the rest of the cron-failure-issue family — the
    # default GITHUB_TOKEN sometimes lacks visibility on cross-workflow runs.
    assert (
        "${{ secrets.GH_PAT != '' && secrets.GH_PAT || github.token }}"
        in workflow_text
    ), "must prefer GH_PAT with github.token fallback"


# ---------------------------------------------------------------------------
# Step timeout
# ---------------------------------------------------------------------------


def test_workflow_has_step_timeout(workflow: dict) -> None:
    jobs = workflow.get("jobs") or {}
    probe = jobs.get("probe")
    assert probe is not None, "expected single `probe` job"
    assert probe.get("timeout-minutes"), (
        "probe job MUST set timeout-minutes so a hung GH API call cannot "
        "burn the full 6h GHA default"
    )
