"""Defense-pin: zero-surface invariants for three classic foot-guns.

Three independent zero-surface bans grouped because each is *currently
empty* in the codebase and reintroduction of any one is a security
regression worth blocking at CI:

1. ``exec(...)`` — dynamic code execution from string. **CWE-95**
   (Code Injection / 'eval injection'). Sister of #219 which already
   bans ``eval(...)`` and ``pickle.load(s)``. ``exec`` was deferred at
   the time; this closes the gap.

2. ``tempfile.mktemp(...)`` — deprecated since Python 2.3 because of an
   inherent **TOCTOU race** (CWE-377 / CWE-367): the function returns
   a path *and then closes it*, so another process can win the
   race-to-create. The supported replacements are
   ``tempfile.mkstemp`` (returns an open fd) or
   ``tempfile.NamedTemporaryFile`` (returns an open file object).

3. ``subprocess.*(..., shell=True, ...)`` — passing a string to
   ``/bin/sh -c`` is a textbook **CWE-78** (OS Command Injection)
   sink whenever any part of the string is operator-controlled or
   interpolated. The supported replacement is the list-form invocation
   without ``shell=``. The ban applies to ``subprocess.run``,
   ``subprocess.Popen``, ``subprocess.call``, ``subprocess.check_call``,
   ``subprocess.check_output``.

Surface today: 0 / 0 / 0. Each test asserts the offender list is empty.
"""

from __future__ import annotations

import ast
from pathlib import Path

from tests._guard_corpus import parse_module

_REPO_ROOT = Path(__file__).resolve().parent.parent

_DIR_EXCLUDE = frozenset(
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
        "tests",
        "SMC++",
    }
)

_SUBPROCESS_FUNCS = frozenset({"run", "Popen", "call", "check_call", "check_output"})


def _iter_first_party_trees():
    for path in _REPO_ROOT.rglob("*.py"):
        if any(part in _DIR_EXCLUDE for part in path.relative_to(_REPO_ROOT).parts):
            continue
        tree = parse_module(path)
        if tree is None:
            continue
        yield path.relative_to(_REPO_ROOT), tree


def _is_exec_call(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "exec"
    )


def _is_mktemp_call(node: ast.AST) -> bool:
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    return (
        isinstance(func, ast.Attribute)
        and func.attr == "mktemp"
        and isinstance(func.value, ast.Name)
        and func.value.id == "tempfile"
    )


def _is_subprocess_shell_true(node: ast.AST) -> bool:
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    if not (
        isinstance(func, ast.Attribute)
        and func.attr in _SUBPROCESS_FUNCS
        and isinstance(func.value, ast.Name)
        and func.value.id == "subprocess"
    ):
        return False
    for kw in node.keywords:
        if kw.arg == "shell" and isinstance(kw.value, ast.Constant) and kw.value.value is True:
            return True
    return False


def _collect(predicate) -> list[tuple[str, int]]:
    out: list[tuple[str, int]] = []
    for rel, tree in _iter_first_party_trees():
        for node in ast.walk(tree):
            if predicate(node):
                out.append((str(rel), node.lineno))
    return sorted(out)


def test_no_exec_call_sites() -> None:
    offenders = _collect(_is_exec_call)
    assert offenders == [], (
        "exec(...) is a CWE-95 sink — replace with explicit dispatch / "
        "structured config. Offenders: " + repr(offenders)
    )


def test_no_tempfile_mktemp_sites() -> None:
    offenders = _collect(_is_mktemp_call)
    assert offenders == [], (
        "tempfile.mktemp(...) has a TOCTOU race (CWE-377/367) and has "
        "been deprecated since Python 2.3. Use tempfile.mkstemp or "
        "tempfile.NamedTemporaryFile. Offenders: " + repr(offenders)
    )


def test_no_subprocess_shell_true_sites() -> None:
    offenders = _collect(_is_subprocess_shell_true)
    assert offenders == [], (
        "subprocess.*(..., shell=True, ...) is a CWE-78 (OS command "
        "injection) sink whenever any input is interpolated. Use "
        "list-form invocation without shell=. Offenders: " + repr(offenders)
    )
