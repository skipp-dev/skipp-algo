from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "bootstrap_node_worktree.sh"


def test_package_json_exposes_node_worktree_bootstrap_shortcut() -> None:
    package_json = json.loads((REPO_ROOT / "package.json").read_text(encoding="utf-8"))
    assert package_json["scripts"]["node:bootstrap-worktree"] == (
        "bash scripts/bootstrap_node_worktree.sh"
    )


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash is required for repo shell helpers")
def test_bootstrap_node_worktree_help_contains_only_comment_preamble() -> None:
    result = subprocess.run(
        ["bash", str(SCRIPT), "--help"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert "Usage:" in result.stdout
    assert "set -euo pipefail" not in result.stdout


def _write_node_checkout(root: Path, lock_text: str) -> None:
    root.mkdir(parents=True)
    (root / "package.json").write_text('{"private":true}\n', encoding="utf-8")
    (root / "package-lock.json").write_text(lock_text, encoding="utf-8")


def _write_fake_node_modules(root: Path) -> None:
    bin_dir = root / "node_modules" / ".bin"
    playwright_dir = root / "node_modules" / "playwright"
    bin_dir.mkdir(parents=True)
    playwright_dir.mkdir(parents=True)
    (playwright_dir / "package.json").write_text('{"name":"playwright"}\n', encoding="utf-8")
    for binary in ("tsx", "tsc", "playwright"):
        path = bin_dir / binary
        path.write_text("#!/usr/bin/env sh\nexit 0\n", encoding="utf-8")
        path.chmod(0o755)


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash is required for repo shell helpers")
def test_bootstrap_node_worktree_links_compatible_source_node_modules(tmp_path: Path) -> None:
    source = tmp_path / "main"
    target = tmp_path / "worktree"
    _write_node_checkout(source, '{"lockfileVersion":3}\n')
    _write_node_checkout(target, '{"lockfileVersion":3}\n')
    _write_fake_node_modules(source)

    result = subprocess.run(
        ["bash", str(SCRIPT), str(target)],
        env={**os.environ, "SKIPP_NODE_MODULES_SOURCE": str(source)},
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr + result.stdout
    assert (target / "node_modules").is_symlink()
    assert (target / "node_modules").resolve() == (source / "node_modules").resolve()
    assert "Linked node_modules" in result.stdout


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash is required for repo shell helpers")
def test_bootstrap_node_worktree_refuses_mismatched_lock_without_install(tmp_path: Path) -> None:
    source = tmp_path / "main"
    target = tmp_path / "worktree"
    _write_node_checkout(source, '{"lockfileVersion":3,"packages":{"a":{}}}\n')
    _write_node_checkout(target, '{"lockfileVersion":3,"packages":{"b":{}}}\n')
    _write_fake_node_modules(source)

    result = subprocess.run(
        ["bash", str(SCRIPT), str(target)],
        env={
            **os.environ,
            "SKIPP_NODE_MODULES_SOURCE": str(source),
            "SKIPP_NODE_BOOTSTRAP_NO_INSTALL": "1",
        },
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert not (target / "node_modules").exists()
    assert "no compatible source node_modules found" in result.stderr
