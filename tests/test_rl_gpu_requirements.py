from __future__ import annotations

from pathlib import Path


def test_rl_gpu_requirements_pin_cuda_torch_wheel() -> None:
    text = Path("requirements-rl-gpu.txt").read_text(encoding="utf-8")
    assert "download.pytorch.org/whl/cu129" in text
    assert "torch==2.12.1+cu129" in text
