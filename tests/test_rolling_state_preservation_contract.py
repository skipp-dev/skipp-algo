from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"


def _steps(workflow: str, job: str) -> list[dict]:
    data = yaml.safe_load((WORKFLOWS / workflow).read_text(encoding="utf-8"))
    return data["jobs"][job]["steps"]


def _step(steps: list[dict], name: str) -> dict:
    return next(step for step in steps if step.get("name") == name)


def test_weekly_digest_does_not_replace_archive_after_restore_failure() -> None:
    steps = _steps("plan-2-8-weekly-digest.yml", "weekly-digest")
    condition = "always() && steps.dl_digest_archive.outcome == 'success'"
    assert _step(steps, "Plan 2.8 digest archive + weekly compare")["if"] == condition
    assert _step(steps, "Upload Plan 2.8 digest archive")["if"] == condition


def test_weekly_digest_does_not_replace_status_ledger_after_restore_failure() -> None:
    steps = _steps("plan-2-8-weekly-digest.yml", "weekly-digest")
    condition = "always() && steps.dl_status_ledger.outcome == 'success'"
    assert _step(steps, "Plan 2.8 status ledger append")["if"] == condition
    assert _step(steps, "Upload Plan 2.8 status ledger")["if"] == condition


def test_library_refresh_does_not_replace_failure_history_after_restore_failure() -> None:
    steps = _steps("smc-library-refresh.yml", "refresh")
    condition = "always() && steps.dl_best_effort_history.outcome == 'success'"
    assert _step(steps, "Best-effort failure summary")["if"] == condition
    assert _step(steps, "Upload best-effort failure history")["if"] == condition


def test_stateful_snapshot_workflows_use_fail_closed_remote_tip_publisher() -> None:
    expected = {
        "smc-live-news-refresh.yml": ("refresh", "bot/live-news-snapshot"),
        "run-open-prep-daily.yml": ("run", "bot/live-open-prep-snapshot"),
        "smc-measurement-benchmark-rolling.yml": (
            "rolling-benchmark",
            "bot/live-experiment-snapshot",
        ),
    }
    for workflow, (job, branch) in expected.items():
        runs = "\n".join(str(step.get("run") or "") for step in _steps(workflow, job))
        assert "scripts/publish_bot_snapshot.py" in runs, workflow
        assert f"--branch {branch}" in runs, workflow


# ---------------------------------------------------------------------------
# The publisher being fail-closed says nothing about its INPUT being complete.
# plan-2-8-evaluation.yml appended to a history that a fresh checkout of main
# never contains, then published the result — so every run replaced the
# accumulated history with a single row. Measured 2026-08-07: the published
# file carried 1 row while the sibling producer's carried 133, and the
# publisher test above was green the whole time.
# ---------------------------------------------------------------------------

_HISTORY_PUBLISHERS = {
    "smc-measurement-benchmark-rolling.yml": (
        "rolling-benchmark",
        "restore_history",
        "Plan 2.8 history archive (snapshot append)",
    ),
}


def test_history_publishers_restore_before_they_append() -> None:
    """A history that lives on a bot branch must be read back into the checkout
    before anything appends to it, and the append must not run if that failed."""
    for workflow, (job, restore_id, append_name) in _HISTORY_PUBLISHERS.items():
        steps = _steps(workflow, job)
        ids = [step.get("id") for step in steps]
        names = [step.get("name") for step in steps]
        assert restore_id in ids, f"{workflow}: no {restore_id!r} step"
        assert ids.index(restore_id) < names.index(append_name), (
            f"{workflow}: {restore_id!r} must run before {append_name!r}"
        )
        condition = str(_step(steps, append_name).get("if") or "")
        assert f"steps.{restore_id}.outcome == 'success'" in condition, (
            f"{workflow}: {append_name!r} must not append onto a failed restore"
        )


def test_history_restore_fails_closed_on_an_unexplained_fetch_error() -> None:
    """A missing branch bootstraps; anything else must stop the run. Continuing
    here is what turns a transient fetch error into a truncated history."""
    for workflow, (job, restore_id, _) in _HISTORY_PUBLISHERS.items():
        steps = _steps(workflow, job)
        matches = [step for step in steps if step.get("id") == restore_id]
        assert matches, f"{workflow}: no {restore_id!r} step"
        run = str(matches[0].get("run") or "")
        assert "exit 1" in run, f"{workflow}: restore must be able to fail the run"
        assert "refusing to replace" in run, (
            f"{workflow}: restore failure must say why it refuses to continue"
        )
