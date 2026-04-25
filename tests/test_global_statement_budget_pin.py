"""Defense-only pin: bound `global` statement usage in production source.

Rationale (OWASP A04 Insecure Design / maintainability hardening):
- `global` introduces hidden write side-effects and shared mutable state,
  the most common source of test pollution, race conditions in concurrent
  code paths (Streamlit reruns, async pollers), and order-dependent bugs
  that escape unit tests.
- This pin freezes today's count so any new `global` declaration in
  production source requires explicit review (raise budget + justification
  or refactor to dependency injection / class state).

Drift detector: if total falls more than 5 below the budget, the test
fails and forces lowering the budget — preventing silent debt regrowth.
"""
from __future__ import annotations

import ast
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent

_DIR_EXCLUDE = frozenset({
    ".git", ".github", ".mypy_cache", ".pytest_cache", ".ruff_cache",
    ".venv", "venv", "node_modules", "artifacts", "docs", "scripts",
    "tests", "SMC++",
})

# Budget snapshot (2026-04-23): 26 `global` statements across 11 files.
_GLOBAL_BUDGET = 26
_DRIFT_TOLERANCE = 5


def _count_global_statements() -> int:
    total = 0
    for path in sorted(_REPO_ROOT.rglob("*.py")):
        if any(part in _DIR_EXCLUDE for part in path.relative_to(_REPO_ROOT).parts):
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError, OSError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Global):
                total += 1
    return total


def test_global_statement_budget_not_exceeded() -> None:
    """`global` statement count must not grow beyond the frozen budget."""
    actual = _count_global_statements()
    assert actual <= _GLOBAL_BUDGET, (
        f"`global` statement count {actual} exceeds budget {_GLOBAL_BUDGET}. "
        "New `global` introduces hidden write side-effects and shared mutable "
        "state (test pollution, race conditions in Streamlit/async paths). "
        "Either refactor to dependency injection / class state, or update "
        "_GLOBAL_BUDGET with justification."
    )


def test_global_statement_budget_drift_detector() -> None:
    """If actual count drops well below budget, force the budget to be lowered."""
    actual = _count_global_statements()
    assert actual >= _GLOBAL_BUDGET - _DRIFT_TOLERANCE, (
        f"`global` statement count {actual} is {_GLOBAL_BUDGET - actual} below "
        f"budget {_GLOBAL_BUDGET} (tolerance={_DRIFT_TOLERANCE}). "
        "Lower _GLOBAL_BUDGET to lock in the improvement and prevent silent regrowth."
    )
