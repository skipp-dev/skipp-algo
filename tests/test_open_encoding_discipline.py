"""Tripwire: every text-mode ``open(...)`` in first-party production code
must pass an explicit ``encoding=`` keyword.

Background
----------
Python's default text encoding is platform-dependent (``utf-8`` on macOS
and Linux, ``cp1252`` on Windows). Production code that reads or writes
text files without specifying ``encoding=`` produces silently different
bytes depending on the OS — a class of bug we have explicitly bitten on
in the past with ``.env`` and lock files.

This pin walks the AST of first-party production ``*.py`` files and
fails when any ``open(...)`` call (a) is opened in text mode and (b)
omits the ``encoding=`` keyword. Binary opens (``"rb"``, ``"wb"``,
``"ab"``, ``"r+b"`` …) are exempt because ``encoding`` is meaningless
for them.

Scope
-----
Production code only. ``tests/``, ``scripts/``, ``docs/``, virtualenvs,
caches, and the ``SMC++/`` Pine workspace are excluded so the gate stays
fast and signal-rich. A small file-level allowlist below covers
generated or vendored modules where this discipline cannot be enforced;
the allowlist is also pinned by a sub-test that fails if an entry no
longer matches anything (so it cannot grow stale).
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent

# Top-level entries excluded entirely (tests, tooling, vendored).
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

# File-level allowlist: known sites that legitimately cannot specify
# encoding= (e.g. binary helpers detected as text by mode inference).
# Keep small; every entry MUST still resolve to an existing file (the
# stale-allowlist sub-test enforces this).
_FILE_ALLOWLIST: frozenset[str] = frozenset()


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


def _open_call_mode(call: ast.Call) -> str | None:
    """Best-effort extraction of the ``mode=`` value from an ``open(...)`` call.

    Returns ``None`` when the mode cannot be statically resolved.
    """
    if len(call.args) >= 2 and isinstance(call.args[1], ast.Constant):
        value = call.args[1].value
        return value if isinstance(value, str) else None
    for kw in call.keywords:
        if kw.arg == "mode" and isinstance(kw.value, ast.Constant):
            value = kw.value.value
            if isinstance(value, str):
                return value
    return None


def _is_text_mode(mode: str | None) -> bool:
    """Text mode if mode is unspecified (default ``"r"``) or has no ``b``."""
    if mode is None:
        return True
    return "b" not in mode


def _has_encoding_kwarg(call: ast.Call) -> bool:
    return any(kw.arg == "encoding" for kw in call.keywords)


def _is_open_call(call: ast.Call) -> bool:
    """True for ``open(...)`` invoked as a bare name (not ``foo.open(...)``)."""
    return isinstance(call.func, ast.Name) and call.func.id == "open"


def _collect_violations(path: Path) -> list[tuple[int, str]]:
    """Return ``(lineno, snippet)`` pairs for missing-encoding ``open`` calls."""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return []
    lines = text.splitlines()
    violations: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not _is_open_call(node):
            continue
        mode = _open_call_mode(node)
        if not _is_text_mode(mode):
            continue
        if _has_encoding_kwarg(node):
            continue
        snippet = lines[node.lineno - 1].strip() if 0 < node.lineno <= len(lines) else ""
        violations.append((node.lineno, snippet))
    return violations


def test_first_party_files_present() -> None:
    """Sanity: the scan actually finds production files (catch path drift)."""
    files = _iter_first_party_py_files()
    assert len(files) >= 50, (
        f"Expected at least 50 first-party .py files; found {len(files)}. "
        "If the repo layout changed, update _DIR_EXCLUDE."
    )


def test_open_calls_specify_encoding() -> None:
    """Every text-mode ``open(...)`` in production code must pass ``encoding=``."""
    failures: list[str] = []
    for path in _iter_first_party_py_files():
        rel = path.relative_to(_REPO_ROOT).as_posix()
        if rel in _FILE_ALLOWLIST:
            continue
        for lineno, snippet in _collect_violations(path):
            failures.append(f"{rel}:{lineno}: {snippet}")
    assert not failures, (
        "open() called in text mode without encoding= in production code:\n  - "
        + "\n  - ".join(failures)
        + "\nFix by adding encoding=\"utf-8\" (or the appropriate codec)."
    )


@pytest.mark.parametrize("entry", sorted(_FILE_ALLOWLIST))
def test_file_allowlist_entries_still_apply(entry: str) -> None:
    """Allowlisted files must still exist — prevents stale entries."""
    path = _REPO_ROOT / entry
    assert path.is_file(), (
        f"Allowlist entry '{entry}' no longer exists; remove it from "
        "_FILE_ALLOWLIST in this test."
    )
