"""Pin: every ``@lru_cache`` decorator carries an explicit ``maxsize``.

Background
==========

Default ``@lru_cache()`` (no args) is unbounded → silent memory leak in
long-running Streamlit / Terminal sessions. PR #98 (A-2) bounded the
two ``scripts/smc_newsapi_ai.py`` cases. This pin keeps it that way
and forces every future cache to either:

1. Pass an explicit ``maxsize=N`` (preferred), or
2. Use ``@cache`` from functools 3.9+ if unbounded is intentional
   (forces the dev to spell out the choice rather than inheriting the
   default).

Scope: workspace Python files only — third-party packages under
``.venv/`` are excluded.

Currently expected: 3 sites in 2 modules (all bounded) — see
:data:`_BASELINE_LRU_CACHE_SITES`. Adding a new ``@lru_cache`` site
without ``maxsize=`` fails the pin; adding a new bounded site requires
extending the baseline.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Directories that must NEVER be scanned (vendored / generated).
_EXCLUDE_DIR_NAMES = frozenset({
    ".venv", ".git", "__pycache__", "node_modules",
    ".mypy_cache", ".pytest_cache", "build", "dist",
})

# Baseline of known-and-approved bounded ``@lru_cache(maxsize=N)`` sites.
# Format: (relative_path, function_name).
_BASELINE_LRU_CACHE_SITES: frozenset[tuple[str, str]] = frozenset({
    ("scripts/smc_newsapi_ai.py", "_uppercase_exact_pattern"),
    ("scripts/smc_newsapi_ai.py", "_strict_market_context_pattern"),
    ("newsstack_fmp/_market_cal.py", "us_equity_market_holidays"),
    ("governance/run_manifest.py", "_git_sha"),
    # maxsize=1 — single process-wide pin_registry.toml snapshot (ADR-0009).
    ("tests/_pin_registry.py", "_load"),
    # maxsize=8 — memoizes the daily_bars workbook parse per (path, mtime);
    # domain is the handful of production workbooks read during a run.
    ("smc_core/cached_workbook_reader.py", "_read_daily_bars_cached"),
    # maxsize=64 — memoizes holiday-date computation per (calendar_code, year);
    # domain is the multi-year holiday calendar window used by market-hours checks.
    ("services/live_overlay_daemon/market_hours.py", "_holiday_dates_for_year"),
})


def _iter_python_files() -> list[Path]:
    out: list[Path] = []
    for path in REPO_ROOT.rglob("*.py"):
        # Skip excluded directories anywhere in the path.
        if any(part in _EXCLUDE_DIR_NAMES for part in path.relative_to(REPO_ROOT).parts):
            continue
        out.append(path)
    return sorted(out)


def _is_lru_cache_decorator(node: ast.expr) -> bool:
    """Return True if ``node`` is a ``lru_cache`` reference (with or without call)."""
    target = node.func if isinstance(node, ast.Call) else node
    if isinstance(target, ast.Name) and target.id == "lru_cache":
        return True
    return bool(isinstance(target, ast.Attribute) and target.attr == "lru_cache")


def _has_explicit_maxsize(node: ast.expr) -> bool:
    """Return True iff the decorator is a ``Call`` with a ``maxsize=`` kwarg
    whose value is **not** the literal ``None``.

    ``@lru_cache(maxsize=None)`` is *technically* explicit but semantically
    equivalent to an unbounded cache — the very bug class this pin is
    meant to prevent. If unbounded is intentional, switch to
    ``@functools.cache`` (forces the dev to spell out the choice).
    """
    if not isinstance(node, ast.Call):
        return False
    for kw in node.keywords:
        if kw.arg != "maxsize":
            continue
        # Reject ``maxsize=None`` — explicit-but-unbounded is still unbounded.
        return not (isinstance(kw.value, ast.Constant) and kw.value.value is None)
    return False


def _collect_lru_cache_sites(path: Path) -> list[tuple[str, str, int, bool]]:
    """Return ``(rel_path, func_name, line, has_maxsize)`` for each site."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError):
        return []
    rel = str(path.relative_to(REPO_ROOT)).replace("\\", "/")
    out: list[tuple[str, str, int, bool]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        for deco in node.decorator_list:
            if _is_lru_cache_decorator(deco):
                out.append((rel, node.name, deco.lineno, _has_explicit_maxsize(deco)))
    return out


def test_every_lru_cache_decorator_has_explicit_maxsize() -> None:
    """No bare ``@lru_cache`` / ``@lru_cache()`` allowed — must specify maxsize."""
    violations: list[str] = []
    for path in _iter_python_files():
        for rel, fn, line, has_max in _collect_lru_cache_sites(path):
            if not has_max:
                violations.append(
                    f"{rel}:{line} @lru_cache on `{fn}` has no explicit "
                    "maxsize=. Default unbounded → memory leak. Add "
                    "`maxsize=N` (PR #98 A-2 contract)."
                )
    assert not violations, (
        "lru_cache discipline violations:\n  " + "\n  ".join(violations)
    )


def test_lru_cache_sites_match_baseline() -> None:
    """Site inventory matches the documented baseline; new sites need review."""
    observed: set[tuple[str, str]] = set()
    for path in _iter_python_files():
        for rel, fn, _line, _has_max in _collect_lru_cache_sites(path):
            observed.add((rel, fn))
    extra = observed - _BASELINE_LRU_CACHE_SITES
    missing = _BASELINE_LRU_CACHE_SITES - observed
    assert not extra, (
        "New @lru_cache sites detected — extend "
        "_BASELINE_LRU_CACHE_SITES after confirming the maxsize is "
        f"sized for the cache domain (symbol? date-window?): {sorted(extra)}"
    )
    assert not missing, (
        "Baseline @lru_cache sites disappeared — if removal was "
        f"intentional, shrink the baseline: {sorted(missing)}"
    )


# ── Belt-and-braces: regex sweep against accidentally bare @lru_cache ──
# AST analysis catches the structural cases; this regex catches a typo
# variant where someone writes ``@lru_cache  # comment`` and the AST
# parses it but a future contributor copy-pastes the line and drops
# the parens. Skips third-party.
_BARE_LRU_RE = re.compile(
    r"^\s*@(functools\.)?lru_cache\s*(?:#.*)?$",
    re.MULTILINE,
)


def test_no_bare_lru_cache_decorator_lines() -> None:
    bad: list[str] = []
    for path in _iter_python_files():
        rel = str(path.relative_to(REPO_ROOT)).replace("\\", "/")
        # Skip the test files themselves (they cite ``@lru_cache`` patterns
        # in docstrings/regexes for educational purposes).
        if rel.startswith("tests/"):
            continue
        text = path.read_text(encoding="utf-8")
        for match in _BARE_LRU_RE.finditer(text):
            line_no = text[: match.start()].count("\n") + 1
            bad.append(f"{rel}:{line_no}")
    assert not bad, (
        "Bare @lru_cache decorator lines (no parens, no maxsize) "
        f"detected: {bad}. Use @lru_cache(maxsize=N)."
    )
