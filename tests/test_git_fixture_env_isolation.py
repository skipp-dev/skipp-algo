"""Every git launched by a sandbox fixture must carry an explicit ``env=``.

Why this file exists
--------------------
On 2026-08-04 a fixture in ``tests/test_smc_library_refresh_workflow.py`` built
a throwaway repository with ``cwd=<sandbox>`` and no ``env=``. ``cwd`` is not
isolation: with ``GIT_DIR`` / ``GIT_INDEX_FILE`` present in the environment,
git resolves its repository from them first, so ``git add -A`` / ``git commit``
retargeted the REAL checkout. A commit named ``seed`` landed on a contributor's
branch, 156 tracked files were staged as deleted, and an unrelated ledger guard
went red on the corrupted index. The suite reported passing throughout.

The fix added ``_isolated_env()``. Its commit message then claimed the coverage
was "verified by an AST walk rather than by eye: zero subprocess calls without
env=". **No such walk existed.** The claim happened to be true, and a review on
2026-08-04 confirmed it by hand — but nothing enforced it, so the next fixture
added to those files would have re-opened the hole under a green suite and a
commit message asserting the opposite. This file is that walk.

What is checked, and what deliberately is not
---------------------------------------------
Only the files in :data:`SANDBOX_GIT_FIXTURE_FILES` — the ones that build git
repositories in a temporary directory. A read-only ``git ls-files`` against the
real repository root is a different thing entirely: it is *supposed* to read
the ambient checkout, and requiring ``env=`` there would be cargo cult. Two
such call sites exist today (``tests/test_no_merge_conflict_markers.py``,
``tests/test_six_zero_tripwires_bundle.py``) and are intentionally out of scope.

Adding a file here is cheap; the roster is the declaration of "this file
mutates git state in a sandbox".
"""

from __future__ import annotations

import ast
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]

#: Files whose fixtures create and mutate git repositories under a temp dir.
SANDBOX_GIT_FIXTURE_FILES = (
    "tests/test_smc_library_refresh_workflow.py",
    "tests/test_analyze_publish_cadence.py",
)

#: Callables in :mod:`subprocess` that actually start a process. Deliberately
#: NOT a substring match on ``subprocess.``: ``CompletedProcess``,
#: ``CalledProcessError`` and ``TimeoutExpired`` are constructors used to build
#: stub return values and raise-paths, and flagging those would train whoever
#: hits it to add a meaningless ``env=`` to a data object.
_LAUNCHERS = frozenset({"run", "call", "check_call", "check_output", "Popen"})


def _is_launch(node: ast.Call) -> bool:
    """Does this call start a subprocess?

    Rejects the nested-call trap: ``subprocess.run(...).stdout.strip()`` is a
    ``Call`` whose unparsed func begins with ``subprocess.`` and carries no
    keywords at all. A prefix test flags it and reports the very line that is
    already correct — measured while writing this file.
    """
    func = node.func
    if isinstance(func, ast.Attribute):
        return func.attr in _LAUNCHERS and ast.unparse(func).startswith("subprocess.")
    return False


def _mentions_git(node: ast.Call) -> bool:
    if not node.args:
        return False
    return "'git'" in ast.unparse(node.args[0]) or '"git"' in ast.unparse(node.args[0])


def find_git_launches_without_env(source: str) -> list[tuple[int, str]]:
    """``(lineno, source)`` for every git-launching call that omits ``env=``."""
    offenders: list[tuple[int, str]] = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call) or not _is_launch(node):
            continue
        if not _mentions_git(node):
            continue
        if any(keyword.arg == "env" for keyword in node.keywords):
            continue
        offenders.append((node.lineno, ast.unparse(node)[:120]))
    return offenders


def count_git_launches(source: str) -> int:
    return sum(
        1
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call) and _is_launch(node) and _mentions_git(node)
    )


