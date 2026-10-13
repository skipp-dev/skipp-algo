"""Defense-pin: datetime timezone-safety zero-surface invariant.

Pins the four datetime call shapes that produce a *naive* (no
``tzinfo``) ``datetime`` object — the source of every classic UTC
vs. local-time bug. All four surfaces are currently empty in
first-party non-test code; this pin keeps them that way.

The four banned shapes:

* ``datetime.utcnow()`` — **deprecated in Python 3.12**, returns a
  naive datetime that *looks* like UTC but has no ``tzinfo``. Use
  ``datetime.now(timezone.utc)``.
* ``datetime.utcfromtimestamp(ts)`` — same problem; use
  ``datetime.fromtimestamp(ts, tz=timezone.utc)``.
* ``*.now()`` without a ``tz=`` argument — returns the system local
  time as a naive datetime. Always pass an explicit ``tz=``.
* ``*.fromtimestamp(ts)`` without a ``tz=`` argument — same.

Detection is by attribute *name* (``utcnow``, ``utcfromtimestamp``,
``now``, ``fromtimestamp``) so it covers every binding style:
``datetime.datetime.now()``, ``dt.now()``,
``from datetime import datetime`` then ``datetime.now()``, etc.
The ``tests/`` tree is excluded — three test files use
``datetime.now()`` deliberately for relative date construction and
those are out of scope.

Defense-only — no production changes. One test, one assertion.
"""

from __future__ import annotations

import ast
from pathlib import Path

from tests._guard_corpus import parse_module

ROOT = Path(__file__).resolve().parent.parent

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

# Keyword arg names that satisfy the "explicit tz" requirement on
# ``.now()`` / ``.fromtimestamp()``. Both spellings appear in the
# stdlib (``tz=`` for the methods, ``tzinfo=`` on the constructor).
_TZ_KWARGS = frozenset({"tz", "tzinfo"})


def _iter_first_party_py_files() -> list[Path]:
    out: list[Path] = []
    for path in ROOT.rglob("*.py"):
        try:
            rel_parts = path.relative_to(ROOT).parts
        except ValueError:
            continue
        if any(part in _DIR_EXCLUDE for part in rel_parts):
            continue
        out.append(path)
    return sorted(out)


def _parse(path: Path) -> ast.AST | None:
    return parse_module(path)


def _scan_naive_datetime_calls(tree: ast.AST) -> list[tuple[int, str]]:
    """Return ``[(lineno, attr), ...]`` for every naive-datetime call."""
    out: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        f = node.func
        if not isinstance(f, ast.Attribute):
            continue
        attr = f.attr
        if attr in ("utcnow", "utcfromtimestamp"):
            out.append((node.lineno, attr))
            continue
        if attr == "now":
            # ``.now()`` is naive unless tz/tzinfo is passed
            # (positional first arg or kwarg).
            has_tz = (
                len(node.args) >= 1
                or any(k.arg in _TZ_KWARGS for k in node.keywords)
            )
            if not has_tz:
                out.append((node.lineno, "now"))
            continue
        if attr == "fromtimestamp":
            # ``.fromtimestamp(ts)`` is naive unless tz/tzinfo is passed
            # (positional second arg or kwarg).
            has_tz = (
                len(node.args) >= 2
                or any(k.arg in _TZ_KWARGS for k in node.keywords)
            )
            if not has_tz:
                out.append((node.lineno, "fromtimestamp"))
    return out


def test_no_naive_datetime_calls_in_production_code() -> None:
    """Zero-surface invariant: production code never builds a naive datetime.

    This pin covers four call shapes:

    * ``datetime.utcnow()``           → ``datetime.now(timezone.utc)``
    * ``datetime.utcfromtimestamp(t)`` → ``datetime.fromtimestamp(t, tz=timezone.utc)``
    * ``*.now()``                     → ``*.now(tz=timezone.utc)``
    * ``*.fromtimestamp(t)``          → ``*.fromtimestamp(t, tz=timezone.utc)``
    """
    findings: list[str] = []
    for path in _iter_first_party_py_files():
        tree = _parse(path)
        if tree is None:
            continue
        rel = path.relative_to(ROOT).as_posix()
        for lineno, attr in _scan_naive_datetime_calls(tree):
            findings.append(f"  - {rel}:{lineno}  .{attr}(...)")
    assert not findings, (
        "Naive-datetime call(s) in production (non-test) code:\n"
        + "\n".join(findings)
        + "\n\nEvery datetime in this codebase is timezone-aware. Pass "
        "an explicit ``tz=timezone.utc`` (or other zone) to ``.now()`` / "
        "``.fromtimestamp()``, and replace ``utcnow()`` / "
        "``utcfromtimestamp()`` (deprecated in Python 3.12) with their "
        "tz-aware equivalents."
    )
