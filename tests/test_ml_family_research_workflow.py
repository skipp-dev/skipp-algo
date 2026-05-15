from __future__ import annotations

from pathlib import Path

WF = Path(".github/workflows/ml-family-research.yml")


def test_workflow_exposes_research_modes() -> None:
    text = WF.read_text(encoding="utf-8")
    assert "mode:" in text
    assert "explainability" in text
    assert "train" in text
    assert "tune" in text


def test_workflow_prefers_gpu_label_via_repo_variable() -> None:
    text = WF.read_text(encoding="utf-8")
    assert "SMC_PRIORITY_CRON_GPU_SELF_HOSTED_LABEL" in text
    assert "priority-gpu" not in text


def test_workflow_installs_ml_stack_and_runs_scripts() -> None:
    text = WF.read_text(encoding="utf-8")
    assert "requirements-ml.txt" in text
    assert "run_ml_family_training.py" in text
    assert "run_ml_explainability_report.py" in text
    assert "run_ml_optuna_tuning.py" in text


def test_workflow_probes_ml_backend_before_requesting_gpu() -> None:
    text = WF.read_text(encoding="utf-8")
    assert "Probe ML runtime" in text
    assert "cuda_ready" in text
    assert "probe_reason" in text


def test_workflow_surfaces_resolved_devices_and_fallbacks() -> None:
    text = WF.read_text(encoding="utf-8")
    assert "resolved devices" in text
    assert "fallback reasons" in text
    assert "Warn on ML fallback" in text


def test_workflow_uploads_research_artifacts() -> None:
    text = WF.read_text(encoding="utf-8")
    assert "actions/upload-artifact" in text
    assert "artifacts/ml/research" in text
    assert "schedule:" in text