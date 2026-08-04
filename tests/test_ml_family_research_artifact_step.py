"""What ``ml-family-research.yml``'s artifact step decides, executed.

The step summarises a finished ML run and publishes two things a warning is
gated on: ``gpu_requested_but_not_used`` and ``fallback_reasons``. The point is
to notice that a run which asked for a GPU quietly trained on CPU -- otherwise
the run looks identical to a healthy one and the bill does not.

Measured 2026-08-04 against a green unmutated baseline of the full suite:
inverting ``requested == "cuda" and "cuda" not in resolved`` to ``… "cuda" in
resolved`` left all **24708 tests green**. The warning would then fire exactly
when the GPU *was* used and stay silent when it was not -- the opposite of the
step, one token apart in the source.

Not a value-preserving mutation, so a whole-line source pin would also have
caught it. None existed.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from tests._fast_gates_gate import evaluate_condition, step_conditions
from tests._workflow_step_shell import declares_bash_default, run_step

WORKFLOW = "ml-family-research.yml"
STEP = "Summarise ML artifact"
WARN = "Warn on ML fallback"

_CONDITIONS = step_conditions(
    Path(__file__).resolve().parents[1] / ".github" / "workflows" / WORKFLOW,
    job="research",
)


def _summarise(tmp_path: Path, payload: dict | None, *, requested: str = "cuda"):
    """``payload=None`` means the run produced no artifact at all."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    artifact = tmp_path / "latest.json"
    if payload is not None:
        artifact.write_text(json.dumps(payload), encoding="utf-8")
    # No stub: the heredoc IS the decision, so it runs on the real interpreter.
    return run_step(
        WORKFLOW, STEP, tmp_path,
        env={"ML_ARTIFACT_PATH": str(artifact), "SMC_PYTHON_BIN": sys.executable,
             "SKIPP_ML_DEVICE": requested},
        expressions={"steps.params.outputs.artifact_dir": str(tmp_path)},
    )


def _warns(outputs: dict[str, str]) -> bool:
    return evaluate_condition(_CONDITIONS[WARN], {
        "artifact.gpu_requested_but_not_used": outputs.get("gpu_requested_but_not_used", ""),
        "artifact.fallback_reasons": outputs.get("fallback_reasons", ""),
    })


def _train(rows: list[dict], requested: str = "cuda") -> dict:
    return {"mode": "train", "requested_device": requested, "family_reports": rows}


def test_the_workflow_still_declares_the_shell_this_harness_runs() -> None:
    assert declares_bash_default(WORKFLOW)


def test_a_silent_cpu_fallback_is_reported(tmp_path: Path) -> None:
    """The assertion the step exists for: paid for a GPU, trained on a CPU."""
    result = _summarise(tmp_path, _train([
        {"family": "fvg", "resolved_device": "cpu", "device_fallback_reason": "no cuda device"},
    ]))
    assert result.outputs["gpu_requested_but_not_used"] == "true", result.outputs
    assert result.outputs["resolved_devices"] == "cpu"
    assert _warns(result.outputs)


def test_a_run_that_actually_used_the_gpu_does_not_warn(tmp_path: Path) -> None:
    """The control direction: without it, `true` could be a constant."""
    result = _summarise(tmp_path, _train([
        {"family": "fvg", "resolved_device": "cuda"},
        {"family": "bos", "resolved_device": "cuda"},
    ]))
    assert result.outputs["gpu_requested_but_not_used"] == "false", result.outputs
    assert result.outputs["fallback_reasons"] == "none"
    assert not _warns(result.outputs)


def test_a_fallback_reason_warns_even_when_the_gpu_was_used(tmp_path: Path) -> None:
    """The condition's second arm, which the flag alone would never reach.

    A mixed run -- one family on cuda, another degraded for its own reason --
    has `gpu_requested_but_not_used=false` and still needs the warning.
    """
    result = _summarise(tmp_path, _train([
        {"family": "fvg", "resolved_device": "cuda"},
        {"family": "bos", "resolved_device": "cuda", "device_fallback_reason": "oom, retried"},
    ]))
    assert result.outputs["gpu_requested_but_not_used"] == "false"
    assert result.outputs["fallback_reasons"] == "bos:oom, retried"
    assert _warns(result.outputs), "a fallback reason must warn on its own"


def test_fallback_reasons_are_deduplicated_and_ordered(tmp_path: Path) -> None:
    """Published through GitHub's multiline `name<<EOF` form, not `name=value`."""
    result = _summarise(tmp_path, _train([
        {"family": "b", "resolved_device": "cpu", "device_fallback_reason": "x"},
        {"family": "a", "resolved_device": "cpu", "device_fallback_reason": "x"},
        {"family": "a", "resolved_device": "cpu", "device_fallback_reason": "x"},
    ]))
    assert result.outputs["fallback_reasons"] == "a:x; b:x", result.outputs


def test_a_cpu_run_that_asked_for_cpu_is_not_a_fallback(tmp_path: Path) -> None:
    result = _summarise(tmp_path, _train([
        {"family": "fvg", "resolved_device": "cpu"}], requested="cpu"), requested="cpu")
    assert result.outputs["requested_device"] == "cpu"
    assert result.outputs["gpu_requested_but_not_used"] == "false"
    assert not _warns(result.outputs)


def test_tune_mode_reads_the_best_trial_not_every_trial(tmp_path: Path) -> None:
    """`tune` has its own extraction path; sharing the assertions would hide it."""
    result = _summarise(tmp_path, {
        "mode": "tune", "requested_device": "cuda", "best_trial_number": 2,
        "best_resolved_devices": ["cpu"],
        "trial_summaries": [
            {"number": 1, "family_metrics": {"fvg": {"device_fallback_reason": "ignored"}}},
            {"number": 2, "family_metrics": {"bos": {"device_fallback_reason": "counted"}}},
        ],
    })
    assert result.outputs["gpu_requested_but_not_used"] == "true"
    assert result.outputs["fallback_reasons"] == "bos:counted", result.outputs


def test_a_missing_artifact_reports_unknown_and_does_not_warn(tmp_path: Path) -> None:
    """A crashed run has nothing to say about devices; it must not invent a warning."""
    result = _summarise(tmp_path, None)
    assert result.returncode == 0, result.stderr
    assert result.outputs["resolved_devices"] == "unknown"
    assert result.outputs["gpu_requested_but_not_used"] == "false"
    assert result.outputs["fallback_reasons"] == "none", result.outputs
    assert not _warns(result.outputs)
