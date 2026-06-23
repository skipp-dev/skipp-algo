"""Pin: zero shell-injection-prone call patterns in first-party Python.

Two zero-tripwires:

1. ``shell=True`` keyword on any call site (typically ``subprocess.run``,
   ``subprocess.Popen``, ``subprocess.call``, ``subprocess.check_output``).
   Shell-mode subprocess invocation enables shell-injection (OWASP A03)
   when any input is non-literal.

2. ``os.popen(...)`` calls. Always shell-mode, always
   shell-injection-prone. Use ``subprocess.run([...], shell=False)``
   instead.

These pins start from current zero (no offenders) and lock the codebase
against regressions.
"""
from __future__ import annotations

import ast
from pathlib import Path

from tests._guard_corpus import iter_tracked_files, parse_module

_REPO_ROOT = Path(__file__).resolve().parents[1]

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
        "scripts",
        "tests",
        "SMC++",
    }
)


def _iter_first_party_py() -> list[Path]:
    return iter_tracked_files("*.py", _DIR_EXCLUDE, root=_REPO_ROOT)


def _is_os_popen(call: ast.Call) -> bool:
    f = call.func
    return (
        isinstance(f, ast.Attribute)
        and f.attr == "popen"
        and isinstance(f.value, ast.Name)
        and f.value.id == "os"
    )


def _has_shell_true_kw(call: ast.Call) -> bool:
    for kw in call.keywords:
        if (
            kw.arg == "shell"
            and isinstance(kw.value, ast.Constant)
            and kw.value.value is True
        ):
            return True
    return False


def _scan() -> tuple[list[tuple[str, int]], list[tuple[str, int]]]:
    shell_true: list[tuple[str, int]] = []
    os_popen: list[tuple[str, int]] = []
    for p in _iter_first_party_py():
        tree = parse_module(p)
        if tree is None:
            continue
        rel = str(p.relative_to(_REPO_ROOT))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if _has_shell_true_kw(node):
                shell_true.append((rel, node.lineno))
            if _is_os_popen(node):
                os_popen.append((rel, node.lineno))
    return shell_true, os_popen


def test_no_shell_true_in_production() -> None:
    """No ``shell=True`` keyword on any call in first-party prod code.

    Shell-mode subprocess invocation is shell-injection-prone whenever the
    command string contains any non-literal substring. Use
    ``subprocess.run([...], shell=False)`` (the default) with a list of
    arguments instead.
    """
    shell_true, _ = _scan()
    assert shell_true == [], (
        "Forbidden `shell=True` call(s) found — shell-injection risk. "
        f"Offenders ({len(shell_true)}): {shell_true}. "
        "Use a list of arguments with shell=False instead."
    )


def test_no_os_popen_in_production() -> None:
    """No ``os.popen(...)`` calls in first-party prod code.

    ``os.popen`` is always shell-mode and is a classic shell-injection
    vector. Use ``subprocess.run([...], capture_output=True,
    shell=False)`` instead.
    """
    _, os_popen = _scan()
    assert os_popen == [], (
        "Forbidden `os.popen(...)` call(s) found — shell-injection risk. "
        f"Offenders ({len(os_popen)}): {os_popen}. "
        "Use subprocess.run([...]) instead."
    )
