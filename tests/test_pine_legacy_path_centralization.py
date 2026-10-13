"""Pin: ``"pine/legacy"`` only appears as a string literal inside the
canonical resolver module (H-8, system review 2026-04-24).

Why
---
ADR-0003 ("Option B" resolver shim) parks LEGACY ``*.pine`` files under
``pine/legacy/`` while keeping bare-basename lookup. The location is
encoded in :data:`scripts.pine_path_resolver.PINE_LEGACY_DIR`. A new
duplicate of the literal anywhere else in the production code would
mean a second source of truth — silently rotting if the directory is
ever moved or sharded (e.g. ``pine/legacy/2025/``).

This test scans every ``*.py`` in the production tree and fails when
the literal ``"pine/legacy"`` (or its escaped variants) appears
*outside* the allow-listed files. Comments and docstrings are stripped
before the scan so descriptive prose remains free.

Allowed sites
-------------
- ``scripts/pine_path_resolver.py`` — defines ``PINE_LEGACY_DIR``.
- ``scripts/check_pine_legacy_drift.py`` — drift-lint, references the
  directory in CLI ``--help`` text.
- Any path under ``tests/`` — test fixtures may pin the literal to
  cross-check the resolver itself.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Separator-tolerant: matches `pine/legacy`, `pine\legacy`, escaped
# `pine\\legacy`, and the slashed variant `pine\/legacy`. The
# negative-lookbehind avoids accidental hits on substrings like
# `apine/legacy`.
_LEGACY_PATH_RE = re.compile(r"(?<![A-Za-z0-9_])pine[\\/]+legacy")

_ALLOWED_FILES: frozenset[str] = frozenset(
    {
        "scripts/pine_path_resolver.py",
        "scripts/check_pine_legacy_drift.py",
    }
)

_SKIP_DIR_NAMES: frozenset[str] = frozenset(
    {
        ".venv",
        "venv",
        "node_modules",
        ".git",
        "build",
        "dist",
        ".mypy_cache",
        ".ruff_cache",
        ".pytest_cache",
        "__pycache__",
        "tests",  # tests may pin the literal directly
    }
)

def _docstring_constant_ids(tree: ast.AST) -> set[int]:
    """Return id() of every Constant node that is a Module/Class/Function docstring."""
    ids: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(
            node,
            (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef),
        ):
            body = getattr(node, "body", None)
            if not body:
                continue
            first = body[0]
            if (
                isinstance(first, ast.Expr)
                and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str)
            ):
                ids.add(id(first.value))
    return ids


def _iter_production_py_files() -> list[Path]:
    files: list[Path] = []
    for path in REPO_ROOT.rglob("*.py"):
        if any(part in _SKIP_DIR_NAMES for part in path.relative_to(REPO_ROOT).parts):
            continue
        files.append(path)
    return files


def _string_literal_violations(path: Path) -> list[tuple[int, str]]:
    r"""Return (lineno, value) for every banned literal in ``path``.

    Walks ``ast.Constant`` strings only — comments and ``#``-style
    annotations are excluded automatically. Module/class/function
    docstrings are skipped so descriptive prose (e.g. an ADR-0003
    reference in a module header) does not fail the pin. Matching is
    separator-tolerant via :data:`_LEGACY_PATH_RE` to catch escaped
    forms like ``pine\legacy`` or ``pine\/legacy``.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return []
    try:
        tree = ast.parse(text, filename=str(path))
    except SyntaxError:
        return []
    docstring_ids = _docstring_constant_ids(tree)
    hits: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
            continue
        if id(node) in docstring_ids:
            continue
        if _LEGACY_PATH_RE.search(node.value):
            hits.append((node.lineno, node.value))
    return hits


def test_pine_legacy_literal_only_in_allowlisted_files() -> None:
    violations: list[str] = []
    for path in _iter_production_py_files():
        rel = path.relative_to(REPO_ROOT).as_posix()
        if rel in _ALLOWED_FILES:
            continue
        for lineno, value in _string_literal_violations(path):
            violations.append(f"{rel}:{lineno}: {value!r}")

    assert not violations, (
        "The literal 'pine/legacy' must not appear outside the canonical "
        "resolver module. Import PINE_LEGACY_DIR from "
        "scripts.pine_path_resolver instead (H-8 alignment).\n"
        + "\n".join(violations)
    )
