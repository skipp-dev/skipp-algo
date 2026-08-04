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


# --- the evaluation verdict, executed ---------------------------------------
#
# `evaluate` publishes status and files_scanned; later steps read both.
# Measured 2026-08-04 with a value-preserving arm swap on status
# (failed <-> success): all 9 assertions across the 2 files that name this
# workflow stayed green -- a failed evaluation would have reported success.

import sys
from pathlib import Path

from tests._workflow_step_shell import Stub, run_step

_EVAL_STEP = "Run Plan 2.8 evaluation script"


def _evaluate(tmp_path: Path, *, writes_report: bool, files_scanned: int = 42):
    return run_step(
        "plan-2-8-evaluation.yml", _EVAL_STEP, tmp_path,
        env={"REAL_PYTHON": sys.executable, "N": str(files_scanned)},
        stubs={"python": Stub(script=f'''
case "$1" in -c) exec "$REAL_PYTHON" "$@" ;; esac
out=""; prev=""
for a in "$@"; do [ "$prev" = "--output" ] && out="$a"; prev="$a"; done
if [ -n "$out" ] && [ "{int(writes_report)}" = "1" ]; then
  mkdir -p "$(dirname "$out")"; printf '{{"files_scanned": %s}}' "$N" > "$out"
fi
exit 0
''')},
    )


def test_a_written_rollup_is_a_success_with_its_real_count(tmp_path: Path) -> None:
    result = _evaluate(tmp_path, writes_report=True, files_scanned=137)
    assert result.returncode == 0, result.stderr
    assert result.outputs["status"] == "success"
    assert result.outputs["files_scanned"] == "137", (
        "the count must come from the rollup, not from a constant; "
        f"got {result.outputs}"
    )


def test_a_silent_script_that_wrote_nothing_is_a_failure(tmp_path: Path) -> None:
    """Exit 0 without a rollup must not read as success.

    This is the only way the else branch is reachable at all: the step runs
    under `set -euo pipefail`, so a script that exits non-zero takes the step
    down before the check. A tool that fails quietly is exactly what the branch
    is for.
    """
    result = _evaluate(tmp_path, writes_report=False)
    assert result.returncode == 0, result.stderr
    assert result.outputs["status"] == "failed"
    assert result.outputs["files_scanned"] == "0"
