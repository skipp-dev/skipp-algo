"""Pin-test for the feature-importance-daily workflow.

E4-3 (Q3): the workflow must surface ranking-drift signals as a workflow
warning (analog to weight-drift-gate). This locks the parsing tokens
emitted by ``open_prep.feature_importance_report`` and the GitHub
Actions output names so a refactor on either side breaks loudly.
"""
from __future__ import annotations

from pathlib import Path

import open_prep.feature_importance_report as fr

WF = Path(".github/workflows/feature-importance-daily.yml")


def _workflow_text() -> str:
    return WF.read_text(encoding="utf-8")


def test_workflow_parses_drift_status_token() -> None:
    text = _workflow_text()
    # The script writes "drift_status=…" — the workflow must parse it.
    assert "drift_status=" in text
    assert "drift_max_delta=" in text


def test_workflow_emits_warning_on_drift() -> None:
    text = _workflow_text()
    assert "Alert on ranking drift" in text
    assert "steps.fi.outputs.drift_status == 'warn'" in text
    assert "::warning" in text


def test_workflow_writes_step_summary() -> None:
    text = _workflow_text()
    assert "GITHUB_STEP_SUMMARY" in text
    assert "ranking_drift" in text


def test_workflow_prefers_gpu_labeled_runner() -> None:
    text = _workflow_text()
    assert "SMC_PRIORITY_CRON_GPU_SELF_HOSTED_LABEL" in text
    assert "priority-gpu" not in text  # variable-driven, not hard-coded


def test_workflow_forces_gpu_backend_on_self_hosted() -> None:
    text = _workflow_text()
    assert "requirements-gpu.txt" in text
    assert "OPEN_PREP_FI_BACKEND=gpu" in text
    assert "OPEN_PREP_FI_BACKEND=cpu" in text


def test_workflow_uploads_generated_report_artifact() -> None:
    text = WF.read_text(encoding="utf-8").replace("\\", "/")
    assert f"{fr.FI_REPORT_DIR.as_posix()}/latest.json" in text
    assert "artifacts/open_prep/outcomes/feature_importance/latest.json" not in text
