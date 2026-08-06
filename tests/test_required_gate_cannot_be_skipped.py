"""The required status check must not be satisfiable by being skipped.

GitHub's own status-checks reference is unambiguous: "A job that is skipped
will report its status as 'Success'. It will not prevent a pull request from
merging, even if it is a required check." The troubleshooting page names the
way in -- "A job depends on a failed job" -> "The dependent job is skipped and
may not block merging" -- and prescribes the remedy: "Use ``always()`` with
``needs`` for required checks that depend on other jobs."

Measured 2026-08-06: ``fast-gates`` is the single required check of the
``main-governance`` ruleset, it carries ``needs: select-runner``, and it has no
job-level ``if``. So a failing ``select-runner`` skips it, the skip reports
Success, and a pull request becomes mergeable with no gate having run at all.
Over the preceding 60 runs ``select-runner`` never failed, so the hole is
structural rather than realised -- which is exactly when it is cheap to close.

The verdict job below is asserted by EXECUTING its shell against every
combination of upstream results, not by matching its text: what has to hold is
that only a real pass exits 0.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
import yaml

_REPO_ROOT = Path(__file__).resolve().parents[1]
_WF = _REPO_ROOT / ".github" / "workflows" / "smc-fast-pr-gates.yml"

#: The job branch protection points at. Changing this name is a ruleset change,
#: not a rename -- the old name would keep passing as a stale required check.
_REQUIRED_JOB = "gate"


def _jobs() -> dict:
    return yaml.safe_load(_WF.read_text(encoding="utf-8"))["jobs"]


def _gate() -> dict:
    jobs = _jobs()
    assert _REQUIRED_JOB in jobs, (
        f"{_REQUIRED_JOB!r} is the required check of the main-governance "
        f"ruleset; the workflow defines {sorted(jobs)}"
    )
    return jobs[_REQUIRED_JOB]


def _verdict_fragment() -> str:
    steps = _gate()["steps"]
    assert len(steps) == 1, "the verdict job stays a single step doing one thing"
    return steps[0]["run"]


def test_the_gate_runs_even_when_everything_it_watches_failed() -> None:
    """``always()``, and not ``!cancelled()``.

    This is the one place the repo prefers ``always()``: a gate guarded by
    ``!cancelled()`` is SKIPPED on cancellation, and a skipped required check
    reports Success -- reopening the hole it exists to close. The usual
    argument against ``always()`` (a run that hangs to timeout) does not apply
    to a job that checks out nothing and only reads results.
    """
    condition = str(_gate().get("if", ""))
    assert "always()" in condition, (
        f"the required check must run unconditionally; got {condition!r}"
    )
    assert "cancelled()" not in condition, (
        "!cancelled() lets a cancelled run skip the gate, and a skipped "
        "required check reports Success to branch protection"
    )


def test_the_gate_watches_every_job_that_could_silently_skip_it() -> None:
    needs = _gate()["needs"]
    assert set(needs) == {"select-runner", "fast-gates"}, (
        "every job whose failure could skip the real work must be inspected "
        f"by the gate; got {needs}"
    )
    # A job that never runs the work cannot inherit the work's runner choice.
    assert "needs.select-runner" not in str(_gate()["runs-on"]), (
        "the gate must not depend on select-runner's output for its own "
        "runner, or a failed selection takes the gate down with it"
    )


@pytest.mark.parametrize(
    ("select_runner", "fast_gates", "expected_rc"),
    [
        ("success", "success", 0),
        # The measured hole: select-runner fails, fast-gates is skipped, and a
        # skip reports Success. The gate must call that what it is.
        ("failure", "skipped", 1),
        ("success", "failure", 1),
        ("success", "skipped", 1),
        ("success", "cancelled", 1),
        ("cancelled", "skipped", 1),
        ("skipped", "skipped", 1),
        # An empty result is what an expression yields for a job that never
        # materialised; it is not a pass either.
        ("", "", 1),
    ],
)
def test_only_a_real_pass_exits_zero(
    select_runner: str, fast_gates: str, expected_rc: int, tmp_path: Path
) -> None:
    """EXECUTED against the shipped shell, one case per upstream combination."""
    summary = tmp_path / "summary.md"
    done = subprocess.run(
        ["/bin/bash", "-c", _verdict_fragment()],
        env={
            "PATH": os.environ["PATH"],
            "SELECT_RUNNER_RESULT": select_runner,
            "FAST_GATES_RESULT": fast_gates,
            "GITHUB_STEP_SUMMARY": str(summary),
        },
        capture_output=True,
        text=True,
    )
    assert done.returncode == expected_rc, (
        f"select-runner={select_runner!r} fast-gates={fast_gates!r} "
        f"exited {done.returncode}, expected {expected_rc}\n"
        f"{done.stdout}{done.stderr}"
    )
    # Whatever it decides, it says both results out loud -- a red gate whose
    # log does not name the cause sends the reader to the wrong job.
    assert (select_runner or "empty") in done.stdout
    assert (fast_gates or "empty") in done.stdout
