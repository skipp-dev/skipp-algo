"""Structural pin tests for ``.github/workflows/workflow-freshness-monitor.yml``.

Locks the shape of the daily out-of-band cron freshness probe so a
future regression cannot silently weaken it — same defensive pattern
used by ``tests/test_credential_health_workflow.py`` (Bundle C) and
``tests/test_tv_preflight_retry_telemetry.py`` (Bundle B).
"""

from __future__ import annotations

from pathlib import Path

import pytest

WORKFLOW = Path(".github/workflows/workflow-freshness-monitor.yml")


@pytest.fixture(scope="module")
def text() -> str:
    assert WORKFLOW.exists(), f"workflow file missing: {WORKFLOW}"
    return WORKFLOW.read_text(encoding="utf-8")


def test_workflow_name_pinned(text: str) -> None:
    assert "name: workflow-freshness-monitor" in text


def test_runs_daily_after_credential_health(text: str) -> None:
    # 06:30 UTC -- intentionally 30 min after credential-health-check
    # so its issue is filed first.
    assert '- cron: "30 6 * * *"' in text


def test_workflow_dispatch_allowed(text: str) -> None:
    assert "workflow_dispatch: {}" in text


def test_permissions_minimal_but_can_file_issues(text: str) -> None:
    assert "contents: read" in text
    assert "issues: write" in text
    # Must NOT have actions:write — this monitor only READS workflow runs.
    assert "actions: write" not in text


def test_invokes_freshness_script(text: str) -> None:
    assert "python scripts/check_workflow_freshness.py" in text


def test_writes_report_to_pinned_path(text: str) -> None:
    assert "--output artifacts/ci/workflow_freshness.json" in text


def test_monitors_critical_crons_with_budgets(text: str) -> None:
    # Workflows whose silent skip would invalidate promotion / SPRT /
    # daily data pipelines. New rows are fine; removing any of these
    # must be a deliberate, reviewed change.
    must_monitor = [
        "smc-library-refresh.yml=30",
        "credential-health-check.yml=30",
        "c13-daily-cron.yml=30",
        "run-open-prep-daily.yml=30",
        "promotion-gate-daily.yml=30",
        "f2-promotion-gate-daily.yml=30",
        "fvg-quality-recal-shadow-daily.yml=30",
        "feature-importance-daily.yml=30",
    ]
    for spec in must_monitor:
        assert spec in text, f"freshness monitor is no longer probing {spec}"


def test_rc_captured_and_re_exit_pattern(text: str) -> None:
    # Must capture rc inside a `set +e` scope AND re-exit with that rc
    # in a later step — the explicit-exit-check pattern Bundle D's
    # global invariant test enforces. Anything else is a silent-skip.
    assert "set +e" in text
    assert "rc=$?" in text
    assert 'echo "rc=$rc" >> "$GITHUB_OUTPUT"' in text
    assert 'exit "${{ steps.probe.outputs.rc }}"' in text


def test_final_step_runs_on_nonzero_rc(text: str) -> None:
    # The fail-job step must be gated on rc != '0' AND rc != ''. The
    # `!= ''` guard prevents firing when the probe step itself never
    # set the output (e.g. setup-python crashed earlier).
    assert "steps.probe.outputs.rc != '0'" in text
    assert "steps.probe.outputs.rc != ''" in text


def test_overall_outcome_published_to_step_output(text: str) -> None:
    assert 'echo "overall=$overall"' in text


def test_files_dedup_issue_on_stale_or_error(text: str) -> None:
    assert "steps.probe.outputs.overall == 'stale'" in text
    assert "steps.probe.outputs.overall == 'error'" in text
    assert "gh issue list" in text
    assert "gh issue comment" in text
    assert "gh issue create" in text
    assert "--label cron-failure" in text


def test_uploads_freshness_artifact(text: str) -> None:
    assert "actions/upload-artifact@" in text
    assert "name: workflow-freshness-report" in text
    assert "path: artifacts/ci/workflow_freshness.json" in text
    assert "retention-days: 30" in text


def test_uses_pinned_action_shas(text: str) -> None:
    # Pin checks defend against tag-mutation supply-chain risk —
    # same SHA discipline as the credential-health workflow.
    assert "actions/checkout@34e114876b0b11c390a56381ad16ebd13914f8d5" in text
    assert "actions/setup-python@e348410e00f449f3bb50f72fda1d4f7600fc1b04" in text
    assert "actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a" in text


def test_token_prefers_gh_pat_with_fallback(text: str) -> None:
    # GH_PAT preferred (broader scope for reading workflow runs);
    # falls back to the ephemeral github.token if PAT unset.
    assert "secrets.GH_PAT != '' && secrets.GH_PAT || github.token" in text


def test_concurrency_group_pinned(text: str) -> None:
    # Prevents the daily cron from racing with a workflow_dispatch
    # of itself; cancel-in-progress=false keeps the scheduled run.
    assert "group: workflow-freshness-monitor" in text
    assert "cancel-in-progress: false" in text


def test_pythonunbuffered_set(text: str) -> None:
    # Same invariant pinned by tests/test_workflow_python_unbuffered.py.
    assert 'PYTHONUNBUFFERED: "1"' in text


def test_job_has_timeout(text: str) -> None:
    # 5 min is generous for a few API calls; absence of timeout-minutes
    # would let a hung request burn the default 6h GHA budget.
    assert "timeout-minutes: 5" in text
