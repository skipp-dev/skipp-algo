"""Pin: every ``pd.to_datetime`` call on a known timestamp column passes ``utc=True``.

Background
==========

PR #95 (TZ-2) and the SESSIONS UTC-fixed contract require that any
naive timestamp parsed from external data is normalised to UTC at the
boundary. Date-only columns may parse without ``utc=True`` (the
result is a date, not a moment-in-time).

This pin walks every ``pd.to_datetime(...)`` / ``to_datetime(...)``
call across the workspace (excluding ``.venv``, generated, and tests)
and flags any call where the first positional argument is a
**subscript whose key is a known timestamp column name** but the call
lacks ``utc=True``.

Known timestamp column names are pinned in
:data:`_TIMESTAMP_COLUMN_NAMES`. To allowlist a name as
date-only, add it to :data:`_DATE_ONLY_COLUMN_NAMES`.

Currently expected: 0 violations (verified by zero-hit grep at the
PR landing).
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

_EXCLUDE_DIR_NAMES = frozenset({
    ".venv", ".git", "__pycache__", "node_modules",
    ".mypy_cache", ".pytest_cache", "build", "dist", "tests",
})

# Column names whose values are moment-in-time (must be parsed with utc=True).
_TIMESTAMP_COLUMN_NAMES: frozenset[str] = frozenset({
    "timestamp",
    "ts",
    "ts_event",
    "ts_recv",
    "datetime",
    "last_window_timestamp",
    "window_timestamp",
    "event_time",
    "published_at",
    "created_at",
    "updated_at",
    # Already-utc=True call sites in the repo — added so a future regression
    # that drops the kwarg on these specific columns is caught by the pin.
    "generated_at",            # databento_volatility_screener.py
    "snapshot_at",             # databento_volatility_screener.py
    "current_price_timestamp", # scripts/databento_production_export.py
})

# Column names whose values are dates (utc=True is irrelevant / wrong).
_DATE_ONLY_COLUMN_NAMES: frozenset[str] = frozenset({
    "trade_date",
    "asof_date",
    "date",
    "session_date",
    "expiry_date",
})


def _iter_python_files() -> list[Path]:
    out: list[Path] = []
    for path in REPO_ROOT.rglob("*.py"):
        if any(part in _EXCLUDE_DIR_NAMES for part in path.relative_to(REPO_ROOT).parts):
            continue
        out.append(path)
    return sorted(out)


def _is_to_datetime_call(node: ast.AST) -> bool:
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    if isinstance(func, ast.Attribute) and func.attr == "to_datetime":
        return True
    return bool(isinstance(func, ast.Name) and func.id == "to_datetime")


def _first_arg_subscript_key(call: ast.Call) -> str | None:
    """If first arg is ``frame["col"]`` / ``frame.get("col")``, return ``col``."""
    if not call.args:
        return None
    arg = call.args[0]
    # frame["col"]
    if isinstance(arg, ast.Subscript):
        slice_val = arg.slice
        if isinstance(slice_val, ast.Constant) and isinstance(slice_val.value, str):
            return slice_val.value
    # frame.get("col")
    if isinstance(arg, ast.Call) and isinstance(arg.func, ast.Attribute) and arg.func.attr == "get" and arg.args:
        inner = arg.args[0]
        if isinstance(inner, ast.Constant) and isinstance(inner.value, str):
            return inner.value
    return None


def _has_utc_kwarg(call: ast.Call) -> bool:
    for kw in call.keywords:
        if kw.arg == "utc" and isinstance(kw.value, ast.Constant) and kw.value.value is True:
            return True
    return False


def _collect_violations(path: Path) -> list[tuple[str, int, str]]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError):
        return []
    rel = str(path.relative_to(REPO_ROOT)).replace("\\", "/")
    out: list[tuple[str, int, str]] = []
    for node in ast.walk(tree):
        if not _is_to_datetime_call(node):
            continue
        col = _first_arg_subscript_key(node)
        if col is None:
            continue
        if col in _TIMESTAMP_COLUMN_NAMES and not _has_utc_kwarg(node):
            out.append((rel, node.lineno, col))
    return out


def test_to_datetime_on_timestamp_columns_passes_utc_true() -> None:
    violations: list[str] = []
    for path in _iter_python_files():
        for rel, line, col in _collect_violations(path):
            violations.append(
                f"{rel}:{line} pd.to_datetime on column {col!r} without "
                "utc=True. Either pass utc=True (PR #95 TZ-2) or, if "
                "the column is actually date-only, add it to "
                "_DATE_ONLY_COLUMN_NAMES in this test."
            )
    assert not violations, (
        "to_datetime utc=True discipline violations:\n  " + "\n  ".join(violations)
    )


def test_timestamp_and_date_only_column_sets_are_disjoint() -> None:
    overlap = _TIMESTAMP_COLUMN_NAMES & _DATE_ONLY_COLUMN_NAMES
    assert not overlap, (
        f"Column name(s) classified as BOTH timestamp and date-only: "
        f"{sorted(overlap)}. Pick one — a column cannot be both."
    )


def test_pin_walks_at_least_one_to_datetime_call() -> None:
    """Belt-and-braces: ensure the AST walker actually finds calls."""
    seen = 0
    for path in _iter_python_files():
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            if _is_to_datetime_call(node):
                seen += 1
    assert seen > 0, (
        "Pin found zero pd.to_datetime calls in the workspace — the "
        "AST walker may have drifted (or to_datetime was fully "
        "removed). Verify with: grep -rn 'to_datetime(' --include='*.py'"
    )
