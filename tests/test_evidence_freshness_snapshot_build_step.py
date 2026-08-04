"""What ``evidence-freshness-snapshot.yml``'s build step decides, executed.

The step publishes one constant, ``status=success``, and the publish step is
gated on it. The decision is therefore not *what* it writes but *whether it
gets there* -- ``set -euo pipefail` is the entire mechanism, and there is no
literal pair anywhere in the block to compare.

Measured 2026-08-04 against a green unmutated baseline of the full suite:
appending ``|| true`` to the snapshot build left all **24708 tests green**.
``status=success`` would then be published after a failed build, and the
consumer would commit a stale freshness snapshot to the rolling branch as
though it were fresh -- on a workflow whose only product is a claim about
freshness.

Not a value-preserving mutation, so a whole-line source pin would also have
caught it. None existed.
"""

from __future__ import annotations

from pathlib import Path

from tests._fast_gates_gate import evaluate_condition, step_conditions
from tests._workflow_step_shell import Stub, declares_bash_default, run_step

WORKFLOW = "evidence-freshness-snapshot.yml"
STEP = "Build evidence-freshness snapshot"
PUBLISH = "Publish snapshot to rolling bot branch"
AUDIT_BRANCH = "origin/data/phase-a-audit"

_CONDITIONS = step_conditions(
    Path(__file__).resolve().parents[1] / ".github" / "workflows" / WORKFLOW,
    job="snapshot",
)


def _build(tmp_path: Path, rc: int):
    tmp_path.mkdir(parents=True, exist_ok=True)
    return run_step(WORKFLOW, STEP, tmp_path, env={},
                    stubs={"python": Stub(exit_code=rc)})


def _publishes(outputs: dict[str, str]) -> bool:
    return evaluate_condition(_CONDITIONS[PUBLISH],
                              {"build.status": outputs.get("status", "")})


def test_the_workflow_still_declares_the_shell_this_harness_runs() -> None:
    assert declares_bash_default(WORKFLOW)


def test_a_successful_build_publishes_the_snapshot(tmp_path: Path) -> None:
    result = _build(tmp_path, 0)
    assert result.returncode == 0, result.stderr
    assert result.outputs["status"] == "success"
    assert _publishes(result.outputs)


def test_a_failed_build_publishes_no_status_and_nothing_is_committed(tmp_path: Path) -> None:
    """The assertion this file exists for.

    `status=success` sits on the line after the build, so `set -e` is what
    stops it being reached. An output the step never wrote is '' in Actions,
    which is what makes the consumer's `== 'success'` false -- and that chain
    is invisible to any assertion on the block's source.
    """
    result = _build(tmp_path, 1)
    assert result.returncode != 0, "a failed snapshot build must fail the step"
    assert "status" not in result.outputs, result.outputs
    assert not _publishes(result.outputs), (
        "a stale snapshot must not reach the rolling branch labelled fresh"
    )


def test_the_snapshot_is_built_from_the_audit_branch(tmp_path: Path) -> None:
    """Read off the recorded invocation: the branch is the whole input.

    Pointed at anything else the workflow still reports success and still
    publishes -- it would just be measuring the freshness of the wrong thing.
    """
    call = _build(tmp_path, 0).called_with("build_evidence_freshness_snapshot")
    assert call, "the snapshot builder never ran"
    assert f"--audit-branch {AUDIT_BRANCH}" in call[0], call[0]
    assert "--output artifacts/monitoring/evidence_freshness.json" in call[0], call[0]


def test_the_output_directory_exists_before_the_build_runs(tmp_path: Path) -> None:
    """`mkdir -p` precedes the build; without it the builder fails on a fresh runner."""
    _build(tmp_path, 0)
    assert (tmp_path / "artifacts" / "monitoring").is_dir()
