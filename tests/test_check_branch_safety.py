"""Tests for scripts/check_branch_safety.py."""

from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "check_branch_safety.py"


@pytest.fixture(scope="module")
def branch_safety_module():
    spec = importlib.util.spec_from_file_location("check_branch_safety", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _completed(stdout: str) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=["git"], returncode=0, stdout=stdout, stderr="")


def test_main_branch_is_blocked(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], branch_safety_module) -> None:
    monkeypatch.setattr(
        branch_safety_module.subprocess,
        "run",
        lambda *args, **kwargs: _completed("# branch.head main\n"),
    )

    rc = branch_safety_module.main()
    out = capsys.readouterr().out

    assert rc == 1
    assert "direct commit to 'main' is blocked" in out


def test_feature_branch_passes(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], branch_safety_module) -> None:
    monkeypatch.setattr(
        branch_safety_module.subprocess,
        "run",
        lambda *args, **kwargs: _completed("# branch.head feat/demo\n"),
    )

    rc = branch_safety_module.main()
    out = capsys.readouterr().out

    assert rc == 0
    assert "BRANCH CHECK: currently on -> feat/demo" in out
    assert "Branch lifecycle observation" not in out


def test_divergence_observation_is_printed(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    branch_safety_module,
) -> None:
    status = "\n".join(
        [
            "# branch.head fix/live-overlay-audit-followup-f1-f4",
            "# branch.upstream origin/fix/live-overlay-audit-followup-f1-f4",
            "# branch.ab +4 -2",
        ]
    )
    monkeypatch.setattr(
        branch_safety_module.subprocess,
        "run",
        lambda *args, **kwargs: _completed(status),
    )

    rc = branch_safety_module.main()
    out = capsys.readouterr().out

    assert rc == 0
    assert "Branch lifecycle observation: DIVERGED" in out
    assert "ahead=4, behind=2" in out


def test_subprocess_failure_falls_back_to_detached(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    branch_safety_module,
) -> None:
    def _raise(*args, **kwargs):
        raise subprocess.CalledProcessError(returncode=1, cmd=["git"])

    monkeypatch.setattr(branch_safety_module.subprocess, "run", _raise)

    rc = branch_safety_module.main()
    out = capsys.readouterr().out

    assert rc == 0
    assert "(detached HEAD)" in out


def test_detached_marker_is_normalized(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    branch_safety_module,
) -> None:
    monkeypatch.setattr(
        branch_safety_module.subprocess,
        "run",
        lambda *args, **kwargs: _completed("# branch.head (detached)\n"),
    )

    rc = branch_safety_module.main()
    out = capsys.readouterr().out

    assert rc == 0
    assert "(detached HEAD)" in out


def test_timeout_falls_back_to_detached(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    branch_safety_module,
) -> None:
    def _raise(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=["git"], timeout=2)

    monkeypatch.setattr(branch_safety_module.subprocess, "run", _raise)

    rc = branch_safety_module.main()
    out = capsys.readouterr().out

    assert rc == 0
    assert "(detached HEAD)" in out