_COUNTER_PROOF = '''
import subprocess

def flagged_plain(tmp):
    subprocess.run(["git", "init"], cwd=tmp, check=True)

def flagged_check_output(tmp):
    subprocess.check_output(["git", "log"], cwd=tmp)

def flagged_popen(tmp):
    subprocess.Popen(["git", "status"], cwd=tmp)

def unflagged_has_env(tmp, env):
    subprocess.run(["git", "init"], cwd=tmp, check=True, env=env)

def unflagged_not_git(tmp):
    subprocess.run(["ruff", "check"], cwd=tmp, check=True)

def unflagged_is_a_data_object(out):
    return subprocess.CompletedProcess(args=["git"], returncode=0, stdout=out)

def unflagged_nested_accessor(tmp, env):
    return subprocess.run(["git", "log"], cwd=tmp, env=env, capture_output=True).stdout.strip()
'''


def test_the_detector_flags_what_it_should_and_nothing_else() -> None:
    """The guard's own counter-proof: without it, a green scan proves nothing.

    Three shapes must be caught and four must not. The last two are the traps
    that make a naive detector useless: a ``CompletedProcess`` is a data object,
    and ``subprocess.run(...).stdout.strip()`` is a correct call whose OUTER
    node has no keywords.
    """
    offenders = find_git_launches_without_env(_COUNTER_PROOF)
    flagged = {source for _, source in offenders}

    assert len(offenders) == 3, f"expected exactly 3 offenders, got {offenders}"
    assert any("git" in s and "init" in s for s in flagged)
    assert any("check_output" in s for s in flagged)
    assert any("Popen" in s for s in flagged)
    assert not any("env=env" in s for s in flagged), (
        "a call passing env= was flagged; the guard would force noise into "
        "correct code and get itself loosened"
    )
    assert not any("ruff" in s for s in flagged), "a non-git launch was flagged"
    assert not any("CompletedProcess" in s for s in flagged), (
        "a data object was flagged as a process launch"
    )


def test_every_declared_fixture_file_really_launches_git() -> None:
    """Non-vacuity: a roster of files that launch nothing scans nothing.

    Without this, deleting the git calls from a listed file — or listing a file
    that never had any — leaves the guard below reporting a clean sweep forever.
    """
    for relative in SANDBOX_GIT_FIXTURE_FILES:
        path = _REPO_ROOT / relative
        assert path.is_file(), (
            f"{relative} is on the sandbox-git-fixture roster but does not exist. "
            "Remove it from SANDBOX_GIT_FIXTURE_FILES in the same commit that "
            "removes the file, or this guard silently covers nothing."
        )
        launches = count_git_launches(path.read_text(encoding="utf-8"))
        assert launches > 0, (
            f"{relative} is on the roster but launches no git at all, so the "
            "env= sweep over it is vacuous. Drop it from the roster or restore "
            "the fixture."
        )


def test_no_sandbox_fixture_launches_git_without_an_explicit_env() -> None:
    """The claim the 2026-08-04 commit message made, now actually enforced.

    ``cwd=`` does not isolate: ``GIT_DIR`` and ``GIT_INDEX_FILE`` outrank it, so
    a fixture missing ``env=`` writes into whatever repository the environment
    points at. That is not hypothetical — it committed a temp tree into this
    repository and corrupted its index.
    """
    for relative in SANDBOX_GIT_FIXTURE_FILES:
        source = (_REPO_ROOT / relative).read_text(encoding="utf-8")
        offenders = find_git_launches_without_env(source)
        assert not offenders, (
            f"{relative} launches git without an explicit env=:\n"
            + "\n".join(f"  line {line}: {text}" for line, text in offenders)
            + "\n\nPass a GIT_*-scrubbed environment. `cwd=` is not isolation: "
            "git resolves its repository from GIT_DIR / GIT_INDEX_FILE first, "
            "and git exports both into every hook it runs — which is where this "
            "suite executes."
        )
