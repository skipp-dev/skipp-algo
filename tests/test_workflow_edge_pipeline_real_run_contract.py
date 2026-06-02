"""Structural pin-test for the EV-20 first-real-run edge pipeline workflow.

Guards the invariants that make ``edge-pipeline-real-run.yml`` a *governed*
first-real-evidence run rather than an ad-hoc credential-burning script:

  * live-window marker ``manual-only`` on line 1 (orphan inventory + posture).
  * Only ``workflow_dispatch`` triggers (no schedule / push / pull_request).
  * The operator inputs that pin the run window are present.
  * Permissions: ``contents: write`` + ``pull-requests: write`` exactly.
  * The job invokes BOTH the Databento pull (EV-13) and the edge pipeline
    (EV-10), archiving into ``governance/promotion_decisions``.
  * ``DATABENTO_API_KEY`` is read from secrets on the run step.
  * The decision PR uses the canonical GH_PAT fallback + ``gh pr create
    --body-file`` and is NOT auto-merged (no ``gh pr merge``).
  * Reports are uploaded with the frozen ``upload-artifact`` v7 pin.

We parse the YAML and inspect the raw text; we never execute the workflow.
"""

from __future__ import annotations

from pathlib import Path

import yaml

WORKFLOW = (
    Path(__file__).resolve().parents[1]
    / ".github"
    / "workflows"
    / "edge-pipeline-real-run.yml"
)


def _text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def _load() -> dict:
    return yaml.safe_load(_text())


def _on(wf: dict) -> dict:
    # PyYAML parses bare 'on:' as the boolean True under YAML 1.1.
    return wf.get("on", wf.get(True))


def _steps() -> list[dict]:
    return _load()["jobs"]["edge-run"]["steps"]


def test_live_window_marker_manual_only_on_first_line() -> None:
    first = _text().splitlines()[0]
    assert first.startswith("# live-window: manual-only"), first


def test_only_workflow_dispatch_trigger() -> None:
    on = _on(_load())
    assert isinstance(on, dict)
    assert "workflow_dispatch" in on
    for forbidden in ("schedule", "push", "pull_request"):
        assert forbidden not in on, f"{forbidden} trigger not allowed for a governed manual run"


def test_required_window_inputs_present() -> None:
    inputs = _on(_load())["workflow_dispatch"]["inputs"]
    for key in ("symbols", "dataset", "schema", "timeframe", "start", "end", "as_of"):
        assert key in inputs, f"missing input: {key}"
    assert inputs["start"]["required"] is True
    assert inputs["end"]["required"] is True
    assert inputs["schema"]["type"] == "choice"


def test_permissions_block_is_exact() -> None:
    perms = _load()["permissions"]
    assert perms == {"contents": "write", "pull-requests": "write"}, perms


def test_job_invokes_pull_and_pipeline_with_archive_dir() -> None:
    runs = "\n".join(s.get("run", "") for s in _steps() if isinstance(s.get("run"), str))
    assert "scripts.pull_databento_edge_input" in runs
    assert "scripts.run_edge_pipeline" in runs
    assert "--archive-dir governance/promotion_decisions" in runs


def test_databento_api_key_wired_to_run_step() -> None:
    for step in _steps():
        if "scripts.run_edge_pipeline" in step.get("run", ""):
            env = step.get("env") or {}
            assert "DATABENTO_API_KEY" in env
            assert "secrets.DATABENTO_API_KEY" in env["DATABENTO_API_KEY"]
            return
    raise AssertionError("edge pipeline run step not found")


def test_decision_pr_is_governed_not_auto_merged() -> None:
    text = _text()
    # Canonical GH_PAT fallback shared with f2-frozen-artifact-bootstrap.yml.
    assert "secrets.GH_PAT != '' && secrets.GH_PAT || github.token" in text
    assert "gh pr create" in text
    assert "--body-file" in text
    # A re-calibration / first-evidence event is human-reviewed: never auto-merge.
    assert "gh pr merge" not in text


def test_upload_artifact_pinned_to_frozen_v7() -> None:
    text = _text()
    assert (
        "actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a # v7" in text
    )
