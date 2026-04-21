"""Pin-tests for the Plan 2.8 history-rotate wiring in the rolling bench."""

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


def _idx(prefix: str) -> int:
    for i, s in enumerate(_steps()):
        if s.get("name", "").startswith(prefix):
            return i
    raise AssertionError(f"no step starts with {prefix!r}")


def _step(prefix: str) -> dict:
    return _steps()[_idx(prefix)]


def test_history_rotate_step_present_and_always() -> None:
    step = _step("Plan 2.8 history rotate")
    assert step["if"].strip() == "always()"


def test_history_rotate_runs_after_archive_and_before_upload() -> None:
    assert (
        _idx("Plan 2.8 history archive")
        < _idx("Plan 2.8 history rotate")
        < _idx("Upload rolling benchmark artifacts")
    )


def test_history_rotate_invokes_rotator_with_caps() -> None:
    run = _step("Plan 2.8 history rotate")["run"]
    assert "scripts/plan_2_8_history_rotate.py" in run
    assert "--max-rows     366" in run
    assert "--max-age-days 400" in run
    assert "plan_2_8_history.jsonl" in run


def test_history_rotate_is_fail_soft_and_guards_missing_history() -> None:
    run = _step("Plan 2.8 history rotate")["run"]
    assert "set +e" in run
    assert run.rstrip().endswith("true")
    assert "if [ -s " in run
