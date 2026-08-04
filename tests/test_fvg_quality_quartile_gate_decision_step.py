"""What ``fvg-quality-quartile-gate.yml``'s decision step decides, executed.

One output, ``release_gate``, and one consumer that opens the release issue on
``== 'PASS'``. The step's only job is to turn a file that may not exist into a
verdict, so its fallback IS the decision.

Measured 2026-08-04 against a green unmutated baseline of the full suite:
turning the missing-file fallback ``DEC="MISSING"`` into ``DEC="PASS"`` left all
**24708 tests green**. An absent ``release_gate.json`` would then read as a
release approval -- fail-open on a gate whose only purpose is to block.

Not a value-preserving mutation, so a whole-line source pin would also have
caught it. None existed.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from tests._fast_gates_gate import evaluate_condition, step_conditions
from tests._workflow_step_shell import Stub, declares_bash_default, run_step

WORKFLOW = "fvg-quality-quartile-gate.yml"
STEP = "Capture decision for downstream steps"
GATE_FILE = Path("docs/fvg_quality/release_gate.json")
RELEASE_ISSUE = "Open issue when release-gate flips to PASS"

_CONDITIONS = step_conditions(
    Path(__file__).resolve().parents[1] / ".github" / "workflows" / WORKFLOW,
    job="evaluate",
)


def _decide(tmp_path: Path, verdict: str | None):
    """``verdict=None`` means the gate file was never produced."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    if verdict is not None:
        target = tmp_path / GATE_FILE
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps({"release_gate": verdict}), encoding="utf-8")
    # The `python -c` that reads the file is the computation under test, so it
    # runs for real rather than being faked into agreeing with the assertion.
    return run_step(WORKFLOW, STEP, tmp_path, env={},
                    stubs={"python": Stub(passthrough=sys.executable)})


def _opens_release_issue(release_gate: str) -> bool:
    return evaluate_condition(_CONDITIONS[RELEASE_ISSUE], {"decision.release_gate": release_gate})


def test_the_workflow_still_declares_the_shell_this_harness_runs() -> None:
    assert declares_bash_default(WORKFLOW)


def test_a_pass_verdict_is_read_out_of_the_file(tmp_path: Path) -> None:
    result = _decide(tmp_path, "PASS")
    assert result.outputs["release_gate"] == "PASS", result.outputs
    assert _opens_release_issue(result.outputs["release_gate"])


def test_a_fail_verdict_does_not_open_the_release_issue(tmp_path: Path) -> None:
    """The control direction: without it, `PASS` could be published constantly."""
    result = _decide(tmp_path, "FAIL")
    assert result.outputs["release_gate"] == "FAIL"
    assert not _opens_release_issue(result.outputs["release_gate"])


def test_a_missing_gate_file_is_not_a_pass(tmp_path: Path) -> None:
    """The assertion this file exists for: no evidence is not a green light.

    A gate that fails open when its own input is absent is worse than no gate,
    because the run still reports that the gate was evaluated.
    """
    result = _decide(tmp_path, None)
    assert result.outputs["release_gate"] == "MISSING", result.outputs
    assert not _opens_release_issue(result.outputs["release_gate"]), (
        "an absent release_gate.json must never approve a release"
    )


def test_the_step_survives_a_missing_file_rather_than_dying_under_set_e(tmp_path: Path) -> None:
    """`set -euo pipefail` is on; the fallback has to be reached, not skipped.

    If the file check were written so the failure propagated, the step would
    die before publishing anything and the consumer would read '' -- which also
    does not equal 'PASS', so the gate would look correct while publishing
    nothing at all.
    """
    result = _decide(tmp_path, None)
    assert result.returncode == 0, result.stderr
    assert "release_gate" in result.outputs
