from __future__ import annotations

import subprocess
from pathlib import Path

from tests._guard_corpus import iter_tracked_files, repo_root


def _git_tracked_py_files(root: Path) -> set[Path]:
    proc = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-z", "--", "*.py"],
        check=True,
        capture_output=True,
        text=False,
    )
    rels = [item for item in proc.stdout.decode("utf-8").split("\x00") if item]
    return {root / rel for rel in rels}


def test_iter_tracked_files_matches_git_ls_files_inventory() -> None:
    root = repo_root()
    exclude_dirs = frozenset(
        {
            ".git",
            ".github",
            ".mypy_cache",
            ".pytest_cache",
            ".ruff_cache",
            ".venv",
            "venv",
            "node_modules",
            "artifacts",
            "docs",
            "scripts",
            "tests",
            "SMC++",
        }
    )

    observed = set(iter_tracked_files("*.py", exclude_dirs, root=root))
    expected = {
        p
        for p in _git_tracked_py_files(root)
        if not any(part in exclude_dirs for part in p.relative_to(root).parts)
    }

    assert observed == expected


def test_iter_tracked_files_excludes_untracked_root_scratch_file() -> None:
    root = repo_root()
    scratch = root / "__scratch_guard_scan_regression__.py"
    scratch.write_text(
        "import subprocess\nsubprocess.run('echo hi', shell=True)\nprint('hi')\n",
        encoding="utf-8",
    )
    try:
        observed = set(iter_tracked_files("*.py", frozenset(), root=root))
        assert scratch not in observed, (
            "iter_tracked_files must not include untracked root scratch files; "
            "otherwise hygiene ledgers can false-fail."
        )
    finally:
        scratch.unlink(missing_ok=True)
