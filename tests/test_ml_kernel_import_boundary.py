"""Kernel boundary guard: ``ml/`` must not depend on domain packages.

The ``ml/`` package is a deliberately domain-free numerical kernel
(fractional differentiation, walk-forward purging, metrics, feature
transforms). Its dependency arrows point *one way*: ``governance/`` and
the ``terminal_*`` runtime import *from* ``ml/`` — never the reverse.

Keeping that arrow uni-directional is what makes ``ml/`` cheaply
extractable later (a single ``git filter-repo`` away) should a second
consumer or a distribution target ever materialise. Without an
automated guard, a future contributor could quietly add
``from governance...`` inside ``ml/`` and silently couple the kernel to
the trading domain, destroying that option at zero warning.

This module parses every ``ml/**/*.py`` file with ``ast`` (no execution)
and asserts none of them import a forbidden domain root. The check is a
*static* AST scan — the cheapest way to enforce the boundary without a
sandboxed import.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
ML_ROOT = REPO_ROOT / "ml"

# Exact top-level module names ``ml/`` may never import.
FORBIDDEN_ROOTS = frozenset({
    "governance",
    "open_prep",
    "open_prep_boundary",
    "strategy_config",
    "newsstack_fmp",
    "conftest",
})

# Prefixes for the domain runtime: any import whose top-level name starts
# with one of these is a forbidden cross-layer dependency.
FORBIDDEN_PREFIXES = (
    "terminal_",
    "databento",
    "streamlit",
    "pine_",
)


def _ml_python_files() -> list[Path]:
    """Return every ``.py`` file under ``ml/`` (excluding ``__pycache__``)."""
    return sorted(
        p
        for p in ML_ROOT.rglob("*.py")
        if "__pycache__" not in p.parts
    )


def _collect_imported_roots(source: str) -> set[str]:
    """Return the set of top-level module names imported in *source*."""
    tree = ast.parse(source)
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                roots.add(alias.name.split(".", 1)[0])
        # ImportFrom.module is None for "from . import x" — a relative
        # import that can never reach a forbidden domain root, so skip it.
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.split(".", 1)[0])
    return roots


def _forbidden(root: str) -> bool:
    """True if *root* is a domain package the kernel may not import."""
    if root in FORBIDDEN_ROOTS:
        return True
    return any(root.startswith(prefix) for prefix in FORBIDDEN_PREFIXES)


def test_ml_root_exists() -> None:
    """The kernel package must exist for the boundary guard to be meaningful."""
    assert ML_ROOT.is_dir(), (
        f"ml/ kernel package missing at {ML_ROOT}. If the kernel moved, "
        "update ML_ROOT in tests/test_ml_kernel_import_boundary.py."
    )
    assert _ml_python_files(), "ml/ contains no Python files to guard."


@pytest.mark.parametrize(
    "ml_file",
    _ml_python_files(),
    ids=lambda p: p.relative_to(REPO_ROOT).as_posix(),
)
def test_ml_kernel_imports_no_domain_package(ml_file: Path) -> None:
    """``ml/`` must not import ``governance/`` or any ``terminal_*`` runtime."""
    source = ml_file.read_text(encoding="utf-8")
    imported = _collect_imported_roots(source)
    violations = sorted(root for root in imported if _forbidden(root))
    assert not violations, (
        f"Kernel boundary violation in {ml_file.relative_to(REPO_ROOT)}: "
        f"forbidden domain imports {violations}. The ml/ package is a "
        "domain-free numerical kernel and must not depend on governance/, "
        "open_prep, strategy_config, or any terminal_*/databento/streamlit "
        "runtime. Invert the dependency (import ml/ from the domain layer "
        "instead), or — if the boundary is intentionally being lifted — "
        "update FORBIDDEN_ROOTS/FORBIDDEN_PREFIXES in "
        "tests/test_ml_kernel_import_boundary.py with a written rationale."
    )
