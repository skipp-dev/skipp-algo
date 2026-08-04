"""What ``rl-research-training.yml``'s artifact step decides, executed.

The RL half of the same decision as ``ml-family-research.yml``: notice that a
run which asked for cuda resolved to something else, so a silent CPU fallback
does not pass as a healthy GPU run.

Measured 2026-08-04 against a green unmutated baseline of the full suite:
inverting ``requested == 'cuda' and resolved != 'cuda'`` to ``… resolved ==
'cuda'`` left all **24708 tests green**. The warning would fire exactly when
cuda *was* used and stay silent when it was not.

Kept beside its workflow rather than folded into the ML file: the two
extraction paths differ (one artifact reports a single device, the other a set
per family), and a shared test would have to fake one of them to fit.

Not a value-preserving mutation, so a whole-line source pin would also have
caught it. None existed.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from tests._fast_gates_gate import evaluate_condition, step_conditions
from tests._workflow_step_shell import declares_bash_default, run_step

WORKFLOW = "rl-research-training.yml"
STEP = "Summarise RL artifact"
WARN = "Warn on RL fallback"

_CONDITIONS = step_conditions(
    Path(__file__).resolve().parents[1] / ".github" / "workflows" / WORKFLOW,
    job="research",
)


def _summarise(tmp_path: Path, payload: dict | None, *, requested: str = "cuda"):
    tmp_path.mkdir(parents=True, exist_ok=True)
    artifact = tmp_path / "latest.json"
    if payload is not None:
        artifact.write_text(json.dumps(payload), encoding="utf-8")
    return run_step(
        WORKFLOW, STEP, tmp_path,
        env={"RL_ARTIFACT_PATH": str(artifact), "SMC_PYTHON_BIN": sys.executable,
             "SKIPP_RL_DEVICE": requested},
    )


def _warns(outputs: dict[str, str]) -> bool:
    return evaluate_condition(
        _CONDITIONS[WARN],
        {"artifact.cuda_requested_but_not_used": outputs.get("cuda_requested_but_not_used", "")},
    )


def test_the_workflow_still_declares_the_shell_this_harness_runs() -> None:
    assert declares_bash_default(WORKFLOW)


def test_a_silent_cpu_fallback_is_reported(tmp_path: Path) -> None:
    result = _summarise(tmp_path, {"requested_device": "cuda", "resolved_device": "cpu"})
    assert result.outputs["cuda_requested_but_not_used"] == "true", result.outputs
    assert result.outputs["resolved_device"] == "cpu"
    assert _warns(result.outputs)


def test_a_run_that_actually_used_cuda_does_not_warn(tmp_path: Path) -> None:
    result = _summarise(tmp_path, {"requested_device": "cuda", "resolved_device": "cuda"})
    assert result.outputs["cuda_requested_but_not_used"] == "false", result.outputs
    assert not _warns(result.outputs)


def test_a_cpu_run_that_asked_for_cpu_is_not_a_fallback(tmp_path: Path) -> None:
    """Otherwise every CPU run would warn and the signal would be worthless."""
    result = _summarise(tmp_path, {"requested_device": "cpu", "resolved_device": "cpu"},
                        requested="cpu")
    assert result.outputs["cuda_requested_but_not_used"] == "false"
    assert not _warns(result.outputs)


def test_the_env_supplies_the_request_when_the_artifact_omits_it(tmp_path: Path) -> None:
    """The artifact is written by the run; the env is what the operator asked for.

    With the field missing, falling back to anything other than the env would
    silently absolve a run of a fallback it did perform.
    """
    result = _summarise(tmp_path, {"resolved_device": "cpu"})
    assert result.outputs["requested_device"] == "cuda"
    assert result.outputs["cuda_requested_but_not_used"] == "true"


def test_a_missing_artifact_reports_unknown_and_does_not_warn(tmp_path: Path) -> None:
    result = _summarise(tmp_path, None)
    assert result.returncode == 0, result.stderr
    assert result.outputs["resolved_device"] == "unknown"
    assert result.outputs["cuda_requested_but_not_used"] == "false"
    assert not _warns(result.outputs)
