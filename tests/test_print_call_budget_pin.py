"""Defense-only pin: bound print() call sites in production source.

Rationale (OWASP A09 Logging Failures):
- print() bypasses the logging framework: no level, no handler, no rotation,
  no structured fields, no security-relevant filtering, no test capture.
- Production print() calls also break Streamlit/Gunicorn buffering
  expectations and can leak sensitive payloads to stdout in unintended
  contexts. CLI scripts intentionally use print() for human output and
  remain bounded by this budget.
- This pin freezes today's count so any new print() in production source
  requires explicit review (raise budget + justification).

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

# Budget snapshot (2026-04-23): 38 print() calls across 7 CLI/script files.
_PRINT_BUDGET = 38
_DRIFT_TOLERANCE = 5


def _count_print_calls() -> int:
    total = 0
    for path in sorted(_REPO_ROOT.rglob("*.py")):
        if any(part in _DIR_EXCLUDE for part in path.relative_to(_REPO_ROOT).parts):
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError, OSError):
            continue
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "print"
            ):
                total += 1
    return total


def test_print_call_budget_not_exceeded() -> None:
    """print() call count must not grow beyond the frozen budget."""
    actual = _count_print_calls()
    assert actual <= _PRINT_BUDGET, (
        f"print() call count {actual} exceeds budget {_PRINT_BUDGET}. "
        "New print() calls in production source bypass the logging framework "
        "(no level, no handler, no test capture, leakage risk). "
        "Either replace with logger.X() or update _PRINT_BUDGET with justification."
    )


def test_print_call_budget_drift_detector() -> None:
    """If actual count drops well below budget, force the budget to be lowered."""
    actual = _count_print_calls()
    assert actual >= _PRINT_BUDGET - _DRIFT_TOLERANCE, (
        f"print() call count {actual} is {_PRINT_BUDGET - actual} below "
        f"budget {_PRINT_BUDGET} (tolerance={_DRIFT_TOLERANCE}). "
        "Lower _PRINT_BUDGET to lock in the improvement and prevent silent regrowth."
    )
