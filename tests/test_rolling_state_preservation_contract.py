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
        "plan-2-8-evaluation.yml": ("evaluate", "bot/live-experiment-snapshot"),
    }
    for workflow, (job, branch) in expected.items():
        runs = "\n".join(str(step.get("run") or "") for step in _steps(workflow, job))
        assert "scripts/publish_bot_snapshot.py" in runs, workflow
        assert f"--branch {branch}" in runs, workflow
