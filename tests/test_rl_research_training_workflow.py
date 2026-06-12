from __future__ import annotations

from pathlib import Path

WF = Path(".github/workflows/rl-research-training.yml")


def test_workflow_prefers_gpu_label_via_repo_variable() -> None:
    text = WF.read_text(encoding="utf-8")
    assert "SMC_PRIORITY_CRON_GPU_SELF_HOSTED_LABEL" in text
    assert "priority-gpu" not in text


def test_workflow_installs_rl_stack_and_runs_training_script() -> None:
    text = WF.read_text(encoding="utf-8")
    assert "requirements-rl.txt" in text
    assert "requirements-rl-gpu.txt" in text
    assert "-m scripts.run_rl_research_training" in text
    assert "workflow_dispatch" in text


def test_workflow_probes_torch_cuda_before_requesting_gpu() -> None:
    text = WF.read_text(encoding="utf-8")
    assert "torch.cuda.is_available()" in text
    assert "requested_device=cuda" in text
    assert "torch CUDA is unavailable" in text
    assert "CPU fallback honestly" in text


def test_workflow_step_summary_surfaces_torch_runtime() -> None:
    text = WF.read_text(encoding="utf-8")
    assert "resolved device" in text
    assert "torch cuda available" in text
    assert "torch cuda version" in text


def test_workflow_surfaces_resolved_device_from_artifact() -> None:
    text = WF.read_text(encoding="utf-8")
    assert "Summarise RL artifact" in text
    assert "resolved_device" in text
    assert "Warn on RL fallback" in text


def test_workflow_preserves_requested_device_intent() -> None:
    text = WF.read_text(encoding="utf-8")
    assert 'echo "requested_device=$REQUESTED_DEVICE" >> "$GITHUB_OUTPUT"' in text
    assert 'payload.get("requested_device")' in text
    assert "keeps requested_device=cuda" in text


def test_workflow_exposes_agent_choices() -> None:
    text = WF.read_text(encoding="utf-8")
    assert "agent:" in text
    assert "ppo" in text
    assert "sac" in text


def test_workflow_uploads_rl_artifacts() -> None:
    text = WF.read_text(encoding="utf-8")
    assert "actions/upload-artifact" in text
    assert "artifacts/rl/research" in text
