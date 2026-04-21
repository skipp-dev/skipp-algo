"""Pin-tests for the plan-2.8 q4-gate dryrun workflow.

Guards the manual W13 operator surface: workflow_dispatch inputs,
evaluator invocation with all four threshold knobs wired through,
artifact upload of the verdict JSON, and markdown streamed into the
GitHub step summary.
"""

from __future__ import annotations

from pathlib import Path

import yaml

WORKFLOW = (
    Path(__file__).resolve().parents[1]
    / ".github" / "workflows" / "plan-2-8-q4-gate-dryrun.yml"
)


def _wf() -> dict:
    data = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    # YAML 1.1 quirk: bare `on:` becomes True.
    return {"on": data.get("on", data.get(True)), **{
        k: v for k, v in data.items() if k not in ("on", True)
    }}


def test_workflow_file_exists() -> None:
    assert WORKFLOW.exists()


def test_trigger_is_workflow_dispatch_only() -> None:
    wf = _wf()
    on = wf["on"]
    assert isinstance(on, dict), f"trigger must be a mapping, got {on!r}"
    assert set(on.keys()) == {"workflow_dispatch"}


def test_all_threshold_inputs_present() -> None:
    inputs = _wf()["on"]["workflow_dispatch"]["inputs"]
    for name in (
        "bundle_path", "uplift_min_pp", "uplift_min_buckets",
        "brier_max_regression", "min_events_per_bucket",
    ):
        assert name in inputs, f"missing workflow input: {name}"


def test_default_thresholds_match_addendum() -> None:
    inputs = _wf()["on"]["workflow_dispatch"]["inputs"]
    assert inputs["uplift_min_pp"]["default"] == "0.03"
    assert inputs["uplift_min_buckets"]["default"] == "2"
    assert inputs["brier_max_regression"]["default"] == "0.02"
    assert inputs["min_events_per_bucket"]["default"] == "30"


def test_evaluator_step_wires_all_knobs_and_streams_summary() -> None:
    steps = _wf()["jobs"]["q4-gate-dryrun"]["steps"]
    gate = next(s for s in steps if s.get("id") == "gate")
    run = gate["run"]
    for flag in (
        "--bundle", "--uplift-min-pp", "--uplift-min-buckets",
        "--brier-max-regression", "--min-events-per-bucket",
        "--output", "--format md",
    ):
        assert flag in run, f"evaluator missing flag: {flag}"
    assert "scripts/plan_2_8_q4_gate_evaluator.py" in run
    assert "$GITHUB_STEP_SUMMARY" in run


def test_verdict_artifact_uploaded_always() -> None:
    steps = _wf()["jobs"]["q4-gate-dryrun"]["steps"]
    upload = next(
        s for s in steps
        if str(s.get("uses", "")).startswith("actions/upload-artifact@")
    )
    assert upload.get("if") == "always()"
    path = upload["with"]["path"]
    assert "plan_2_8_q4_gate_verdict.json" in path
    assert upload["with"]["name"] == "plan-2-8-q4-gate-verdict"
