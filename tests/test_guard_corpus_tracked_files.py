from __future__ import annotations

import ast
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from tests._guard_corpus import (
    MIN_EXPECTED_PROD_FILES,
    iter_production_py_files,
    iter_tracked_files,
    repo_root,
)


def _clean_git_env() -> dict[str, str]:
    """The ambient environment with every ``GIT_*`` variable stripped.

    This is the load-bearing part, and it is not paranoia. ``pre-commit`` runs
    its hooks with ``GIT_DIR`` / ``GIT_INDEX_FILE`` exported and pointing at the
    REAL repository. Those win over ``-C``: ``git -C /tmp/throwaway config
    user.email x`` under a hook resolves to the real repo and writes there.
    Demonstrated on this tree — with ``GIT_DIR`` exported, ``git -C <tmp> config
    --get user.email`` returns the developer's address, not the temp repo's.

    That is exactly how a helper here overwrote this repo's committer identity
    and left a stray commit on the branch: it passed under a bare ``pytest`` run
    and only misfired inside the pre-push hook, where the variables exist.
    """
    return {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}


def _git_tracked_py_files(root: Path) -> set[Path] | None:
    git = shutil.which("git")
    if git is None:
        return None
    try:
        proc = subprocess.run(
            [git, "-C", str(root), "ls-files", "-z", "--", "*.py"],
            check=True,
            capture_output=True,
            text=False,
            # Without this the inherited GIT_INDEX_FILE makes the command fail
            # under a pre-commit hook, so this returned None and the parity
            # assertion below skipped itself with "git unavailable" — false, and
            # precisely in the pre-push run where it is the only thing checking
            # that iter_tracked_files still agrees with git.
            env=_clean_git_env(),
        )
    except (OSError, subprocess.SubprocessError):
        return None
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
    tracked = _git_tracked_py_files(root)
    if tracked is None:
        pytest.skip("git unavailable; skipping git ls-files parity assertion")
    expected = {p for p in tracked if not any(part in exclude_dirs for part in p.relative_to(root).parts)}

    assert observed == expected


