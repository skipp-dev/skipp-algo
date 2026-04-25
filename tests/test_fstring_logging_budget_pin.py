"""Pin: F-string-in-logger budget (anti-pattern).

`logger.info(f"value={x}")` evaluates the f-string at call time even
when the log level is filtered out — wasted work plus loss of
structured `extra=` context. The Python logging idiom is
`logger.info("value=%s", x)` — lazy interpolation only when emitted.

Today: 44 sites across 6 files (top: streamlit_terminal.py:16,
open_prep/streamlit_monitor.py:11, databento_volatility_screener.py:8).

Defense-only budget pin — count can only shrink. To raise the budget
you must edit this file (mandatory review).

OWASP A09 (Security Logging & Monitoring) — eager evaluation can
also leak sensitive data into exception traces if `__repr__` raises.
"""
from __future__ import annotations

import ast
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_DIR_EXCLUDE = frozenset({
    ".git", ".github", ".mypy_cache", ".pytest_cache", ".ruff_cache",
    ".venv", "venv", "node_modules", "artifacts", "docs", "scripts",
    "tests", "SMC++",
})

_LOG_METHODS = frozenset({
    "debug", "info", "warning", "error", "critical", "exception", "log",
})

_FSTRING_LOG_BUDGET = 44


def _iter_prod_py() -> list[Path]:
    out: list[Path] = []
    for p in sorted(_REPO_ROOT.rglob("*.py")):
        rel_parts = p.relative_to(_REPO_ROOT).parts
        if any(part in _DIR_EXCLUDE for part in rel_parts):
            continue
        out.append(p)
    return out


def _count_fstring_log_calls() -> int:
    n = 0
    for p in _iter_prod_py():
        try:
            tree = ast.parse(p.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            f = node.func
            if not isinstance(f, ast.Attribute):
                continue
            if f.attr not in _LOG_METHODS:
                continue
            if not node.args:
                continue
            # logger.log(level, f"...") — message is 2nd arg
            msg = node.args[1] if f.attr == "log" and len(node.args) >= 2 else node.args[0]
            if isinstance(msg, ast.JoinedStr):
                n += 1
    return n


def test_fstring_logging_budget_not_exceeded() -> None:
    """F-string-in-logger count must not exceed frozen budget.

    Use lazy interpolation: ``logger.info("x=%s", x)`` instead of
    ``logger.info(f"x={x}")``. Lazy form skips formatting when the
    log level is filtered.
    """
    actual = _count_fstring_log_calls()
    assert actual <= _FSTRING_LOG_BUDGET, (
        f"f-string-in-logger budget exceeded: {actual} > "
        f"{_FSTRING_LOG_BUDGET}. Convert to lazy form "
        f"(logger.info(\"...\", x)) or raise _FSTRING_LOG_BUDGET "
        f"(review-only)."
    )


def test_fstring_logging_drift_detector() -> None:
    """If actual drops >5 below budget, force budget update."""
    actual = _count_fstring_log_calls()
    drift = _FSTRING_LOG_BUDGET - actual
    assert drift <= 5, (
        f"_FSTRING_LOG_BUDGET drift: budget={_FSTRING_LOG_BUDGET}, "
        f"actual={actual}, drift={drift}. Lower the budget to lock "
        f"in the improvement."
    )
