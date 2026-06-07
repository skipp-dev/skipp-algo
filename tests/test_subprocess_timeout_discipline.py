"""Tripwire: every blocking ``subprocess.*`` call in first-party production
code must pass an explicit ``timeout=`` keyword.

Background
----------
Blocking ``subprocess`` invocations (``run``, ``check_output``,
``check_call``, ``call``) wait synchronously for the child to exit. The
default behaviour is to wait forever. In CI that translates directly to
wedged jobs (e.g. a hung ``git`` invocation behind a network filesystem,
a child shelling out to a flaky CLI). We've already eaten one such
incident on the ``git rev-parse HEAD`` site in ``release_policy.py``.

This pin walks the AST of first-party production ``*.py`` files and
fails when any blocking ``subprocess.*`` call (or the ``subprocess.run``
imported as a bare name) omits the ``timeout=`` keyword.

Scope
-----
**Blocking** primitives only:
``subprocess.run``, ``subprocess.check_output``, ``subprocess.check_call``,
``subprocess.call``. ``subprocess.Popen`` is intentionally exempt — it is
the launch primitive used for long-lived detached children
(e.g. ``open_prep/realtime_signals.py`` engine boot), where a timeout
on the *spawn* itself would be meaningless. Tests, scripts, docs,
virtualenvs, caches, and the ``SMC++/`` Pine workspace are excluded.

A small site-level allowlist is provided as ``(rel_path, lineno)`` tuples
for legitimately unbounded blocking calls; a sub-test asserts each entry
still resolves to the original ``open()`` AST so stale entries cannot
silently rot. Allowlist starts empty.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from tests._guard_corpus import parse_module, read_source

_REPO_ROOT = Path(__file__).resolve().parent.parent

_DIR_EXCLUDE: frozenset[str] = frozenset(
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

_BLOCKING_FUNCS: frozenset[str] = frozenset(
    {"run", "check_output", "check_call", "call"}
)

# Site-level allowlist: (rel_path, lineno). Keep small. The
# stale-allowlist sub-test fails if the line no longer matches a
# blocking subprocess call.
_SITE_ALLOWLIST: frozenset[tuple[str, int]] = frozenset()


def _iter_first_party_py_files() -> list[Path]:
    """Return all first-party production ``*.py`` files under the repo."""
    files: list[Path] = []
    for entry in _REPO_ROOT.iterdir():
        if entry.name.startswith("."):
            continue
        if entry.name in _DIR_EXCLUDE:
            continue
        if entry.is_file() and entry.suffix == ".py":
            files.append(entry)
        elif entry.is_dir():
            for path in entry.rglob("*.py"):
                if any(part.startswith(".") for part in path.parts):
                    continue
                if any(part in _DIR_EXCLUDE for part in path.parts):
                    continue
                files.append(path)
    return sorted(files)


def _is_blocking_subprocess_call(node: ast.Call) -> bool:
    """True for ``subprocess.<blocking>(...)`` invocations.

    We intentionally do NOT match bare-name ``run(...)``: the project
    convention is to import the module (``import subprocess``) and call
    via attribute, which keeps the AST check unambiguous.
    """
    func = node.func
    if not isinstance(func, ast.Attribute):
        return False
    if not isinstance(func.value, ast.Name):
        return False
    if func.value.id != "subprocess":
        return False
    return func.attr in _BLOCKING_FUNCS


def _has_timeout_kwarg(node: ast.Call) -> bool:
    return any(kw.arg == "timeout" for kw in node.keywords)


def _collect_violations(path: Path) -> list[tuple[int, str]]:
    text = read_source(path)
    if text is None:
        return []
    tree = parse_module(path)
    if tree is None:
        return []
    lines = text.splitlines()
    out: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not _is_blocking_subprocess_call(node):
            continue
        if _has_timeout_kwarg(node):
            continue
        snippet = lines[node.lineno - 1].strip() if 0 < node.lineno <= len(lines) else ""
        out.append((node.lineno, snippet))
    return out


def test_first_party_files_present() -> None:
    """Sanity: scan finds production files (catches layout drift)."""
    files = _iter_first_party_py_files()
    assert len(files) >= 50, (
        f"Expected at least 50 first-party .py files; found {len(files)}. "
        "If the repo layout changed, update _DIR_EXCLUDE."
    )


def test_blocking_subprocess_calls_specify_timeout() -> None:
    """Every blocking ``subprocess.*`` call in production code needs ``timeout=``."""
    failures: list[str] = []
    for path in _iter_first_party_py_files():
        rel = path.relative_to(_REPO_ROOT).as_posix()
        for lineno, snippet in _collect_violations(path):
            if (rel, lineno) in _SITE_ALLOWLIST:
                continue
            failures.append(f"{rel}:{lineno}: {snippet}")
    assert not failures, (
        "Blocking subprocess.* call(s) without explicit timeout= in "
        "production code:\n  - "
        + "\n  - ".join(failures)
        + "\nAdd timeout=<seconds>. subprocess.Popen is exempt from this rule."
    )


@pytest.mark.parametrize("entry", sorted(_SITE_ALLOWLIST))
def test_site_allowlist_entries_still_apply(entry: tuple[str, int]) -> None:
    """Allowlist entries must still match a blocking subprocess call.

    Prevents stale entries from accidentally laundering newly-added
    unrelated code on the same line.
    """
    rel_path, lineno = entry
    path = _REPO_ROOT / rel_path
    assert path.is_file(), f"Allowlist entry path missing: {rel_path}"
    matched = any(
        viol_lineno == lineno for viol_lineno, _ in _collect_violations(path)
    )
    assert matched, (
        f"Allowlist entry {rel_path}:{lineno} no longer matches a blocking "
        "subprocess.* call without timeout=. Remove the entry from "
        "_SITE_ALLOWLIST."
    )
