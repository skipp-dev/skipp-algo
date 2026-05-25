"""Structural pin-test for the F2 frozen-artifact bootstrap workflow.

Guards the invariants that matter for #43:
  * live-window marker on line 1 (orphan inventory + posture tests).
  * Only ``workflow_dispatch`` triggers (no schedule, push, pull_request).
  * The four required inputs are present with the right types.
  * Permissions: ``contents: write`` + ``pull-requests: write`` exactly.
  * The job invokes both the measurement benchmark and the frozen
    calibration CLI (``--frozen``).
  * The PR-creation step uses the canonical GH_PAT fallback, labels
    the PR ``f2-recalibration``, and uses the documented title format.
  * ``DATABENTO_API_KEY`` is read from secrets for the benchmark step.

We parse the YAML and inspect the raw text; we never execute the
workflow.
"""

from __future__ import annotations

from pathlib import Path

import yaml

WORKFLOW = (
    Path(__file__).resolve().parents[1]
    / ".github"
    / "workflows"
    / "f2-frozen-artifact-bootstrap.yml"
)


def _text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def _load() -> dict:
    return yaml.safe_load(_text())


def _on(wf: dict) -> dict:
    # PyYAML parses bare 'on:' as the boolean True under YAML 1.1.
    return wf.get("on", wf.get(True))


def _steps() -> list[dict]:
    return _load()["jobs"]["bootstrap"]["steps"]


def test_live_window_marker_on_first_line() -> None:
    first = _text().splitlines()[0]
    assert first.startswith("# live-window: manual-only"), first


def test_only_workflow_dispatch_trigger() -> None:
    wf = _load()
    on = _on(wf)
    assert isinstance(on, dict)
    assert "workflow_dispatch" in on
    for forbidden in ("schedule", "push", "pull_request"):
        assert forbidden not in on, f"{forbidden} trigger not allowed for governed bootstrap"


def test_required_inputs_present_with_expected_types() -> None:
    on = _on(_load())
    inputs = on["workflow_dispatch"]["inputs"]
    # corpus_start_date: required string
    assert inputs["corpus_start_date"]["required"] is True
    assert inputs["corpus_start_date"]["type"] == "string"
    # corpus_window_days: string, default "90"
    assert inputs["corpus_window_days"]["type"] == "string"
    assert str(inputs["corpus_window_days"]["default"]) == "90"
    # status: choice with shadow|live, default shadow
    assert inputs["status"]["type"] == "choice"
    assert inputs["status"]["default"] == "shadow"
    assert set(inputs["status"]["options"]) == {"shadow", "live"}
    # frozen_at: string, default empty
    assert inputs["frozen_at"]["type"] == "string"
    assert inputs["frozen_at"]["default"] == ""


def test_permissions_block_is_exact() -> None:
    perms = _load()["permissions"]
    assert perms == {"contents": "write", "pull-requests": "write"}, perms


def test_job_invokes_benchmark_and_frozen_calibration() -> None:
    runs = "\n".join(s.get("run", "") for s in _steps() if isinstance(s.get("run"), str))
    assert "scripts/run_smc_measurement_benchmark.py" in runs
    assert "scripts/smc_zone_priority_calibration.py" in runs
    assert "--frozen" in runs
    assert "--frozen-at" in runs
    assert "--corpus-manifest-hash" in runs


def test_pr_creation_uses_canonical_gh_pat_pattern_and_label() -> None:
    text = _text()
    # GH_PAT fallback pattern shared with smc-library-refresh.yml
    assert "secrets.GH_PAT != '' && secrets.GH_PAT || github.token" in text
    # PR is labeled and titled per the issue spec
    assert "--label f2-recalibration" in text
    assert (
        'data(f2): regenerate frozen contextual calibration artifact (corpus ${START}--${END})'
        in text
    )
    # PR is opened via gh pr create with --body-file (diff summary)
    assert "gh pr create" in text
    assert "--body-file" in text


def test_databento_api_key_wired_to_benchmark_step() -> None:
    for step in _steps():
        if "run_smc_measurement_benchmark.py" in step.get("run", ""):
            env = step.get("env") or {}
            assert "DATABENTO_API_KEY" in env
            assert "secrets.DATABENTO_API_KEY" in env["DATABENTO_API_KEY"]
            return
    raise AssertionError("benchmark step not found")
