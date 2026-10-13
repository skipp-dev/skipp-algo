"""Pin-tests for the Plan 2.8 history-validate wiring in the rolling bench."""

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


def test_history_validate_step_present_and_always() -> None:
    step = _step("Plan 2.8 history validate")
    assert step["if"].strip() == "always()"


def test_history_validate_runs_after_rotate_and_before_upload() -> None:
    assert (
        _idx("Plan 2.8 history rotate")
        < _idx("Plan 2.8 history validate")
        < _idx("Upload rolling benchmark artifacts")
    )


def test_history_validate_invokes_validator_with_quiet_and_output() -> None:
    run = _step("Plan 2.8 history validate")["run"]
    assert "scripts/plan_2_8_history_validate.py" in run
    assert "--quiet" in run
    assert "plan_2_8_history_validate.json" in run


def test_history_validate_streams_report_to_step_summary() -> None:
    run = _step("Plan 2.8 history validate")["run"]
    assert "Plan 2.8 history validate" in run
    assert "GITHUB_STEP_SUMMARY" in run


def test_history_validate_is_fail_soft() -> None:
    run = _step("Plan 2.8 history validate")["run"]
    assert "set +e" in run
    assert run.rstrip().endswith("true")
    assert "if [ -s " in run
