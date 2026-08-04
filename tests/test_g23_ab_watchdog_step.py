"""What ``g23-ab-watchdog.yml``'s watchdog step decides, executed.

The step deliberately folds exit codes 2/3/4 into a green job so the run can
post-process them, which makes ``exit_code`` the ONLY carrier of the §G2/§G3
governance signal. Three issue-opening steps read nothing else.

Measured 2026-08-04 against a green unmutated baseline of the full suite:
replacing ``echo "exit_code=$rc"`` with ``echo "exit_code=0"`` left all
**24708 tests green** -- while a watchdog stuck at 0 opens no issue ever again
and the job stays as green as it always was, which is exactly what the folding
makes it look like.

Not a value-preserving mutation (``$rc`` has no second literal arm), so a
whole-line source pin would have caught it too. None existed.
"""

from __future__ import annotations

from pathlib import Path

from tests._fast_gates_gate import evaluate_condition, step_conditions
from tests._workflow_step_shell import Stub, declares_bash_default, run_step

WORKFLOW = "g23-ab-watchdog.yml"
STEP = "Run G2/G3 watchdog"

ROLLBACK = "Open issue on §G2 rollback signal"
PROMOTION = "Open issue on §G3 promotion-ready signal"
FUTILITY = "Open issue on §G3 futility signal"

_CONDITIONS = step_conditions(
    Path(__file__).resolve().parents[1] / ".github" / "workflows" / WORKFLOW,
    job="watchdog",
)

# The step reads `/tmp/ab_comparison.json` by absolute path to decide whether
# to pass `--input`. That path is outside anything this harness can shadow, so
# the input-args branch is NOT covered here -- stated rather than faked by
# writing into a shared /tmp during a test run.


def _watchdog(tmp_path: Path, rc: int):
    tmp_path.mkdir(parents=True, exist_ok=True)
    return run_step(
        WORKFLOW, STEP, tmp_path,
        env={"GITHUB_SHA": "0" * 40, "GITHUB_RUN_ID": "12345"},
        stubs={"python": Stub(exit_code=rc)},
        expressions={"github.sha": "0" * 40, "github.run_id": "12345"},
    )


def test_the_workflow_still_declares_the_shell_this_harness_runs() -> None:
    assert declares_bash_default(WORKFLOW)


def test_a_clean_run_reports_zero_and_stays_green(tmp_path: Path) -> None:
    result = _watchdog(tmp_path, 0)
    assert result.returncode == 0
    assert result.outputs["exit_code"] == "0"
    assert result.called_with("scripts.g23_ab_watchdog", "--history", "--status-md")


def test_each_governance_signal_reaches_its_own_issue_step(tmp_path: Path) -> None:
    """2, 3 and 4 are three different signals, and each opens a different issue.

    Asserting only "non-zero survives" would let all three collapse onto one
    code without a test noticing -- the run would still be green and an issue
    would still open, just the wrong one.
    """
    for code, expected in ((2, ROLLBACK), (3, PROMOTION), (4, FUTILITY)):
        result = _watchdog(tmp_path / f"c{code}", code)
        assert result.outputs["exit_code"] == str(code), result.outputs
        assert result.returncode == 0, (
            f"exit {code} is a governance signal, not a failure: {result.stderr}"
        )
        outputs = {"watchdog.exit_code": result.outputs["exit_code"]}
        fired = [n for n in (ROLLBACK, PROMOTION, FUTILITY)
                 if evaluate_condition(_CONDITIONS[n], outputs)]
        assert fired == [expected], f"exit {code} fired {fired}"


def test_a_real_crash_still_fails_the_job(tmp_path: Path) -> None:
    """The folding is scoped to 0/2/3/4. Everything else must stay a failure.

    Widening the `case` to `*)` would turn a crashed watchdog into a green run
    that opens no issue -- indistinguishable from a healthy one in the outputs.
    """
    result = _watchdog(tmp_path, 1)
    assert result.returncode == 1, "a watchdog crash must not be folded into success"
    assert result.outputs["exit_code"] == "1"
    assert not any(evaluate_condition(_CONDITIONS[n], {"watchdog.exit_code": "1"})
                   for n in (ROLLBACK, PROMOTION, FUTILITY))


def test_an_unexpected_code_is_passed_through_not_swallowed(tmp_path: Path) -> None:
    result = _watchdog(tmp_path, 9)
    assert result.returncode == 9
    assert result.outputs["exit_code"] == "9"