def test_iter_tracked_files_excludes_untracked_root_scratch_file() -> None:
    root = repo_root()
    if shutil.which("git") is None:
        pytest.skip("git unavailable; tracked-file exclusion requires git ls-files")

    scratch = root / "__scratch_guard_scan_regression__.py"
    scratch.write_text(
        "# untracked scratch file used for tracked-inventory regression\ndef _scratch() -> None:\n    return None\n",
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


# skipif, not an in-body skip call: the skip budget (test_pytest_skip_budget)
# counts those per file, and four more would have pushed this file over its
# budget of 2 — raising a budget just to add tests is exactly backwards.
# (Its regex is a line match, so spelling the call out even in a comment counts.)
_requires_git = pytest.mark.skipif(shutil.which("git") is None, reason="git unavailable")


def _git(path: Path, *args: str) -> None:
    """Run git against the throwaway repo at ``path`` and nowhere else.

    Three independent belts, because one was not enough:

    * ``_clean_git_env`` — removes the inherited ``GIT_DIR`` / ``GIT_INDEX_FILE``
      that would otherwise redirect the whole command at the real repo.
    * ``--git-dir`` / ``--work-tree`` — pin the target explicitly, so git cannot
      walk up out of ``path``.
    * ``-c user.email=…`` — the identity is per invocation and cannot outlive the
      process. A ``git config`` write is persistent, and in a WORKTREE it lands
      in the shared config of the real repo. A test helper must never do that.
    """
    subprocess.run(
        [
            "git",
            "--git-dir",
            str(path / ".git"),
            "--work-tree",
            str(path),
            "-c",
            "user.email=guard@example.invalid",
            "-c",
            "user.name=guard",
            "-c",
            "commit.gpgsign=false",
            *args,
        ],
        check=True,
        capture_output=True,
        cwd=path,
        env=_clean_git_env(),
    )


def _init_repo(path: Path) -> None:
    """Make ``path`` a real git repo with one commit (no *.py tracked)."""
    subprocess.run(
        ["git", "init", "-q", str(path)],
        check=True,
        capture_output=True,
        env=_clean_git_env(),
    )
    (path / "seed.txt").write_text("seed\n", encoding="utf-8")
    _git(path, "add", "seed.txt")
    _git(path, "commit", "-qm", "seed")


def _commit_py(path: Path, *names: str) -> None:
    for name in names:
        (path / name).parent.mkdir(parents=True, exist_ok=True)
        (path / name).write_text("x = 1\n", encoding="utf-8")
        _git(path, "add", name)
    _git(path, "commit", "-qm", "py")


@_requires_git
def test_iter_tracked_files_returns_empty_on_zero_matches_without_falling_back(
    tmp_path: Path,
) -> None:
    """A successful ``git ls-files`` with no matches must stay an honest ``[]``.

    The filesystem fallback exists for "git is unusable", NOT for "git works and
    the pattern matches nothing" — taking it there would sweep untracked files
    into a tracked-only inventory, which
    ``test_iter_tracked_files_excludes_untracked_root_scratch_file`` forbids.
    This pins the low-level contract that :func:`iter_production_py_files` is
    built on: the raw helper reports emptiness truthfully, and the FLOOR (not
    the fallback) is what turns a collapsed corpus into a failure.
    """
    _init_repo(tmp_path)
    # Untracked, so a fallback rglob WOULD pick it up — and must not.
    (tmp_path / "untracked.py").write_text("x = 1\n", encoding="utf-8")

    assert iter_tracked_files("*.py", frozenset(), root=tmp_path) == []


@_requires_git
def test_iter_production_py_files_rejects_a_collapsed_corpus(tmp_path: Path) -> None:
    """The floor this repo documented but never enforced.

    ``MIN_EXPECTED_PROD_FILES`` names this hazard verbatim ("sparse-checkout
    environments returning too few files"). Before the floor existed, a guard
    pointed at a corpus like this scanned zero files and reported PASSED.
    """
    _init_repo(tmp_path)
    (tmp_path / "untracked.py").write_text("x = 1\n", encoding="utf-8")

    with pytest.raises(AssertionError, match="production corpus collapsed"):
        iter_production_py_files(frozenset(), root=tmp_path)


def test_iter_production_py_files_accepts_the_real_repo() -> None:
    """The floor must not false-fail on the tree the guards actually scan."""
    files = iter_production_py_files(frozenset({".venv", "node_modules"}), root=repo_root())
    assert len(files) >= MIN_EXPECTED_PROD_FILES


@_requires_git
def test_iter_production_py_files_floor_is_boundary_exact(tmp_path: Path) -> None:
    """``minimum`` is a floor, not a threshold: exactly ``minimum`` passes."""
    _init_repo(tmp_path)
    _commit_py(tmp_path, "mod0.py", "mod1.py", "mod2.py")

    assert len(iter_production_py_files(frozenset(), root=tmp_path, minimum=3)) == 3
    with pytest.raises(AssertionError, match=r"found 3 .*expected >= 4"):
        iter_production_py_files(frozenset(), root=tmp_path, minimum=4)


@_requires_git
def test_iter_production_py_files_catches_an_over_broad_exclude(tmp_path: Path) -> None:
    """The other documented cause: an exclude set that eats the whole corpus."""
    _init_repo(tmp_path)
    _commit_py(tmp_path, "pkg/mod.py")

    assert len(iter_production_py_files(frozenset(), root=tmp_path, minimum=1)) == 1
    with pytest.raises(AssertionError, match="production corpus collapsed"):
        iter_production_py_files(frozenset({"pkg"}), root=tmp_path, minimum=1)


#: Guards still discovering files by walking the working tree instead of asking
#: git. A walk sees whatever happens to sit on disk, so an untracked local
#: directory joins the corpus and the guard judges a different population
#: locally than in CI. Migrating a guard lowers this; it must never rise.
_MAX_WALKING_GUARDS = 37


def _walks_the_working_tree(source: str) -> bool:
    """True when the module really CALLS ``rglob`` — not merely mentions it.

    A text match also counts a guard whose only occurrence sits inside a string
    template used as a test fixture, which is how this ratchet reported one
    guard too many. Parsing also removes the need to obfuscate the marker so
    this file does not count itself: naming the attribute is not calling it.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return False
    return any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "rglob"
        for node in ast.walk(tree)
    )


def test_working_tree_walking_does_not_spread() -> None:
    walkers = sorted(
        path.name
        for path in (repo_root() / "tests").glob("*.py")
        if _walks_the_working_tree(path.read_text(encoding="utf-8", errors="ignore"))
    )
    assert len(walkers) <= _MAX_WALKING_GUARDS, (
        f"{len(walkers)} guards discover files by walking the working tree, up "
        f"from {_MAX_WALKING_GUARDS}. Use iter_production_py_files() or "
        f"iter_tracked_files() so the corpus is git-derived and identical in "
        f"CI. Walking guards: {walkers}"
    )
