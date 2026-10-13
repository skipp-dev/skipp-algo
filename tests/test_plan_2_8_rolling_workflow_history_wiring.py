"""Pin-tests for the Plan 2.8 history-archive wiring in the rolling bench.

Sister file to ``test_plan_2_8_rolling_workflow_rollup_wiring.py``:
guards the new "Plan 2.8 history archive" step that folds each daily
rollup into ``plan_2_8_history.jsonl`` for the weekly trend digest.
"""

from __future__ import annotations

from pathlib import Path

import yaml

WORKFLOW = (
    Path(__file__).resolve().parents[1]
    / ".github" / "workflows"
    / "smc-measurement-benchmark-rolling.yml"
)


def _steps() -> list[dict]:
    wf = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    return wf["jobs"]["rolling-benchmark"]["steps"]


def _step(prefix: str) -> dict:
    for s in _steps():
        if s.get("name", "").startswith(prefix):
            return s
    raise AssertionError(f"step starting with {prefix!r} not found")


def _idx(prefix: str) -> int:
    for i, s in enumerate(_steps()):
        if s.get("name", "").startswith(prefix):
            return i
    raise AssertionError(f"no step starts with {prefix!r}")


def test_history_archive_step_present_and_always() -> None:
    step = _step("Plan 2.8 history archive")
    assert step["if"].strip() == "always()"


def test_history_archive_runs_after_rollup_and_before_upload() -> None:
    i_rollup  = _idx("Plan 2.8 Phase 1 per-TF family rollup")
    i_archive = _idx("Plan 2.8 history archive")
    i_upload  = _idx("Upload rolling benchmark artifacts")
    assert i_rollup < i_archive < i_upload


def test_history_archive_invokes_archiver_with_rollup_and_history_paths() -> None:
    run = _step("Plan 2.8 history archive")["run"]
    assert "scripts/plan_2_8_history_archive.py" in run
    assert "plan_2_8_tf_family_rollup.json" in run
    assert "plan_2_8_history.jsonl" in run


def test_history_archive_writes_inside_benchmark_out_dir_for_upload() -> None:
    run = _step("Plan 2.8 history archive")["run"]
    assert "${{ steps.meta.outputs.out_dir }}/plan_2_8_history.jsonl" in run


def test_history_archive_is_fail_soft() -> None:
    run = _step("Plan 2.8 history archive")["run"]
    assert "set +e" in run
    assert run.rstrip().endswith("true")
    # Skip when the rollup did not write anything.
    assert "if [ -s " in run
