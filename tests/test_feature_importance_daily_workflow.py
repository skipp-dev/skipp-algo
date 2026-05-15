"""Pin-test for the feature-importance-daily workflow.

E4-3 (Q3): the workflow must surface ranking-drift signals as a workflow
warning (analog to weight-drift-gate). This locks the parsing tokens
emitted by ``open_prep.feature_importance_report`` and the GitHub
Actions output names so a refactor on either side breaks loudly.
"""
from __future__ import annotations

from pathlib import Path

WF = Path(".github/workflows/feature-importance-daily.yml")


def test_workflow_parses_drift_status_token() -> None:
    text = WF.read_text(encoding="utf-8")
    # The script writes "drift_status=…" — the workflow must parse it.
    assert "drift_status=" in text
    assert "drift_max_delta=" in text


def test_workflow_emits_warning_on_drift() -> None:
    text = WF.read_text(encoding="utf-8")
    assert "Alert on ranking drift" in text
    assert "steps.fi.outputs.drift_status == 'warn'" in text
    assert "::warning" in text


def test_workflow_writes_step_summary() -> None:
    text = WF.read_text(encoding="utf-8")
    assert "GITHUB_STEP_SUMMARY" in text
    assert "ranking_drift" in text


def test_workflow_prefers_gpu_labeled_runner() -> None:
    text = WF.read_text(encoding="utf-8")
    assert "SMC_PRIORITY_CRON_GPU_SELF_HOSTED_LABEL" in text
    assert "priority-gpu" not in text  # variable-driven, not hard-coded


def test_workflow_forces_gpu_backend_on_self_hosted() -> None:
    text = WF.read_text(encoding="utf-8")
    assert "requirements-gpu.txt" in text
    assert "OPEN_PREP_FI_BACKEND=gpu" in text
    assert "OPEN_PREP_FI_BACKEND=cpu" in text
